"""Result serialization for model-facing output.

Only the action output is returned to the model. Receipt and trace
metadata are logged at INFO level for orchestrator consumption —
exposing them in the model context would leak enforcement internals
to a potentially compromised model.

This is security-critical: every integration package must use this
single implementation to ensure consistent redaction.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from latchgate_common.audit import AuditCallback, AuditRecord

if TYPE_CHECKING:
    from latchgate import ActionResult

logger = logging.getLogger(__name__)


def serialize_result(
    result: ActionResult,
    *,
    action_id: str = "",
    on_audit: AuditCallback | None = None,
) -> str:
    """Serialize an ActionResult to a JSON string for the model.

    Returns only ``result.output``. Receipt ID, trace ID, and verification
    are emitted via structured log at INFO level — never in the return value.

    Parameters
    ----------
    result:
        The execution result from LatchGate.
    action_id:
        The action that produced this result (for audit context).
    on_audit:
        Optional callback invoked with the audit metadata. Called
        *after* serialization, does not affect the return value.
    """
    logger.info(
        "action completed: receipt_id=%s trace_id=%s verification=%s",
        result.receipt_id,
        result.trace_id,
        result.verification,
    )

    if on_audit is not None:
        on_audit(
            AuditRecord(
                action_id=action_id,
                receipt_id=result.receipt_id,
                trace_id=result.trace_id,
                verification=result.verification,
            )
        )

    return json.dumps(result.output, default=str, ensure_ascii=False)
