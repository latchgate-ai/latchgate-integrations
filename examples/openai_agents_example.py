"""OpenAI Agents SDK + LatchGate: discover tools and execute an action.

Usage:
    cd openai-agents && uv run python ../examples/openai_agents_example.py
"""

from __future__ import annotations

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")


async def main() -> None:
    from latchgate_openai_agents import latchgate_tools

    # No gate_url needed — defaults to UDS (latchgate up)

    tools = await latchgate_tools()
    print(f"Discovered {len(tools)} tools: {[t.name for t in tools]}")

    # Direct invocation (no LLM needed to verify the plumbing).
    http_fetch = next(t for t in tools if t.name == "http_fetch")
    result = await http_fetch.on_invoke_tool(None, '{"url": "https://httpbin.org/get"}')  # type: ignore[arg-type]
    print(f"Result: {result[:200]}...")

    # With an LLM agent (requires OPENAI_API_KEY):
    # from agents import Agent, Runner
    #
    # agent = Agent(
    #     name="Fetcher",
    #     instructions="You fetch URLs through LatchGate.",
    #     tools=tools,
    # )
    # result = await Runner.run(agent, "Fetch https://httpbin.org/get")
    # print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
