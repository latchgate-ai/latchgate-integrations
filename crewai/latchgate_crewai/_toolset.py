"""CrewAI tools for LatchGate — auto-discovers actions and creates tools.

Usage::

    from latchgate_crewai import LatchGateToolset

    # Async (preferred):
    toolset = await LatchGateToolset.create(gate_url="http://localhost:3000")
    tools = toolset.all()

    # Sync convenience (outside an event loop):
    toolset = LatchGateToolset.create_sync(gate_url="http://localhost:3000")
    tools = toolset.all()

    # Use with any CrewAI agent:
    from crewai import Agent
    agent = Agent(role="Worker", goal="...", tools=tools)

The toolset connects to LatchGate, discovers all registered actions, fetches
their JSON Schemas, and wraps each as a :class:`LatchGateTool`. The underlying
:class:`LatchGateClient` uses lazy-connect — the DPoP lease is obtained on
the first tool invocation, not at toolset creation time.
"""

from __future__ import annotations

import logging
import os

from crewai.tools import BaseTool
from latchgate import LatchGateClient
from latchgate_common.audit import AuditCallback
from latchgate_common.discovery import ActionDescriptor, discover_actions
from latchgate_common.sync import run_sync
from latchgate_common.transport import DEFAULT_PUBLIC_BASE_URL, resolve_discovery_params

from latchgate_crewai._tool import LatchGateTool

logger = logging.getLogger(__name__)


class LatchGateToolset:
    """Container that wraps all LatchGate actions as CrewAI tools.

    Use :meth:`create` (async) or :meth:`create_sync` (sync) to construct.
    Direct instantiation is internal — callers should use the factories.
    """

    def __init__(
        self,
        *,
        client: LatchGateClient,
        tools: list[LatchGateTool],
        gate_url: str = "",
    ) -> None:
        self._client = client
        self._tools = tools
        self._gate_url = gate_url

    def all(self) -> list[BaseTool]:
        """Return all discovered LatchGate actions as CrewAI tools."""
        return list(self._tools)

    def get(self, action_id: str) -> LatchGateTool:
        """Return a single tool by action_id.

        Raises
        ------
        KeyError
            If the action_id was not discovered.
        """
        for tool in self._tools:
            if tool.action_id == action_id:
                return tool
        raise KeyError(
            f"action '{action_id}' not found. Available: {[t.action_id for t in self._tools]}"
        )

    @property
    def client(self) -> LatchGateClient:
        """The underlying LatchGate client (for direct API access if needed)."""
        return self._client

    @property
    def action_ids(self) -> list[str]:
        """List of discovered action IDs."""
        return [t.action_id for t in self._tools]

    async def close(self) -> None:
        """Close the underlying LatchGate client transport."""
        await self._client.close()

    async def __aenter__(self) -> LatchGateToolset:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ── Factories ─────────────────────────────────────────────────────────

    @classmethod
    async def create(
        cls,
        *,
        gate_url: str | None = None,
        agent_id: str = "crewai",
        client: LatchGateClient | None = None,
        include: set[str] | None = None,
        exclude: set[str] | None = None,
        discovery_timeout: float = 15.0,
        on_audit: AuditCallback | None = None,
    ) -> LatchGateToolset:
        """Discover LatchGate actions and create a ready-to-use toolset.

        Parameters
        ----------
        gate_url:
            Base URL of the running LatchGate instance. Required when
            ``client`` is not provided. Falls back to ``LATCHGATE_URL``.
        agent_id:
            Agent identifier for lease requests. Default: ``"crewai"``.
        client:
            Optional pre-configured :class:`LatchGateClient`.
        include:
            Only wrap actions whose ``action_id`` is in this set.
        exclude:
            Skip actions whose ``action_id`` is in this set.
        discovery_timeout:
            HTTP timeout for discovery in seconds.
        on_audit:
            Optional callback invoked with receipt metadata after each execution.
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

        tools = [LatchGateTool.from_descriptor(d, client, on_audit=on_audit) for d in descriptors]

        logger.info(
            "LatchGateToolset ready: %d tools from %s",
            len(tools),
            effective_url,
        )
        return cls(client=client, tools=tools, gate_url=effective_url)

    @classmethod
    def create_sync(
        cls,
        *,
        gate_url: str | None = None,
        agent_id: str = "crewai",
        client: LatchGateClient | None = None,
        include: set[str] | None = None,
        exclude: set[str] | None = None,
        discovery_timeout: float = 15.0,
        on_audit: AuditCallback | None = None,
    ) -> LatchGateToolset:
        """Synchronous factory — convenience wrapper around :meth:`create`.

        Safe to call from any context, including inside a running event
        loop (Jupyter, FastAPI, Celery). Uses a background thread when
        an event loop is already running.
        """
        return run_sync(
            cls.create(
                gate_url=gate_url,
                agent_id=agent_id,
                client=client,
                include=include,
                exclude=exclude,
                discovery_timeout=discovery_timeout,
                on_audit=on_audit,
            )
        )

    @classmethod
    def from_descriptors(
        cls,
        descriptors: list[ActionDescriptor],
        *,
        client: LatchGateClient,
        on_audit: AuditCallback | None = None,
    ) -> LatchGateToolset:
        """Create from pre-fetched action descriptors (no network calls)."""
        tools = [LatchGateTool.from_descriptor(d, client, on_audit=on_audit) for d in descriptors]
        return cls(client=client, tools=tools)
