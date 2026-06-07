"""Audit metadata callback for LatchGate integrations.

After every successful action execution, LatchGate returns a receipt ID,
trace ID, and verification outcome. By default this metadata is logged at
INFO level. The ``AuditCallback`` protocol allows orchestrators to consume
it programmatically — for example to store receipts in a database, emit
OpenTelemetry spans, or feed a compliance pipeline.

The callback is invoked *after* the model-facing output has been
serialized. It never affects the return value seen by the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AuditRecord:
    """Audit metadata from a single LatchGate action execution."""

    action_id: str
    receipt_id: str | None
    trace_id: str | None
    verification: Any


class AuditCallback(Protocol):
    """Protocol for audit metadata handlers.

    Implementations may be sync or async — the integration layer
    calls whichever variant the framework supports.
    """

    def __call__(self, record: AuditRecord) -> None: ...
