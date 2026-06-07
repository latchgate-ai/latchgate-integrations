/**
 * @latchgate/ai-sdk — Vercel AI SDK integration for LatchGate.
 *
 * @example
 * ```ts
 * import { latchgateToolset } from "@latchgate/ai-sdk";
 * import { generateText } from "ai";
 *
 * const { tools, close } = await latchgateToolset({ gateUrl: "http://localhost:3000" });
 * try {
 *   const { text } = await generateText({ model, tools, prompt: "..." });
 * } finally {
 *   await close();
 * }
 * ```
 */

export { latchgateToolset } from "./toolset.js";
export type {
  AuditCallback,
  AuditRecord,
  LatchGateToolsetOptions,
  LatchGateToolsetResult,
  LatchGateToolResult,
  LatchGateToolError,
} from "./toolset.js";

export { discoverActions } from "./discovery.js";
export type { ActionDescriptor, DiscoverOptions } from "./discovery.js";
