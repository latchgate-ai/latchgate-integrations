"""OpenAI Agents SDK tools for LatchGate — auto-discovers actions.

Usage::

    from latchgate_openai_agents import latchgate_tools
    from agents import Agent, Runner

    tools = await latchgate_tools(gate_url="http://localhost:3000")
    agent = Agent(name="Worker", tools=tools)
    result = await Runner.run(agent, "Fetch https://httpbin.org/get")
"""

from __future__ import annotations

import logging
import os

from agents import FunctionTool
from latchgate import LatchGateClient
from latchgate_common.audit import AuditCallback
from latchgate_common.discovery import ActionDescriptor, discover_actions
from latchgate_common.transport import DEFAULT_PUBLIC_BASE_URL, resolve_discovery_params

from latchgate_openai_agents._tool import create_tool

logger = logging.getLogger(__name__)


async def latchgate_tools(
    *,
    gate_url: str | None = None,
    agent_id: str = "openai-agents",
    client: LatchGateClient | None = None,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
    discovery_timeout: float = 15.0,
    on_audit: AuditCallback | None = None,
) -> list[FunctionTool]:
    """Discover LatchGate actions and return them as OpenAI Agents SDK tools.

    Parameters
    ----------
    gate_url:
        Base URL of the LatchGate instance. Falls back to ``LATCHGATE_URL``.
    agent_id:
        Agent identifier for lease requests. Default: ``"openai-agents"``.
    client:
        Optional pre-configured :class:`LatchGateClient`.
    include:
        Only wrap actions whose ``action_id`` is in this set.
    exclude:
        Skip actions whose ``action_id`` is in this set.
    discovery_timeout:
        HTTP timeout for discovery in seconds.

    Returns
    -------
    List of ``FunctionTool`` instances ready for ``Agent(tools=[...])``.
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

    tools = [create_tool(d, client, on_audit=on_audit) for d in descriptors]

    logger.info(
        "latchgate_tools ready: %d tools from %s",
        len(tools),
        effective_url,
    )
    return tools


def latchgate_tools_from_descriptors(
    descriptors: list[ActionDescriptor],
    *,
    client: LatchGateClient,
    on_audit: AuditCallback | None = None,
) -> list[FunctionTool]:
    """Create tools from pre-fetched descriptors (no network calls)."""
    return [create_tool(d, client, on_audit=on_audit) for d in descriptors]
