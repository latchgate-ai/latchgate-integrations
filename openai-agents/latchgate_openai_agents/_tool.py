"""OpenAI Agents SDK ``FunctionTool`` instances backed by LatchGate actions.

Each tool wraps a single registered action. Execution goes through
the full LatchGate enforcement pipeline: auth => policy => WASM sandbox
=> verification => signed receipt.

Error semantics
---------------
``on_invoke_tool`` returns a string result. On LatchGate errors, a
structured error string is returned so the agent can reason about it.
No exceptions propagate from tool invocation — the Agents SDK treats
the returned string as the tool output regardless.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agents import FunctionTool, RunContextWrapper
from latchgate import (
    ActionResult,
    LatchGateApprovalRequired,
    LatchGateBudgetExhausted,
    LatchGateClient,
    LatchGateDenied,
    LatchGateError,
)
from latchgate_common.audit import AuditCallback
from latchgate_common.discovery import ActionDescriptor
from latchgate_common.serialization import serialize_result

logger = logging.getLogger(__name__)


def create_tool(
    descriptor: ActionDescriptor,
    client: LatchGateClient,
    *,
    on_audit: AuditCallback | None = None,
) -> FunctionTool:
    """Create an OpenAI Agents SDK FunctionTool from a LatchGate action descriptor.

    The returned tool can be passed directly to ``Agent(tools=[...])``.
    """

    async def on_invoke(ctx: RunContextWrapper[Any], input_str: str) -> str:
        """Execute the action through LatchGate.

        Parameters
        ----------
        ctx:
            Agent run context (unused — LatchGate manages its own auth).
        input_str:
            JSON-encoded arguments from the LLM.
        """
        try:
            params: dict[str, Any] = json.loads(input_str) if input_str else {}
        except (json.JSONDecodeError, TypeError):
            return f"ERROR: Invalid JSON input for action '{descriptor.action_id}': {input_str!r}"

        logger.debug("executing action '%s' with params: %s", descriptor.action_id, params)

        try:
            result: ActionResult = await client.execute(descriptor.action_id, params)
        except LatchGateApprovalRequired as exc:
            logger.info(
                "approval required: action=%s approval_id=%s", descriptor.action_id, exc.approval_id
            )
            return (
                f"ERROR: Action '{descriptor.action_id}' requires human approval. "
                f"The orchestrator has been notified."
            )
        except LatchGateBudgetExhausted:
            return (
                f"ERROR: Budget exhausted for action '{descriptor.action_id}'. "
                f"Obtain a new lease with a fresh budget allocation."
            )
        except LatchGateDenied as exc:
            return (
                f"ERROR: Action '{descriptor.action_id}' denied: {exc.reason}. "
                f"The request does not satisfy the gate's policy."
            )
        except LatchGateError as exc:
            return f"ERROR: LatchGate error on action '{descriptor.action_id}': {exc}"

        return serialize_result(result, action_id=descriptor.action_id, on_audit=on_audit)

    # Build the JSON Schema for the tool's parameters.
    # The Agents SDK passes this to the LLM for function-call generation.
    schema = _to_strict_schema(descriptor.request_schema)

    return FunctionTool(
        name=descriptor.action_id,
        description=descriptor.description,
        params_json_schema=schema,
        on_invoke_tool=on_invoke,
    )


def _to_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert a JSON Schema to OpenAI Agents SDK strict-compatible format.

    The Agents SDK enforces strict JSON schema rules recursively:
    - ``additionalProperties`` must be ``false`` on all objects
    - ``required`` must list all properties
    - Top level must be ``type: "object"``

    To satisfy the "required lists all properties" constraint without
    losing optional-field semantics, originally optional fields are
    wrapped in ``anyOf: [<original>, {"type": "null"}]``. The model
    can pass ``null`` for fields it wants to omit.
    """
    if schema.get("type") != "object":
        return {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }

    result: dict[str, Any] = {"type": "object"}
    original_required: set[str] = set(schema.get("required", []))

    # Recursively clean nested properties.
    old_props = schema.get("properties", {})
    new_props: dict[str, Any] = {}
    for key, prop in old_props.items():
        if isinstance(prop, dict) and prop.get("type") == "object":
            cleaned = _to_strict_schema(prop)
        else:
            cleaned = prop

        # Wrap originally optional fields as nullable so the model can
        # pass null instead of being forced to fabricate a value.
        if key not in original_required and isinstance(cleaned, dict):
            cleaned = _make_nullable(cleaned)

        new_props[key] = cleaned

    result["properties"] = new_props
    # Strict mode requires ALL properties listed — nullable wrapping
    # preserves the optional semantics.
    result["required"] = list(new_props.keys())
    result["additionalProperties"] = False

    if "description" in schema:
        result["description"] = schema["description"]

    return result


def _make_nullable(prop: dict[str, Any]) -> dict[str, Any]:
    """Wrap a property schema in anyOf with null to make it optional.

    If the property already allows null (via anyOf or type), return as-is.
    The description is lifted to the wrapper and removed from the inner
    schema to prevent duplication.
    """
    # Already nullable.
    if prop.get("type") == "null":
        return prop
    if "anyOf" in prop and any(
        isinstance(v, dict) and v.get("type") == "null" for v in prop["anyOf"]
    ):
        return prop

    # Separate the description from the inner schema to avoid duplication
    # at two levels of the anyOf structure.
    description = prop.get("description")
    inner = {k: v for k, v in prop.items() if k != "description"} if description else prop

    result: dict[str, Any] = {"anyOf": [inner, {"type": "null"}]}
    if description:
        result["description"] = description
    return result
