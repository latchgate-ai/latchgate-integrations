# latchgate-openai-agents

OpenAI Agents SDK integration for [LatchGate](https://github.com/latchgate-ai/latchgate) — execution security kernel for AI agents.

Every tool call goes through LatchGate's enforcement pipeline: **auth => policy => WASM sandbox => verification => signed receipt**. The LLM never holds credentials and never contacts external systems directly.

## Installation

```bash
pip install latchgate-openai-agents
```

Requires a running LatchGate instance:

```bash
curl -fsSL https://raw.githubusercontent.com/latchgate-ai/latchgate/main/install.sh | bash && latchgate up
```

## Quick start

```python
from agents import Agent, Runner
from latchgate_openai_agents import latchgate_tools

async def main():
    tools = await latchgate_tools(gate_url="http://localhost:3000")

    agent = Agent(
        name="Secure Worker",
        instructions="You have access to LatchGate-protected tools with full audit trail.",
        tools=tools,
    )

    result = await Runner.run(agent, "Fetch https://httpbin.org/get")
    print(result.final_output)
```

## API

### `latchgate_tools(**kwargs)`

Async factory — discovers actions and returns `FunctionTool` instances:

```python
tools = await latchgate_tools(
    gate_url="http://localhost:3000",    # Required (or set LATCHGATE_URL)
    agent_id="my-agent",                 # Default: "openai-agents"
    include={"http_fetch", "database"},  # Optional
    exclude={"send_message"},            # Optional
    on_audit=my_audit_callback,          # Optional: receipt callback
)

agent = Agent(name="Worker", tools=tools)
```

### `latchgate_tools_from_descriptors(descriptors, *, client)`

Create tools from pre-fetched descriptors (no network):

```python
from latchgate_openai_agents import latchgate_tools_from_descriptors, ActionDescriptor
```

### `create_tool(descriptor, client)`

Create a single `FunctionTool` from an `ActionDescriptor`:

```python
from latchgate_openai_agents import create_tool
```

## Error handling

LatchGate errors are returned as structured strings (not raised):

| LatchGate error | Tool returns |
|---|---|
| Policy denied | `"ERROR: Action '...' denied: {reason}..."` |
| Approval required | `"ERROR: ... requires human approval..."` (approval_id emitted via log, not to the model) |
| Budget exhausted | `"ERROR: Budget exhausted..."` |
| Invalid JSON input | `"ERROR: Invalid JSON input..."` |
| Transport / infra | `"ERROR: LatchGate error..."` |

## Output format

Tool output is a JSON string containing **only the action result**. Enforcement metadata (receipt ID, trace ID, verification) is never returned to the model — it is emitted at INFO log level and via the optional `on_audit` callback.

```json
{"status": 200, "body": "{...}"}
```

## License

Apache-2.0
