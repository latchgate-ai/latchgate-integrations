"""Pydantic AI integration for LatchGate — execution security kernel for AI agents.

Quick start::

    from pydantic_ai import Agent
    from latchgate_pydantic_ai import LatchGateToolset

    toolset = await LatchGateToolset.create(gate_url="http://localhost:3000")
    agent = Agent("openai:gpt-4o", toolsets=[toolset])
    result = agent.run_sync("Fetch https://httpbin.org/get")
"""

from latchgate_common.discovery import ActionDescriptor, discover_actions

from latchgate_pydantic_ai._toolset import LatchGateToolset

__all__ = [
    "ActionDescriptor",
    "LatchGateToolset",
    "discover_actions",
]

__version__ = "0.1.0"
