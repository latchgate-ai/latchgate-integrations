"""Shared internals for LatchGate framework integrations.

This package provides the canonical implementation of discovery, schema
conversion, result serialization, and transport resolution used by every
Python integration package (LangChain, CrewAI, OpenAI Agents, Pydantic AI).

End users should install a framework-specific package (e.g.
``latchgate-langchain``) rather than depending on this package directly.

Security-relevant logic — especially the ``expose_security_details``
redaction in :func:`build_description` and the output-only filtering
in :func:`serialize_result` — lives here exactly once.
"""

from latchgate_common.audit import AuditCallback, AuditRecord
from latchgate_common.discovery import (
    ActionDescriptor,
    build_description,
    discover_actions,
)
from latchgate_common.schema import (
    JSON_TYPE_MAP,
    resolve_type,
    schema_to_pydantic,
)
from latchgate_common.serialization import serialize_result
from latchgate_common.sync import run_sync
from latchgate_common.transport import resolve_discovery_params

__all__ = [
    "JSON_TYPE_MAP",
    "ActionDescriptor",
    "AuditCallback",
    "AuditRecord",
    "build_description",
    "discover_actions",
    "resolve_discovery_params",
    "resolve_type",
    "run_sync",
    "schema_to_pydantic",
    "serialize_result",
]

__version__ = "0.1.0"
