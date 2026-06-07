/**
 * Action discovery from the LatchGate REST API.
 *
 * Fetches the action registry and request schemas via unauthenticated
 * endpoints. These endpoints expose only structural metadata — never
 * credentials or secrets.
 *
 * @internal
 */

import type { Dispatcher } from "undici";

/** Metadata for a single discovered LatchGate action. */
export interface ActionDescriptor {
  actionId: string;
  version: string;
  riskLevel: string;
  requestSchema: Record<string, unknown>;
  description: string;
  declaredSideEffects: string[];
}

export interface DiscoverOptions {
  /** HTTP timeout in milliseconds. Default: 15000. */
  timeout?: number;
  /** If provided, only return actions whose actionId is in this set. */
  include?: Set<string>;
  /** If provided, skip actions whose actionId is in this set. */
  exclude?: Set<string>;
  /**
   * When false (default), actions without a request schema are skipped.
   * Production LatchGate always serves schemas; a missing schema
   * indicates a degraded gate.
   */
  allowSchemaless?: boolean;
  /**
   * Controls how much enforcement metadata appears in model-visible
   * tool descriptions. `"none"` (default) omits egress profiles,
   * allowed domains, database modes, and statement IDs. `"debug"`
   * includes all available detail. Use `"debug"` only in trusted
   * development environments.
   */
  securityDetail?: "none" | "debug";
  /**
   * Optional undici Dispatcher for custom transport (e.g. UDS).
   * When provided, discovery uses this dispatcher instead of global fetch.
   * @internal Used by framework integrations to reuse client transport.
   */
  dispatcher?: Dispatcher;
}

/**
 * Discover all registered actions from a LatchGate instance.
 *
 * @param gateUrl - Base URL of the running gate (e.g. "http://localhost:3000").
 * @param options - Discovery options.
 * @returns Array of ActionDescriptor for each discovered action.
 */
export async function discoverActions(
  gateUrl: string,
  options: DiscoverOptions = {},
): Promise<ActionDescriptor[]> {
  const base = gateUrl.replace(/\/$/, "");
  const timeout = options.timeout ?? 15_000;
  const dispatcher = options.dispatcher;
  const allowSchemaless = options.allowSchemaless ?? false;
  const securityDetail = options.securityDetail ?? "none";

  const actionsResp = await fetchJson(
    `${base}/v1/actions`,
    timeout,
    dispatcher,
  );
  const rawActions: Array<Record<string, unknown>> = (
    actionsResp as Record<string, unknown>
  )["actions"] as Array<Record<string, unknown>>;

  if (!rawActions || rawActions.length === 0) {
    return [];
  }

  const filtered = filterActions(rawActions, options.include, options.exclude);
  const descriptors: ActionDescriptor[] = [];

  for (const action of filtered) {
    const actionId = action["action_id"] as string;

    if (!isSafeIdentifier(actionId)) {
      console.warn(
        `[latchgate] skipping action with unsafe identifier: '${String(actionId).slice(0, 64)}' — ` +
          `action_id must be alphanumeric with hyphens, underscores, or dots (max 256 chars)`,
      );
      continue;
    }

    const version = (action["version"] as string) ?? "0.0.0";
    const riskLevel = (action["risk_level"] as string) ?? "unknown";

    let schema = await fetchSchema(base, actionId, timeout, dispatcher);

    if (schema === null) {
      if (allowSchemaless) {
        console.warn(
          `[latchgate] no schema for action '${actionId}' — wrapping with permissive schema (allowSchemaless=true)`,
        );
        schema = { type: "object", additionalProperties: true };
      } else {
        console.warn(
          `[latchgate] skipping action '${actionId}': gate did not return a request schema. ` +
            `Pass allowSchemaless: true to wrap anyway (not recommended for production).`,
        );
        continue;
      }
    }

    const detail = await fetchDetail(base, actionId, timeout, dispatcher);

    const sideEffects = detail
      ? ((detail["declared_side_effects"] as string[]) ?? [])
      : [];
    const description = buildDescription(
      actionId,
      version,
      riskLevel,
      detail,
      securityDetail,
    );

    descriptors.push({
      actionId,
      version,
      riskLevel,
      requestSchema: schema,
      description,
      declaredSideEffects: sideEffects,
    });
  }

  return descriptors;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function filterActions(
  actions: Array<Record<string, unknown>>,
  include?: Set<string>,
  exclude?: Set<string>,
): Array<Record<string, unknown>> {
  let result = actions;
  if (include) {
    result = result.filter((a) => include.has(a["action_id"] as string));
  }
  if (exclude) {
    result = result.filter((a) => !exclude.has(a["action_id"] as string));
  }
  return result;
}

/**
 * Identifier format: alphanumeric start, then alphanumeric/hyphens/underscores/dots.
 * No path separators, query strings, or URL-special characters.
 */
const SAFE_IDENTIFIER_RE = /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/;

/**
 * Check whether a string is safe for URL path interpolation.
 *
 * Validates action_ids received from the gate before embedding them in
 * URLs for schema and detail fetches. The gate is a trusted source, but
 * a compromised or buggy gate could return a crafted action_id that
 * alters the request path.
 */
function isSafeIdentifier(value: string): boolean {
  return !!value && value.length <= 256 && SAFE_IDENTIFIER_RE.test(value);
}

async function fetchSchema(
  base: string,
  actionId: string,
  timeout: number,
  dispatcher?: Dispatcher,
): Promise<Record<string, unknown> | null> {
  try {
    const resp = await fetchJson(
      `${base}/v1/actions/${actionId}/schema/request`,
      timeout,
      dispatcher,
    );
    return resp as Record<string, unknown>;
  } catch {
    return null;
  }
}

async function fetchDetail(
  base: string,
  actionId: string,
  timeout: number,
  dispatcher?: Dispatcher,
): Promise<Record<string, unknown> | null> {
  try {
    return (await fetchJson(
      `${base}/v1/actions/${actionId}`,
      timeout,
      dispatcher,
    )) as Record<string, unknown>;
  } catch {
    return null;
  }
}

async function fetchJson(
  url: string,
  timeout: number,
  dispatcher?: Dispatcher,
): Promise<unknown> {
  const init: Record<string, unknown> = {
    signal: AbortSignal.timeout(timeout),
    headers: { Accept: "application/json" },
  };

  let resp: Response;
  if (dispatcher) {
    // Dynamic import — undici is a transitive dependency via latchgate SDK.
    // Only loaded when a custom dispatcher is provided (UDS path).
    const { fetch: uFetch } = await import("undici");
    resp = await (
      uFetch as unknown as (
        url: string,
        init: Record<string, unknown>,
      ) => Promise<Response>
    )(url, { ...init, dispatcher });
  } else {
    resp = await fetch(url, init as RequestInit);
  }

  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status} from ${url}`);
  }
  return resp.json();
}

function buildDescription(
  actionId: string,
  version: string,
  riskLevel: string,
  detail: Record<string, unknown> | null,
  securityDetail: "none" | "debug" = "none",
): string {
  const parts: string[] = [
    `LatchGate protected action: ${actionId} (v${version}, risk=${riskLevel}).`,
  ];

  if (detail) {
    const sideEffects = detail["declared_side_effects"] as string[] | undefined;
    if (sideEffects?.length) {
      parts.push(`Side effects: ${sideEffects.join(", ")}.`);
    }

    if (securityDetail === "debug") {
      const egress = detail["egress"] as Record<string, unknown> | null;
      if (egress && typeof egress === "object") {
        const profile = egress["profile"] as string;
        const domains = egress["allowed_domains"] as string[];
        if (profile) parts.push(`Egress profile: ${profile}.`);
        if (domains?.length) {
          parts.push(`Allowed domains: ${domains.join(", ")}.`);
        }
      }

      const db = detail["database"] as Record<string, unknown> | null;
      if (db && typeof db === "object") {
        const mode = db["mode"] as string;
        parts.push(`Database mode: ${mode}.`);
        const stmts = db["statements"] as Array<Record<string, unknown>>;
        if (stmts?.length) {
          const ids = stmts.map((s) => (s["id"] as string) ?? "?");
          parts.push(`Available statements: ${ids.join(", ")}.`);
        }
        if (db["allows_parameterized_queries"]) {
          const ops = (db["parameterized_operations"] as string[]) ?? [];
          parts.push(`Parameterized queries allowed for: ${ops.join(", ")}.`);
        }
      }
    }
  }

  parts.push(
    "All calls are authenticated, policy-evaluated, sandboxed, " +
      "and produce signed audit receipts.",
  );
  return parts.join(" ");
}
