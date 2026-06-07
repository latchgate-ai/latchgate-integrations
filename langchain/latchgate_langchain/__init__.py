"""LangChain integration for LatchGate — execution security kernel for AI agents.

Quick start::

    from latchgate_langchain import LatchGateToolset

    toolset = await LatchGateToolset.create(gate_url="http://localhost:3000")
    tools = toolset.get_tools()

Every tool call goes through LatchGate's enforcement pipeline:
auth => policy => WASM sandbox => verification => signed receipt.
"""

from latchgate_common.discovery import ActionDescriptor, discover_actions

from latchgate_langchain._tool import LatchGateTool
from latchgate_langchain._toolset import LatchGateToolset

__all__ = [
    "ActionDescriptor",
    "LatchGateTool",
    "LatchGateToolset",
    "discover_actions",
]

__version__ = "0.1.0"
