"""Pydantic AI toolset backed by LatchGate actions.

Implements ``AbstractToolset`` — the native Pydantic AI interface for
external tool collections. The toolset discovers actions from LatchGate's
REST API and provides them to the agent with full JSON Schema definitions.

Every tool call goes through LatchGate's enforcement pipeline:
auth => policy => WASM sandbox => verification => signed receipt.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from latchgate import (
    ActionResult,
    LatchGateApprovalRequired,
    LatchGateBudgetExhausted,
    LatchGateClient,
    LatchGateDenied,
    LatchGateError,
)
from latchgate_common.audit import AuditCallback
from latchgate_common.discovery import ActionDescriptor, discover_actions
from latchgate_common.serialization import serialize_result
from latchgate_common.transport import DEFAULT_PUBLIC_BASE_URL, resolve_discovery_params
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset

logger = logging.getLogger(__name__)


class LatchGateToolset(AbstractToolset[Any]):
    """Pydantic AI toolset that wraps all discovered LatchGate actions.

    Usage::

        from pydantic_ai import Agent
        from latchgate_pydantic_ai import LatchGateToolset

        toolset = await LatchGateToolset.create(gate_url="http://localhost:3000")
        agent = Agent("openai:gpt-4o", toolsets=[toolset])
        result = agent.run_sync("Fetch https://httpbin.org/get")

    Parameters
    ----------
    client:
        A :class:`LatchGateClient` instance.
    descriptors:
        Pre-fetched action descriptors.
    toolset_id:
        Optional identifier for this toolset instance. Defaults to ``"latchgate"``.
    """

    def __init__(
        self,
        *,
        client: LatchGateClient,
        descriptors: list[ActionDescriptor],
        toolset_id: str = "latchgate",
        on_audit: AuditCallback | None = None,
    ) -> None:
        self._client = client
        self._descriptors = {d.action_id: d for d in descriptors}
        self._toolset_id = toolset_id
        self._on_audit = on_audit

    # ── AbstractToolset interface ─────────────────────────────────────────

    def id(self) -> str:
        """Unique identifier for this toolset instance."""
        return self._toolset_id

    async def get_tools(self) -> list[ToolDefinition]:
        """Return tool definitions for all discovered LatchGate actions."""
        tools: list[ToolDefinition] = []
        for descriptor in self._descriptors.values():
            schema = _ensure_object_schema(descriptor.action_id, descriptor.request_schema)
            tools.append(
                ToolDefinition(
                    name=descriptor.action_id,
                    description=descriptor.description,
                    parameters_json_schema=schema,
                )
            )
        return tools

    async def call_tool(self, call: ToolCallPart) -> str:
        """Execute a LatchGate action and return the result as JSON text.

        All LatchGate errors are caught and returned as structured error
        strings so the model can reason about failures.
        """
        action_id = call.tool_name
        params: dict[str, Any] = call.args_as_dict()

        descriptor = self._descriptors.get(action_id)
        if descriptor is None:
            return f"ERROR: Unknown LatchGate action '{action_id}'."

        logger.debug("executing action '%s' with params: %s", action_id, params)

        try:
            result: ActionResult = await self._client.execute(action_id, params)
        except LatchGateApprovalRequired as exc:
            logger.info("approval required: action=%s approval_id=%s", action_id, exc.approval_id)
            return (
                f"ERROR: Action '{action_id}' requires human approval. "
                f"The orchestrator has been notified."
            )
        except LatchGateBudgetExhausted:
            return (
                f"ERROR: Budget exhausted for action '{action_id}'. "
                f"Obtain a new lease with a fresh budget allocation."
            )
        except LatchGateDenied as exc:
            return (
                f"ERROR: Action '{action_id}' denied: {exc.reason}. "
                f"The request does not satisfy the gate's policy."
            )
        except LatchGateError as exc:
            return f"ERROR: LatchGate error on action '{action_id}': {exc}"

        return serialize_result(result, action_id=action_id, on_audit=self._on_audit)

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Close the underlying LatchGate client transport."""
        await self._client.close()

    async def __aenter__(self) -> LatchGateToolset:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def client(self) -> LatchGateClient:
        """The underlying LatchGate client."""
        return self._client

    @property
    def action_ids(self) -> list[str]:
        """List of discovered action IDs."""
        return list(self._descriptors.keys())

    # ── Factories ─────────────────────────────────────────────────────────

    @classmethod
    async def create(
        cls,
        *,
        gate_url: str | None = None,
        agent_id: str = "pydantic-ai",
        client: LatchGateClient | None = None,
        include: set[str] | None = None,
        exclude: set[str] | None = None,
        discovery_timeout: float = 15.0,
        toolset_id: str = "latchgate",
        on_audit: AuditCallback | None = None,
    ) -> LatchGateToolset:
        """Discover LatchGate actions and create a ready-to-use toolset.

        Parameters
        ----------
        gate_url:
            Base URL of the LatchGate instance. Falls back to ``LATCHGATE_URL``.
        agent_id:
            Agent identifier for lease requests. Default: ``"pydantic-ai"``.
        client:
            Optional pre-configured :class:`LatchGateClient`.
        include:
            Only wrap actions whose ``action_id`` is in this set.
        exclude:
            Skip actions whose ``action_id`` is in this set.
        discovery_timeout:
            HTTP timeout for discovery in seconds.
        toolset_id:
            Identifier for this toolset instance. Default: ``"latchgate"``.
        """
        # UDS fallback — matches latchgate up (no TCP required).
        if gate_url is None and client is None and not os.environ.get("LATCHGATE_URL"):
            client = LatchGateClient(
                public_base_url=DEFAULT_PUBLIC_BASE_URL,
                agent_id=agent_id,
            )

        effective_url, discovery_http = resolve_discovery_params(gate_url, client)

        if client is None:
            client = LatchGateClient(base_url=effective_url, agent_id=agent_id)

        descriptors = await discover_actions(
            effective_url,
            timeout=discovery_timeout,
            include=include,
            exclude=exclude,
            _http=discovery_http,
        )

        logger.info(
            "LatchGateToolset ready: %d tools from %s",
            len(descriptors),
            effective_url,
        )
        return cls(client=client, descriptors=descriptors, toolset_id=toolset_id, on_audit=on_audit)


# ── Helpers ───────────────────────────────────────────────────────────────


def _ensure_object_schema(action_id: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Ensure the schema is a valid JSON Schema object for Pydantic AI.

    If the schema type is not ``"object"``, logs a warning and returns
    an empty object schema. This prevents silent data loss when the gate
    returns a malformed schema.
    """
    if schema.get("type") != "object":
        logger.warning(
            "action '%s' has schema type '%s' instead of 'object' — "
            "wrapping as empty object schema (original properties discarded)",
            action_id,
            schema.get("type", "<missing>"),
        )
        return {"type": "object", "properties": {}}
    return schema
