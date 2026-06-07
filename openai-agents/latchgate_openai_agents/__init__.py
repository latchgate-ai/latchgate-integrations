"""OpenAI Agents SDK integration for LatchGate — execution security kernel for AI agents.

Quick start::

    from latchgate_openai_agents import latchgate_tools
    from agents import Agent, Runner

    tools = await latchgate_tools(gate_url="http://localhost:3000")
    agent = Agent(name="Worker", tools=tools)
    result = await Runner.run(agent, "Fetch https://httpbin.org/get")
"""

from latchgate_common.discovery import ActionDescriptor, discover_actions

from latchgate_openai_agents._factory import latchgate_tools, latchgate_tools_from_descriptors
from latchgate_openai_agents._tool import create_tool

__all__ = [
    "ActionDescriptor",
    "create_tool",
    "discover_actions",
    "latchgate_tools",
    "latchgate_tools_from_descriptors",
]

__version__ = "0.1.0"
