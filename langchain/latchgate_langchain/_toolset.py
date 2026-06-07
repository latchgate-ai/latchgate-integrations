"""LangChain toolset for LatchGate — auto-discovers actions and creates tools.

Usage::

    from latchgate_langchain import LatchGateToolset

    toolset = await LatchGateToolset.create(
        gate_url="http://localhost:3000",
        agent_id="my-langchain-agent",
    )
    tools = toolset.get_tools()

    # Use with any LangChain agent:
    from langchain.agents import AgentExecutor, create_tool_calling_agent
    agent = create_tool_calling_agent(llm, tools, prompt)

The toolset connects to LatchGate, discovers all registered actions, fetches
their JSON Schemas, and wraps each as a :class:`LatchGateTool`. The underlying
:class:`LatchGateClient` uses lazy-connect — the DPoP lease is obtained on
the first tool invocation, not at toolset creation time.
"""

from __future__ import annotations

import logging
import os

from langchain_core.tools import BaseTool
from latchgate import LatchGateClient
from latchgate_common.audit import AuditCallback
from latchgate_common.discovery import ActionDescriptor, discover_actions
from latchgate_common.transport import DEFAULT_PUBLIC_BASE_URL, resolve_discovery_params

from latchgate_langchain._tool import LatchGateTool

logger = logging.getLogger(__name__)


class LatchGateToolset:
    """Toolset that wraps all LatchGate actions as LangChain tools.

    Parameters
    ----------
    client:
        A :class:`LatchGateClient` instance. The toolset takes ownership
        of the client lifecycle when created via :meth:`create`. When
        constructed directly, the caller is responsible for closing it.
    tools:
        Pre-built list of :class:`LatchGateTool` instances.

    Notes
    -----
    Prefer :meth:`create` for standard usage — it handles discovery,
    schema fetching, and client construction in one call.
    """

    def __init__(
        self,
        *,
        client: LatchGateClient,
        tools: list[LatchGateTool],
    ) -> None:
        self._client = client
        self._tools = tools

    def get_tools(self) -> list[BaseTool]:
        """Return all discovered LatchGate actions as LangChain tools."""
        return list(self._tools)

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

    # ── Factory ───────────────────────────────────────────────────────────

    @classmethod
    async def create(
        cls,
        *,
        gate_url: str | None = None,
        agent_id: str = "langchain",
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
            ``client`` is not provided. Falls back to ``LATCHGATE_URL``
            env var if the client reads it.
        agent_id:
            Agent identifier for lease requests. Default: ``"langchain"``.
        client:
            Optional pre-configured :class:`LatchGateClient`. When provided,
            ``gate_url`` is used only for discovery (unauthenticated HTTP)
            and the client is used for authenticated execution.
        include:
            If provided, only wrap actions whose ``action_id`` is in this set.
        exclude:
            If provided, skip actions whose ``action_id`` is in this set.
        discovery_timeout:
            HTTP timeout for the discovery phase in seconds.

        Returns
        -------
        A :class:`LatchGateToolset` with one :class:`LatchGateTool` per
        discovered action.

        Raises
        ------
        httpx.HTTPError
            If the gate's discovery endpoints are unreachable.
        ValueError
            If neither ``gate_url`` nor ``client`` is provided.
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
        return cls(client=client, tools=tools)

    @classmethod
    def from_descriptors(
        cls,
        descriptors: list[ActionDescriptor],
        *,
        client: LatchGateClient,
        on_audit: AuditCallback | None = None,
    ) -> LatchGateToolset:
        """Create a toolset from pre-fetched action descriptors.

        Useful when you want to control discovery separately or build
        a toolset from a subset of actions without hitting the network.

        This is a synchronous factory — no I/O is performed.
        """
        tools = [LatchGateTool.from_descriptor(d, client, on_audit=on_audit) for d in descriptors]
        return cls(client=client, tools=tools)
