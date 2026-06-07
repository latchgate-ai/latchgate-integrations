# latchgate-pydantic-ai

Pydantic AI integration for [LatchGate](https://github.com/latchgate-ai/latchgate) — execution security kernel for AI agents.

Every tool call goes through LatchGate's enforcement pipeline: **auth => policy => WASM sandbox => verification => signed receipt**. The LLM never holds credentials and never contacts external systems directly.

## Installation

```bash
pip install latchgate-pydantic-ai
```

Requires a running LatchGate instance:

```bash
curl -fsSL https://raw.githubusercontent.com/latchgate-ai/latchgate/main/install.sh | bash && latchgate up
```

## Quick start

```python
from pydantic_ai import Agent
from latchgate_pydantic_ai import LatchGateToolset

async def main():
    async with await LatchGateToolset.create(gate_url="http://localhost:3000") as toolset:
        agent = Agent(
            "openai:gpt-4o",
            instructions="You have access to LatchGate-protected tools with full audit trail.",
            toolsets=[toolset],
        )

        result = await agent.run("Fetch https://httpbin.org/get")
        print(result.output)
```

## API

### `LatchGateToolset`

Native Pydantic AI `AbstractToolset` implementation. Discovers actions and provides them to the agent via `toolsets=[...]`.

```python
toolset = await LatchGateToolset.create(
    gate_url="http://localhost:3000",    # Required (or set LATCHGATE_URL)
    agent_id="my-agent",                 # Default: "pydantic-ai"
    include={"http_fetch", "database"},  # Optional
    exclude={"send_message"},            # Optional
    on_audit=my_audit_callback,          # Optional: receipt callback
)

agent = Agent("openai:gpt-4o", toolsets=[toolset])

# Properties:
toolset.action_ids   # list[str]
toolset.client       # LatchGateClient
```

Use as an async context manager for automatic cleanup:

```python
async with await LatchGateToolset.create(gate_url="...") as toolset:
    agent = Agent("openai:gpt-4o", toolsets=[toolset])
```

Or construct from pre-fetched descriptors:

```python
toolset = LatchGateToolset(client=client, descriptors=descriptors)
```

### `discover_actions(gate_url, **kwargs)`

Low-level discovery:

```python
from latchgate_pydantic_ai import discover_actions

descriptors = await discover_actions("http://localhost:3000", include={"http_fetch"})
```

## Error handling

LatchGate errors are returned as structured strings (not raised):

| LatchGate error | Tool returns |
|---|---|
| Policy denied | `"ERROR: Action '...' denied: {reason}..."` |
| Approval required | `"ERROR: ... requires human approval..."` (approval_id emitted via log, not to the model) |
| Budget exhausted | `"ERROR: Budget exhausted..."` |
| Unknown action | `"ERROR: Unknown LatchGate action '...'."`|
| Transport / infra | `"ERROR: LatchGate error..."` |

## Output format

Tool output is a JSON string containing **only the action result**. Enforcement metadata (receipt ID, trace ID, verification) is never returned to the model — it is emitted at INFO log level and via the optional `on_audit` callback.

```json
{"status": 200, "body": "{...}"}
```

## Why AbstractToolset?

Pydantic AI's `AbstractToolset` is the native interface for external tool collections. It provides `get_tools()` for schema discovery and `call_tool()` for execution — matching LatchGate's discovery + execute pattern perfectly. No schema-to-Pydantic model conversion needed; JSON Schemas pass through directly via `ToolDefinition.parameters_json_schema`.

## License

Apache-2.0
