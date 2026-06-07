"""Pydantic AI + LatchGate: discover tools and execute an action.

Usage:
    cd pydantic && uv run python ../examples/pydantic_ai_example.py
"""

from __future__ import annotations

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")


async def main() -> None:
    from pydantic_ai.messages import ToolCallPart

    from latchgate_pydantic_ai import LatchGateToolset

    # No gate_url needed — defaults to UDS (latchgate up)

    async with await LatchGateToolset.create() as toolset:
        tool_defs = await toolset.get_tools()
        print(f"Discovered {len(tool_defs)} tools: {toolset.action_ids}")

        # Direct invocation (no LLM needed to verify the plumbing).
        call = ToolCallPart(
            tool_name="http_fetch",
            args={"url": "https://httpbin.org/get"},
            tool_call_id="test-001",
        )
        result = await toolset.call_tool(call)
        print(f"Result: {result[:200]}...")

        # With an LLM agent (requires OPENAI_API_KEY):
        # from pydantic_ai import Agent
        #
        # agent = Agent("openai:gpt-4o-mini", toolsets=[toolset])
        # result = agent.run_sync("Fetch https://httpbin.org/get")
        # print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
