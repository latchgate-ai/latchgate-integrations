"""Discovery transport resolution for LatchGate integrations.

Resolves the gate URL and optional HTTP transport used during
action discovery. Supports explicit URLs, the ``LATCHGATE_URL``
environment variable, and UDS transport reuse from a pre-configured
:class:`LatchGateClient`.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from latchgate import LatchGateClient

# Server's default public_base_url — used for DPoP htu when no explicit
# gate_url is configured.  Must match ListenerConfig::default() in
# crates/latchgate-config/src/listener.rs.
DEFAULT_PUBLIC_BASE_URL = "http://localhost:3000"


def resolve_discovery_params(
    gate_url: str | None,
    client: LatchGateClient | None,
) -> tuple[str, httpx.AsyncClient | None]:
    """Resolve the gate URL and optional HTTP transport for discovery.

    Returns ``(url, http_client_or_none)``.  When a pre-configured
    :class:`LatchGateClient` is provided and no explicit ``gate_url`` is
    given, the client's internal ``httpx.AsyncClient`` (which may be
    configured for UDS transport) is reused for discovery.

    Raises
    ------
    ValueError
        If no usable gate URL can be determined from the arguments
        or the environment.
    """
    if gate_url is not None:
        return gate_url, None

    env_url = os.environ.get("LATCHGATE_URL")
    if env_url:
        return env_url, None

    # Use the client's own transport for discovery (supports UDS).
    if client is not None:
        url = getattr(client, "gate_url", None)
        if not url:
            raise ValueError(
                "gate_url is required. The provided client has no gate_url. "
                "Provide gate_url explicitly or set the LATCHGATE_URL "
                "environment variable."
            )
        return url, client.http_transport

    raise ValueError(
        "gate_url is required. Provide it explicitly, pass a client, "
        "or set the LATCHGATE_URL environment variable."
    )
