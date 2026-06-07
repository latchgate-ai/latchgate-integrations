/**
 * Vercel AI SDK + LatchGate: discover tools and execute an action.
 *
 * Usage:
 *   cd ai-sdk && npx tsx ../examples/ai_sdk_example.ts
 */

import { latchgateToolset } from "latchgate-ai-sdk";

async function main(): Promise<void> {
  // No gateUrl needed — defaults to UDS (latchgate up)

  const { tools, actionIds, close } = await latchgateToolset({});
  console.log(`Discovered ${actionIds.length} tools: ${actionIds.join(", ")}`);

  try {
    // Direct invocation (no LLM needed to verify the plumbing).
    const httpFetch = tools["http_fetch"];
    if (httpFetch) {
      const result = await (httpFetch as any).execute({
        url: "https://httpbin.org/get",
      });
      console.log("Result:", JSON.stringify(result).slice(0, 200), "...");
    }

    // With an LLM (requires OPENAI_API_KEY):
    // import { generateText } from "ai";
    // import { openai } from "@ai-sdk/openai";
    //
    // const { text } = await generateText({
    //   model: openai("gpt-4o-mini"),
    //   tools,
    //   prompt: "Fetch https://httpbin.org/get",
    // });
    // console.log(text);
  } finally {
    await close();
  }
}

main().catch(console.error);
