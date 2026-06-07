# LatchGate Integration Examples

Minimal runnable scripts showing each framework integration end-to-end.

## Prerequisites

1. A running LatchGate instance with the built-in `http_fetch` action:

   ```bash
   # From the main latchgate repo:
   cargo run -- gate --config examples/config.toml
   ```

   By default this listens on `http://localhost:3000`.

2. Install the integration package you want to test:

   ```bash
   cd langchain && uv sync && cd ..
   # or: cd crewai && uv sync && cd ..
   # or: cd openai-agents && uv sync && cd ..
   # or: cd pydantic && uv sync && cd ..
   # or: cd ai-sdk && npm ci && cd ..
   ```

3. Set your LLM API key (examples use OpenAI):

   ```bash
   export OPENAI_API_KEY="sk-..."
   ```

## Run

```bash
# Python examples (from repo root):
cd langchain  && uv run python ../examples/langchain_example.py
cd crewai     && uv run python ../examples/crewai_example.py
cd openai-agents && uv run python ../examples/openai_agents_example.py
cd pydantic   && uv run python ../examples/pydantic_ai_example.py

# TypeScript example:
cd ai-sdk && npx tsx ../examples/ai_sdk_example.ts
```

Each script discovers actions from the gate, wraps them as
framework-native tools, and executes a single `http_fetch` call.
The output includes the HTTP response from the fetched URL and
confirms that receipt metadata is logged (not returned to the model).

## What to look for

- **Tool discovery** — the script prints discovered action IDs.
- **Execution** — the agent calls `http_fetch` through LatchGate.
- **Audit trail** — receipt ID and trace ID appear in log output
  at INFO level, never in the model-visible result.
