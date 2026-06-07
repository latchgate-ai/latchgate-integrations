"""CrewAI + LatchGate: discover tools and execute an action.

Usage:
    cd crewai && uv run python ../examples/crewai_example.py
"""

from __future__ import annotations

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")


async def main() -> None:
    from latchgate_crewai import LatchGateToolset

    # No gate_url needed — defaults to UDS (latchgate up)

    toolset = await LatchGateToolset.create()
    tools = toolset.all()
    print(f"Discovered {len(tools)} tools: {toolset.action_ids}")

    # Direct invocation (no LLM needed to verify the plumbing).
    http_fetch = toolset.get("http_fetch")
    result = await http_fetch._arun(url="https://httpbin.org/get")
    print(f"Result: {result[:200]}...")

    # Sync path also works:
    # toolset_sync = LatchGateToolset.create_sync()
    # tool = toolset_sync.get("http_fetch")
    # result = tool._run(url="https://httpbin.org/get")

    # With an LLM agent (requires OPENAI_API_KEY):
    # from crewai import Agent, Task, Crew
    #
    # agent = Agent(
    #     role="Fetcher",
    #     goal="Fetch URLs through LatchGate",
    #     tools=tools,
    # )
    # task = Task(
    #     description="Fetch https://httpbin.org/get and summarize the response.",
    #     agent=agent,
    #     expected_output="A summary of the HTTP response.",
    # )
    # crew = Crew(agents=[agent], tasks=[task])
    # result = crew.kickoff()
    # print(result)

    await toolset.close()


if __name__ == "__main__":
    asyncio.run(main())
