# latchgate-langchain

LangChain integration for [LatchGate](https://github.com/latchgate-ai/latchgate) — execution security kernel for AI agents.

Every tool call goes through LatchGate's enforcement pipeline: **auth => policy => WASM sandbox => verification => signed receipt**. The LLM never holds credentials and never contacts external systems directly.

## Installation

```bash
pip install latchgate-langchain
```

Requires a running LatchGate instance:

```bash
curl -fsSL https://raw.githubusercontent.com/latchgate-ai/latchgate/main/install.sh | bash && latchgate up
```

## Quick start

```python
import asyncio
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from latchgate_langchain import LatchGateToolset

async def main():
    # Discover all LatchGate actions as LangChain tools.
    async with await LatchGateToolset.create(
        gate_url="http://localhost:3000",
        agent_id="my-langchain-agent",
    ) as toolset:
        tools = toolset.get_tools()

        llm = ChatOpenAI(model="gpt-4o")
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a helpful assistant with access to gated tools."),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ])
        agent = create_tool_calling_agent(llm, tools, prompt)
        executor = AgentExecutor(agent=agent, tools=tools)

        result = await executor.ainvoke({"input": "Fetch https://httpbin.org/get"})
        print(result["output"])

asyncio.run(main())
```

## API

### `LatchGateToolset`

Main entry point. Discovers actions and wraps them as LangChain tools.

```python
toolset = await LatchGateToolset.create(
    gate_url="http://localhost:3000",  # Required (or set LATCHGATE_URL)
    agent_id="my-agent",               # Default: "langchain"
    include={"http_fetch", "database"}, # Optional: only these actions
    exclude={"send_message"},           # Optional: skip these actions
    on_audit=my_audit_callback,         # Optional: receipt callback
)

tools = toolset.get_tools()       # list[BaseTool]
ids = toolset.action_ids          # list[str]
client = toolset.client           # LatchGateClient (for direct access)
await toolset.close()             # Clean up transport
```

Use as an async context manager for automatic cleanup:

```python
async with await LatchGateToolset.create(gate_url="...") as toolset:
    tools = toolset.get_tools()
```

Or create from pre-fetched descriptors (synchronous, no I/O):

```python
toolset = LatchGateToolset.from_descriptors(descriptors, client=client)
```

### `LatchGateTool`

Individual tool wrapping a single action. Created automatically by the toolset, but can be used directly:

```python
from latchgate import LatchGateClient
from latchgate_langchain import LatchGateTool, ActionDescriptor

client = LatchGateClient(base_url="http://localhost:3000", agent_id="my-agent")

descriptor = ActionDescriptor(
    action_id="http_fetch",
    version="1.0.0",
    risk_level="low",
    request_schema={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    description="Fetch a URL through LatchGate",
)

tool = LatchGateTool.from_descriptor(descriptor, client)
result = await tool.ainvoke({"url": "https://httpbin.org/get"})
```

### `discover_actions`

Low-level discovery function for advanced control:

```python
from latchgate_langchain import discover_actions

descriptors = await discover_actions(
    "http://localhost:3000",
    include={"http_fetch"},
    timeout=10.0,
)
```

## Error handling

LatchGate errors are surfaced as `ToolException` with structured messages the LLM can reason about:

| LatchGate error | Tool behavior |
|---|---|
| Policy denied | `ToolException` — "denied: {reason}" |
| Approval required | `ToolException` — "requires human approval" (approval_id emitted via callback, not to the model) |
| Budget exhausted | `ToolException` — "obtain a new lease" |
| Transport / infra | `ToolException` — retryable failure |

All tools have `handle_tool_error=True` so errors are returned to the LLM as text rather than crashing the agent.

## Output format

Tool output is a JSON string containing **only the action result**. Enforcement metadata (receipt ID, trace ID, verification) is never returned to the model — it is emitted at INFO log level and via the optional `on_audit` callback.

```json
{"status": 200, "body": "{...}"}
```

## License

Apache-2.0
