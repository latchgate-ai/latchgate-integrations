"""LangChain + LatchGate: discover tools and execute an action.

Usage:
    cd langchain && uv run python ../examples/langchain_example.py
"""

from __future__ import annotations

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")


async def main() -> None:
    from latchgate_langchain import LatchGateToolset

    # No gate_url needed — defaults to UDS (latchgate up)

    async with await LatchGateToolset.create() as toolset:
        tools = toolset.get_tools()
        print(f"Discovered {len(tools)} tools: {toolset.action_ids}")

        # Direct invocation (no LLM needed to verify the plumbing).
        http_fetch = next(t for t in tools if t.name == "http_fetch")
        result = await http_fetch.ainvoke({"url": "https://httpbin.org/get"})
        print(f"Result: {result[:200]}...")

        # With an LLM agent (requires OPENAI_API_KEY):
        # from langchain_openai import ChatOpenAI
        # from langchain.agents import AgentExecutor, create_tool_calling_agent
        # from langchain_core.prompts import ChatPromptTemplate
        #
        # llm = ChatOpenAI(model="gpt-4o-mini")
        # prompt = ChatPromptTemplate.from_messages([
        #     ("system", "You are a helpful assistant with access to LatchGate tools."),
        #     ("human", "{input}"),
        #     ("placeholder", "{agent_scratchpad}"),
        # ])
        # agent = create_tool_calling_agent(llm, tools, prompt)
        # executor = AgentExecutor(agent=agent, tools=tools)
        # response = await executor.ainvoke({"input": "Fetch https://httpbin.org/get"})
        # print(response["output"])


if __name__ == "__main__":
    asyncio.run(main())
