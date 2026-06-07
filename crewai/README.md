# latchgate-crewai

CrewAI integration for [LatchGate](https://github.com/latchgate-ai/latchgate) — execution security kernel for AI agents.

Every tool call goes through LatchGate's enforcement pipeline: **auth => policy => WASM sandbox => verification => signed receipt**. The LLM never holds credentials and never contacts external systems directly.

## Installation

```bash
pip install latchgate-crewai
```

Requires a running LatchGate instance:

```bash
curl -fsSL https://raw.githubusercontent.com/latchgate-ai/latchgate/main/install.sh | bash && latchgate up
```

## Quick start

```python
from crewai import Agent, Task, Crew
from latchgate_crewai import LatchGateToolset

# Sync factory (preferred for CrewAI's synchronous kickoff):
toolset = LatchGateToolset.create_sync(gate_url="http://localhost:3000")
tools = toolset.all()

agent = Agent(
    role="Secure Worker",
    goal="Perform tasks through gated tools with full audit trail",
    backstory="You are an agent with access to LatchGate-protected actions.",
    tools=tools,
)

task = Task(
    description="Fetch https://httpbin.org/get and report the response",
    expected_output="The HTTP response body",
    agent=agent,
)

crew = Crew(agents=[agent], tasks=[task])
result = crew.kickoff()
print(result)
```

## API

### `LatchGateToolset`

Main entry point. Discovers actions and wraps them as CrewAI tools.

```python
# Sync factory (works everywhere, including inside running event loops):
toolset = LatchGateToolset.create_sync(
    gate_url="http://localhost:3000",  # Required (or set LATCHGATE_URL)
    agent_id="my-agent",               # Default: "crewai"
    include={"http_fetch", "database"}, # Optional: only these actions
    exclude={"send_message"},           # Optional: skip these actions
    on_audit=my_audit_callback,         # Optional: receipt callback
)

# Async factory:
toolset = await LatchGateToolset.create(gate_url="http://localhost:3000")

tools = toolset.all()              # list[BaseTool]
tool = toolset.get("http_fetch")   # single tool by action_id
ids = toolset.action_ids           # list[str]
client = toolset.client            # LatchGateClient (for direct access)
```

Use as an async context manager for automatic cleanup:

```python
async with await LatchGateToolset.create(gate_url="...") as toolset:
    tools = toolset.all()
```

Or create from pre-fetched descriptors (synchronous, no I/O):

```python
toolset = LatchGateToolset.from_descriptors(descriptors, client=client)
```

### `LatchGateTool`

Individual tool wrapping a single action. Created automatically by `LatchGateToolset`, but can be used directly:

```python
from latchgate import LatchGateClient
from latchgate_crewai import LatchGateTool, ActionDescriptor

client = LatchGateClient(base_url="http://localhost:3000", agent_id="my-agent")

descriptor = ActionDescriptor(
    action_id="http_fetch",
    version="1.0.0",
    risk_level="low",
    request_schema={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    description="Fetch a URL through LatchGate",
)

tool = LatchGateTool.from_descriptor(descriptor, client)
```

### `discover_actions`

Low-level discovery function:

```python
from latchgate_crewai import discover_actions

descriptors = await discover_actions("http://localhost:3000", include={"http_fetch"})
```

## Error handling

LatchGate errors are returned as structured error strings (not exceptions) so the CrewAI agent can reason about them:

| LatchGate error | Tool returns |
|---|---|
| Policy denied | `"ERROR: Action '...' denied: {reason}..."` |
| Approval required | `"ERROR: ... requires human approval..."` (approval_id emitted via log, not to the model) |
| Budget exhausted | `"ERROR: Budget exhausted..."` |
| Transport / infra | `"ERROR: LatchGate error..."` |

## Output format

Tool output is a JSON string containing **only the action result**. Enforcement metadata (receipt ID, trace ID, verification) is never returned to the model — it is emitted at INFO log level and via the optional `on_audit` callback.

```json
{"status": 200, "body": "{...}"}
```

## License

Apache-2.0
