# latchgate-ai-sdk

Vercel AI SDK integration for [LatchGate](https://github.com/latchgate-ai/latchgate) — execution security kernel for AI agents.

Every tool call goes through LatchGate's enforcement pipeline: **auth => policy => WASM sandbox => verification => signed receipt**. The LLM never holds credentials and never contacts external systems directly.

## Installation

```bash
npm install latchgate-ai-sdk latchgate ai
```

Requires a running LatchGate instance:

```bash
curl -fsSL https://raw.githubusercontent.com/latchgate-ai/latchgate/main/install.sh | bash && latchgate up
```

## Quick start

```typescript
import { generateText } from "ai";
import { latchgateToolset } from "latchgate-ai-sdk";

const { tools, close } = await latchgateToolset({ gateUrl: "http://localhost:3000" });

try {
  const { text } = await generateText({
    model: yourModel,
    tools,
    maxSteps: 5,
    prompt: "Fetch https://httpbin.org/get and summarize the response",
  });
} finally {
  await close();
}
```

## API

### `latchgateToolset(options?)`

Discovers all LatchGate actions and returns a `LatchGateToolsetResult`.

```typescript
const { tools, actionIds, close } = await latchgateToolset({
  gateUrl: "http://localhost:3000",    // Required (or set LATCHGATE_URL)
  agentId: "my-agent",                 // Default: "ai-sdk"
  include: new Set(["http_fetch"]),    // Optional: only these actions
  exclude: new Set(["send_message"]),  // Optional: skip these actions
  timeout: 15000,                      // Discovery timeout in ms
  client: existingClient,              // Optional: pre-configured client
  onAudit: (record) => { ... },        // Optional: receipt callback
});

// tools: Record<string, CoreTool> — pass directly to generateText/streamText
// actionIds: string[] — discovered action IDs
// close(): Promise<void> — release transport (no-op if client was provided)

const { text } = await generateText({ model, tools, prompt: "..." });
await close();
```

### `discoverActions(gateUrl, options?)`

Low-level discovery function:

```typescript
import { discoverActions } from "latchgate-ai-sdk";

const descriptors = await discoverActions("http://localhost:3000", {
  include: new Set(["http_fetch"]),
});
```

## Output format

Tool output contains **only the action result** — enforcement metadata (receipt ID, trace ID, verification) is never returned to the model:

```typescript
// Successful execution:
{ output: { status: 200, body: "{...}" } }

// Error (not thrown — the LLM can reason about it):
{ error: "Action 'http_fetch' denied: policy_violation.", actionId: "http_fetch" }
```

## Audit metadata

Receipt metadata is logged at INFO level by default. Use `onAudit` for programmatic consumption:

```typescript
const { tools, close } = await latchgateToolset({
  gateUrl: "http://localhost:3000",
  onAudit: (record) => {
    // record.actionId, record.receiptId, record.traceId, record.verification
    auditLog.store(record);
  },
});
```

The callback is invoked after each successful execution, never on errors.

## License

Apache-2.0
