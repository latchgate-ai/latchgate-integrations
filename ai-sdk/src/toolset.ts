/**
 * Vercel AI SDK toolset for LatchGate.
 *
 * Creates AI SDK `tool()` instances for every registered LatchGate action.
 * Each tool's `execute` function runs the action through the full
 * enforcement pipeline: auth => policy => WASM sandbox => verification
 * => signed receipt.
 *
 * @example
 * ```ts
 * import { latchgateToolset } from "latchgate-ai-sdk";
 * import { generateText } from "ai";
 *
 * const { tools, close } = await latchgateToolset({ gateUrl: "http://localhost:3000" });
 * try {
 *   const { text } = await generateText({ model: yourModel, tools, prompt: "..." });
 * } finally {
 *   await close();
 * }
 * ```
 */

import { tool, jsonSchema } from "ai";
import type { ToolSet } from "ai";
import type { Dispatcher } from "undici";
import {
  LatchGateClient,
  LatchGateApprovalRequired,
  LatchGateBudgetExhausted,
  LatchGateDenied,
  LatchGateError,
} from "latchgate";
import type { ActionResult } from "latchgate";

import {
  discoverActions,
  type ActionDescriptor,
  type DiscoverOptions,
} from "./discovery.js";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/** Audit metadata from a single LatchGate action execution. */
export interface AuditRecord {
  actionId: string;
  receiptId?: string;
  traceId?: string;
  verification?: unknown;
}

/** Callback invoked with receipt metadata after each successful execution. */
export type AuditCallback = (record: AuditRecord) => void;

export interface LatchGateToolsetOptions extends DiscoverOptions {
  /** Base URL of the LatchGate instance. Falls back to LATCHGATE_URL env var. */
  gateUrl?: string;
  /** Agent identifier for lease requests. Default: "ai-sdk". */
  agentId?: string;
  /** Pre-configured LatchGateClient. When provided, gateUrl is used only for discovery. */
  client?: LatchGateClient;
  /** Callback invoked with audit metadata after each successful action execution. */
  onAudit?: AuditCallback;
}

/** Result shape returned by every LatchGate tool execution. */
export interface LatchGateToolResult {
  output: unknown;
}

/** Error shape returned when a LatchGate tool execution fails. */
export interface LatchGateToolError {
  error: string;
  actionId: string;
}

/** Object returned by latchgateToolset(). */
export interface LatchGateToolsetResult {
  /**
   * Tools record ready for `generateText` / `streamText`.
   *
   * Type is `ToolSet` — the native AI SDK record type accepted by all
   * generation functions — so the result can be spread directly:
   *
   * ```ts
   * const { tools } = await latchgateToolset();
   * await generateText({ model, tools, prompt });
   * ```
   */
  tools: ToolSet;
  /** Action IDs of all discovered tools. */
  actionIds: string[];
  /**
   * Close the underlying LatchGate client transport.
   * Call this when the toolset is no longer needed to release connections.
   * No-op if the client was provided externally via options.client.
   */
  close: () => Promise<void>;
}

const PUBLIC_BASE_URL_DEFAULT = "http://localhost:3000";

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

/**
 * Discover LatchGate actions and return them as AI SDK tools.
 *
 * The returned object contains a `tools` record (passable directly to
 * `generateText` or `streamText`) and a `close()` method for releasing
 * the underlying transport when done.
 *
 * @param options - Toolset configuration.
 * @returns LatchGateToolsetResult with tools, actionIds, and close().
 */
export async function latchgateToolset(
  options: LatchGateToolsetOptions = {},
): Promise<LatchGateToolsetResult> {
  // UDS fallback: when no explicit URL or client, create a UDS client first
  // so discovery can reuse its transport.
  let resolvedClient = options.client;
  if (!options.gateUrl && !process.env["LATCHGATE_URL"] && !resolvedClient) {
    resolvedClient = new LatchGateClient({
      publicBaseUrl: PUBLIC_BASE_URL_DEFAULT,
      agentId: options.agentId ?? "ai-sdk",
    });
  }

  const { url: effectiveUrl, dispatcher } = resolveDiscoveryParams(
    options.gateUrl,
    resolvedClient,
  );

  const clientProvided = options.client != null;
  const client =
    resolvedClient ??
    new LatchGateClient({
      baseUrl: effectiveUrl,
      agentId: options.agentId ?? "ai-sdk",
    });

  const descriptors = await discoverActions(effectiveUrl, {
    timeout: options.timeout,
    include: options.include,
    exclude: options.exclude,
    dispatcher,
  });

  const tools: ToolSet = {};
  const actionIds: string[] = [];

  for (const descriptor of descriptors) {
    tools[descriptor.actionId] = createTool(
      descriptor,
      client,
      options.onAudit,
    );
    actionIds.push(descriptor.actionId);
  }

  return {
    tools,
    actionIds,
    close: async () => {
      // Only close the client if we created it. Externally provided
      // clients have their own lifecycle managed by the caller.
      if (!clientProvided && typeof client.close === "function") {
        await client.close();
      }
    },
  };
}

// ---------------------------------------------------------------------------
// Tool factory
// ---------------------------------------------------------------------------

function createTool(
  descriptor: ActionDescriptor,
  client: LatchGateClient,
  onAudit?: AuditCallback,
) {
  return tool({
    description: descriptor.description,
    inputSchema: jsonSchema<Record<string, unknown>>(
      descriptor.requestSchema as Parameters<typeof jsonSchema>[0],
    ),
    execute: async (
      args: Record<string, unknown>,
    ): Promise<LatchGateToolResult | LatchGateToolError> => {
      try {
        const result: ActionResult = await client.execute(
          descriptor.actionId,
          args,
        );
        // Receipt and trace metadata are not returned to the model —
        // a compromised model could use them to forge downstream evidence
        // or craft targeted social-engineering prompts for the operator.
        if (result.receiptId || result.traceId) {
          console.info(
            `[latchgate] action=${descriptor.actionId} receipt_id=${result.receiptId} trace_id=${result.traceId}`,
          );
        }

        if (onAudit) {
          onAudit({
            actionId: descriptor.actionId,
            receiptId: result.receiptId,
            traceId: result.traceId,
            verification: result.verification,
          });
        }

        return { output: result.output };
      } catch (err) {
        return mapError(descriptor.actionId, err);
      }
    },
  });
}

function mapError(actionId: string, err: unknown): LatchGateToolError {
  if (err instanceof LatchGateApprovalRequired) {
    console.info(
      `[latchgate] approval required: action=${actionId} approval_id=${err.approvalId}`,
    );
    return {
      error: `Action '${actionId}' requires human approval. The orchestrator has been notified.`,
      actionId,
    };
  }
  if (err instanceof LatchGateBudgetExhausted) {
    return {
      error: `Budget exhausted for action '${actionId}'. Obtain a new lease.`,
      actionId,
    };
  }
  if (err instanceof LatchGateDenied) {
    return {
      error: `Action '${actionId}' denied: ${err.reason ?? "policy_violation"}.`,
      actionId,
    };
  }
  if (err instanceof LatchGateError) {
    return {
      error: `LatchGate error on action '${actionId}': ${err.message}`,
      actionId,
    };
  }
  return {
    error: `Unexpected error on action '${actionId}': ${String(err)}`,
    actionId,
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface DiscoveryParams {
  url: string;
  dispatcher?: Dispatcher;
}

function resolveDiscoveryParams(
  gateUrl: string | undefined,
  client: LatchGateClient | undefined,
): DiscoveryParams {
  if (gateUrl) return { url: gateUrl };

  const envUrl = process.env["LATCHGATE_URL"];
  if (envUrl) return { url: envUrl };

  // Use the client's own transport for discovery (supports UDS).
  if (client) {
    const url = client.gateUrl;
    if (!url) {
      throw new Error(
        "gateUrl is required. The provided client has no gateUrl. " +
          "Provide gateUrl explicitly or set LATCHGATE_URL.",
      );
    }
    return { url, dispatcher: client.httpDispatcher };
  }

  // No resolution path found.
  throw new Error(
    "gateUrl is required. Provide it explicitly, pass a client, " +
      "or set LATCHGATE_URL.",
  );
}
