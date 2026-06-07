"""LangChain ``BaseTool`` implementation backed by a LatchGate action.

Each tool instance wraps exactly one registered action. Tool execution goes
through the full LatchGate enforcement pipeline: auth => policy => WASM sandbox
=> verification => signed receipt. The LLM never holds credentials and never
contacts external systems directly.

Error semantics
---------------
- **Policy denied / schema violation / budget exhausted** => ``ToolException``
  with a structured message the LLM can reason about.
- **Pending approval** => ``ToolException`` with a human-readable message.
  The ``approval_id`` is emitted via callback side-channel for the orchestrator.
- **Transport / infrastructure failure** => ``ToolException`` with a
  retryable indicator.
- Exceptions are never swallowed — every failure is surfaced faithfully.
"""

from __future__ import annotations

import json
import logging
from typing import Any, ClassVar

from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool, ToolException
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
from latchgate_common.schema import schema_to_pydantic
from latchgate_common.serialization import serialize_result
from latchgate_common.sync import run_sync

logger = logging.getLogger(__name__)


class LatchGateTool(BaseTool):
    """LangChain tool backed by a single LatchGate protected action.

    Attributes
    ----------
    name:
        The LatchGate ``action_id`` — matches the manifest identifier.
    description:
        Auto-generated from action metadata (risk level, side effects,
        egress profile, database statements). Gives the LLM enough context
        to decide when to invoke this tool.
    args_schema:
        Pydantic model dynamically generated from the action's JSON Schema.
        LangChain uses this for argument validation and for populating the
        ``parameters`` field in tool-call function descriptions.
    handle_tool_error:
        Always ``True`` — LatchGate errors produce ``ToolException`` so the
        LLM can see structured error messages and decide how to proceed.
    on_audit:
        Optional callback invoked with receipt metadata after each execution.
    """

    # Surface errors to the LLM as text instead of crashing the agent.
    handle_tool_error: bool = True  # type: ignore[assignment]

    # Instance fields (set at construction, not by the LLM).
    client: LatchGateClient
    action_id: str
    action_version: str = "0.0.0"
    action_risk_level: str = "unknown"
    on_audit: Any = None  # AuditCallback | None — Any avoids Pydantic Protocol introspection

    model_config: ClassVar[dict[str, Any]] = {"arbitrary_types_allowed": True}

    def _run(
        self,
        run_manager: CallbackManagerForToolRun | None = None,
        **kwargs: Any,
    ) -> str:
        """Synchronous fallback — delegates to the async path via background thread."""
        return run_sync(self._arun(run_manager=None, **kwargs))

    async def _arun(
        self,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
        **kwargs: Any,
    ) -> str:
        """Execute the action through LatchGate and return the result as JSON text.

        When a ``run_manager`` is provided (LangSmith, LangFuse, or any
        LangChain callback handler), execution events are emitted so tool
        calls appear in traces.

        Returns
        -------
        Serialized JSON of the action output on success.

        Raises
        ------
        ToolException
            On any LatchGate denial, approval requirement, budget exhaustion,
            or infrastructure error. The message is structured for LLM consumption.
        """
        params = kwargs
        logger.debug("executing action '%s' with params: %s", self.action_id, params)

        try:
            result: ActionResult = await self.client.execute(self.action_id, params)
        except LatchGateApprovalRequired as exc:
            if run_manager:
                await run_manager.on_tool_error(exc)
                await run_manager.on_text(
                    json.dumps({"approval_id": exc.approval_id}, default=str),
                    verbose=False,
                    name="latchgate_approval",
                )
            raise ToolException(
                f"Action '{self.action_id}' requires human approval. "
                f"The orchestrator has been notified."
            ) from exc
        except LatchGateBudgetExhausted as exc:
            if run_manager:
                await run_manager.on_tool_error(exc)
            raise ToolException(
                f"Budget exhausted for action '{self.action_id}'. "
                f"Obtain a new lease with a fresh budget allocation."
            ) from exc
        except LatchGateDenied as exc:
            if run_manager:
                await run_manager.on_tool_error(exc)
            raise ToolException(
                f"Action '{self.action_id}' denied: {exc.reason}. "
                f"The request does not satisfy the gate's policy."
            ) from exc
        except LatchGateError as exc:
            if run_manager:
                await run_manager.on_tool_error(exc)
            raise ToolException(f"LatchGate error on action '{self.action_id}': {exc}") from exc

        # Emit receipt metadata via callback (side-channel, not model-visible).
        if run_manager:
            await run_manager.on_text(
                json.dumps(
                    {
                        "receipt_id": result.receipt_id,
                        "trace_id": result.trace_id,
                        "verification": result.verification,
                    },
                    default=str,
                ),
                verbose=False,
                name="latchgate_audit",
            )

        return serialize_result(result, action_id=self.action_id, on_audit=self.on_audit)

    @classmethod
    def from_descriptor(
        cls,
        descriptor: ActionDescriptor,
        client: LatchGateClient,
        *,
        on_audit: AuditCallback | None = None,
    ) -> LatchGateTool:
        """Create a tool instance from a discovered action descriptor."""
        schema_model = schema_to_pydantic(descriptor.action_id, descriptor.request_schema)

        return cls(
            name=descriptor.action_id,
            description=descriptor.description,
            args_schema=schema_model,
            client=client,
            action_id=descriptor.action_id,
            action_version=descriptor.version,
            action_risk_level=descriptor.risk_level,
            on_audit=on_audit,
        )
