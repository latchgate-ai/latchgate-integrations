"""CrewAI integration for LatchGate — execution security kernel for AI agents.

Quick start::

    from latchgate_crewai import LatchGateToolset

    # Sync:
    toolset = LatchGateToolset.create_sync(gate_url="http://localhost:3000")
    tools = toolset.all()

    # Async:
    toolset = await LatchGateToolset.create(gate_url="http://localhost:3000")
    tools = toolset.all()

Every tool call goes through LatchGate's enforcement pipeline:
auth => policy => WASM sandbox => verification => signed receipt.
"""

from latchgate_common.discovery import ActionDescriptor, discover_actions

from latchgate_crewai._tool import LatchGateTool
from latchgate_crewai._toolset import LatchGateToolset

__all__ = [
    "ActionDescriptor",
    "LatchGateTool",
    "LatchGateToolset",
    "discover_actions",
]

__version__ = "0.1.0"
