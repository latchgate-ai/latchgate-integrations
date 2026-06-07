"""CrewAI ``BaseTool`` implementation backed by a LatchGate action.

Each tool instance wraps exactly one registered action. Tool execution goes
through the full LatchGate enforcement pipeline: auth => policy => WASM sandbox
=> verification => signed receipt. The LLM never holds credentials and never
contacts external systems directly.

Error semantics
---------------
CrewAI does not have a ``ToolException`` mechanism like LangChain.
Instead, errors are returned as structured text strings so the agent
can reason about failures:

- **Policy denied / schema violation / budget exhausted** => error string
  with the reason, giving the agent enough context to adjust.
- **Pending approval** => error string indicating the orchestrator has been
  notified. The ``approval_id`` is emitted via log side-channel.
- **Transport / infrastructure failure** => error string indicating a
  transient issue.

No exception is swallowed — but they are caught at the tool boundary
and converted to agent-readable output. Uncaught exceptions from the
CrewAI framework itself (e.g. Pydantic validation) propagate normally.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from crewai.tools import BaseTool
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
    """CrewAI tool backed by a single LatchGate protected action.

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
    """

    # Instance fields (set at construction, not by the LLM).
    client: LatchGateClient
    action_id: str
    action_version: str = "0.0.0"
    action_risk_level: str = "unknown"
    on_audit: Any = None  # AuditCallback | None — Any avoids Pydantic Protocol introspection

    model_config: ClassVar[dict[str, Any]] = {"arbitrary_types_allowed": True}

    # ── Sync execution (primary for CrewAI) ───────────────────────────────

    def _run(self, **kwargs: Any) -> str:
        """Execute the action through LatchGate.

        CrewAI calls ``_run`` synchronously. The async LatchGateClient
        is bridged via a background thread with its own event loop —
        safe in Jupyter, FastAPI, Celery, and any other environment
        with an already-running loop.

        Returns
        -------
        Serialized JSON of the action output on success, or a structured
        error message on failure.
        """
        return run_sync(self._arun(**kwargs))

    # ── Async execution ───────────────────────────────────────────────────

    async def _arun(self, **kwargs: Any) -> str:
        """Async execution path — called by ``_run`` or directly by async crews."""
        params = kwargs
        logger.debug("executing action '%s' with params: %s", self.action_id, params)

        try:
            result: ActionResult = await self.client.execute(self.action_id, params)
        except LatchGateApprovalRequired as exc:
            logger.info(
                "approval required: action=%s approval_id=%s", self.action_id, exc.approval_id
            )
            return (
                f"ERROR: Action '{self.action_id}' requires human approval. "
                f"The orchestrator has been notified."
            )
        except LatchGateBudgetExhausted:
            return (
                f"ERROR: Budget exhausted for action '{self.action_id}'. "
                f"Obtain a new lease with a fresh budget allocation."
            )
        except LatchGateDenied as exc:
            return (
                f"ERROR: Action '{self.action_id}' denied: {exc.reason}. "
                f"The request does not satisfy the gate's policy."
            )
        except LatchGateError as exc:
            return f"ERROR: LatchGate error on action '{self.action_id}': {exc}"

        return serialize_result(result, action_id=self.action_id, on_audit=self.on_audit)

    # ── Factory ───────────────────────────────────────────────────────────

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
