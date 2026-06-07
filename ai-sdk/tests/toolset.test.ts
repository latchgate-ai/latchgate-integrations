import { describe, it, expect, vi, afterEach } from "vitest";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SAMPLE_ACTIONS = {
  actions: [
    { action_id: "http_fetch", version: "1.0.0", risk_level: "low" },
    { action_id: "send_message", version: "1.0.0", risk_level: "high" },
  ],
};

const SAMPLE_HTTP_FETCH_SCHEMA = {
  type: "object",
  required: ["url"],
  properties: {
    url: { type: "string", description: "Target URL" },
    method: { type: "string", enum: ["GET", "HEAD"], default: "GET" },
  },
};

const SAMPLE_HTTP_FETCH_DETAIL = {
  action_id: "http_fetch",
  version: "1.0.0",
  risk_level: "low",
  declared_side_effects: ["http_read"],
  egress: { profile: "proxy_allowlist", allowed_domains: ["api.github.com"] },
};

function mockRoutes(routes: Record<string, unknown>): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input.toString();
      const path = new URL(url).pathname;
      if (path in routes) {
        return new Response(JSON.stringify(routes[path]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ error: "not_found" }), {
        status: 404,
      });
    }),
  );
}

function fullRoutes(): Record<string, unknown> {
  return {
    "/v1/actions": SAMPLE_ACTIONS,
    "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
    "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
    "/v1/actions/send_message/schema/request": { type: "object" },
    "/v1/actions/send_message": { action_id: "send_message" },
  };
}

// ---------------------------------------------------------------------------
// URL resolution
// ---------------------------------------------------------------------------

describe("URL resolution", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete process.env["LATCHGATE_URL"];
  });

  it("rejects when no gateUrl and no env var", async () => {
    delete process.env["LATCHGATE_URL"];
    const { latchgateToolset } = await import("../src/toolset.js");
    await expect(latchgateToolset()).rejects.toThrow(
      /gateUrl is required|fetch failed|ECONNREFUSED/,
    );
  }, 15_000);

  it("rejects when client has no gateUrl getter", async () => {
    const { latchgateToolset } = await import("../src/toolset.js");
    const fakeClient = {} as any;
    await expect(latchgateToolset({ client: fakeClient })).rejects.toThrow(
      "gateUrl is required",
    );
  });

  it("uses client.gateUrl when no explicit gateUrl provided", async () => {
    mockRoutes({ "/v1/actions": { actions: [] } });

    const { latchgateToolset } = await import("../src/toolset.js");
    const fakeClient = {
      gateUrl: "http://localhost:3000",
      httpDispatcher: undefined,
    } as any;
    const result = await latchgateToolset({ client: fakeClient });
    expect(result.tools).toEqual({});
    expect(result.actionIds).toEqual([]);
  });

  it("uses LATCHGATE_URL env var as fallback", async () => {
    process.env["LATCHGATE_URL"] = "http://localhost:3000";
    mockRoutes({ "/v1/actions": { actions: [] } });

    const { latchgateToolset } = await import("../src/toolset.js");
    const result = await latchgateToolset();
    expect(result.tools).toEqual({});
  });
});

// ---------------------------------------------------------------------------
// Toolset creation
// ---------------------------------------------------------------------------

describe("latchgateToolset", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete process.env["LATCHGATE_URL"];
  });

  it("returns empty tools for zero actions", async () => {
    mockRoutes({ "/v1/actions": { actions: [] } });

    const { latchgateToolset } = await import("../src/toolset.js");
    const result = await latchgateToolset({ gateUrl: "http://localhost:3000" });
    expect(result.tools).toEqual({});
    expect(result.actionIds).toEqual([]);
  });

  it("returns tools keyed by action_id", async () => {
    mockRoutes(fullRoutes());

    const { latchgateToolset } = await import("../src/toolset.js");
    const result = await latchgateToolset({
      gateUrl: "http://localhost:3000",
    });

    expect(Object.keys(result.tools).sort()).toEqual([
      "http_fetch",
      "send_message",
    ]);
    expect(result.actionIds.sort()).toEqual(["http_fetch", "send_message"]);
  });

  it("respects include filter", async () => {
    mockRoutes({
      "/v1/actions": SAMPLE_ACTIONS,
      "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
      "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
    });

    const { latchgateToolset } = await import("../src/toolset.js");
    const result = await latchgateToolset({
      gateUrl: "http://localhost:3000",
      include: new Set(["http_fetch"]),
    });

    expect(Object.keys(result.tools)).toEqual(["http_fetch"]);
  });

  it("respects exclude filter", async () => {
    mockRoutes({
      "/v1/actions": SAMPLE_ACTIONS,
      "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
      "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
    });

    const { latchgateToolset } = await import("../src/toolset.js");
    const result = await latchgateToolset({
      gateUrl: "http://localhost:3000",
      exclude: new Set(["send_message"]),
    });

    expect(Object.keys(result.tools)).toEqual(["http_fetch"]);
  });

  it("created tools have execute function", async () => {
    mockRoutes(fullRoutes());

    const { latchgateToolset } = await import("../src/toolset.js");
    const result = await latchgateToolset({
      gateUrl: "http://localhost:3000",
    });

    const httpFetch = result.tools["http_fetch"] as any;
    expect(httpFetch).toBeDefined();
    expect(typeof httpFetch.execute).toBe("function");
  });

  it("close() is callable", async () => {
    mockRoutes({ "/v1/actions": { actions: [] } });

    const { latchgateToolset } = await import("../src/toolset.js");
    const result = await latchgateToolset({
      gateUrl: "http://localhost:3000",
    });

    expect(typeof result.close).toBe("function");
    // Should not throw
    await result.close();
  });

  it("close() is no-op when client was provided externally", async () => {
    mockRoutes({ "/v1/actions": { actions: [] } });

    const { latchgateToolset } = await import("../src/toolset.js");
    const mockClient = {
      gateUrl: "http://localhost:3000",
      httpDispatcher: undefined,
      close: vi.fn().mockResolvedValue(undefined),
    } as any;

    const result = await latchgateToolset({ client: mockClient });
    await result.close();
    // close() should NOT be called on externally provided client
    expect(mockClient.close).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Error mapping
// ---------------------------------------------------------------------------

describe("mapError", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("maps LatchGateDenied to structured error", async () => {
    mockRoutes({
      "/v1/actions": {
        actions: [{ action_id: "test", version: "1.0.0", risk_level: "low" }],
      },
      "/v1/actions/test/schema/request": { type: "object", properties: {} },
      "/v1/actions/test": { action_id: "test" },
    });

    const { latchgateToolset } = await import("../src/toolset.js");
    const { LatchGateDenied } = await import("latchgate");

    const mockClient = {
      execute: vi
        .fn()
        .mockRejectedValue(new LatchGateDenied("test", "policy_violation")),
    };

    const result = await latchgateToolset({
      gateUrl: "http://localhost:3000",
      client: mockClient as any,
    });

    const toolResult = await (result.tools["test"] as any).execute({});
    expect(toolResult.error).toContain("denied");
    expect(toolResult.actionId).toBe("test");
  });

  it("maps LatchGateApprovalRequired without exposing approvalId", async () => {
    mockRoutes({
      "/v1/actions": {
        actions: [{ action_id: "test", version: "1.0.0", risk_level: "low" }],
      },
      "/v1/actions/test/schema/request": { type: "object", properties: {} },
      "/v1/actions/test": { action_id: "test" },
    });

    const { latchgateToolset } = await import("../src/toolset.js");
    const { LatchGateApprovalRequired } = await import("latchgate");

    const mockClient = {
      execute: vi
        .fn()
        .mockRejectedValue(new LatchGateApprovalRequired("test", "apr_123")),
    };

    const result = await latchgateToolset({
      gateUrl: "http://localhost:3000",
      client: mockClient as any,
    });

    const toolResult = await (result.tools["test"] as any).execute({});
    expect(toolResult.error).toContain("approval");
    expect(toolResult.error).not.toContain("apr_123");
    expect(toolResult.approvalId).toBeUndefined();
  });

  it("maps LatchGateBudgetExhausted", async () => {
    mockRoutes({
      "/v1/actions": {
        actions: [{ action_id: "test", version: "1.0.0", risk_level: "low" }],
      },
      "/v1/actions/test/schema/request": { type: "object", properties: {} },
      "/v1/actions/test": { action_id: "test" },
    });

    const { latchgateToolset } = await import("../src/toolset.js");
    const { LatchGateBudgetExhausted } = await import("latchgate");

    const mockClient = {
      execute: vi.fn().mockRejectedValue(new LatchGateBudgetExhausted("test")),
    };

    const result = await latchgateToolset({
      gateUrl: "http://localhost:3000",
      client: mockClient as any,
    });

    const toolResult = await (result.tools["test"] as any).execute({});
    expect(toolResult.error).toContain("Budget exhausted");
  });

  it("maps unexpected errors", async () => {
    mockRoutes({
      "/v1/actions": {
        actions: [{ action_id: "test", version: "1.0.0", risk_level: "low" }],
      },
      "/v1/actions/test/schema/request": { type: "object", properties: {} },
      "/v1/actions/test": { action_id: "test" },
    });

    const { latchgateToolset } = await import("../src/toolset.js");

    const mockClient = {
      execute: vi.fn().mockRejectedValue(new Error("network timeout")),
    };

    const result = await latchgateToolset({
      gateUrl: "http://localhost:3000",
      client: mockClient as any,
    });

    const toolResult = await (result.tools["test"] as any).execute({});
    expect(toolResult.error).toContain("Unexpected");
    expect(toolResult.actionId).toBe("test");
  });
});

// ---------------------------------------------------------------------------
// Tool execution
// ---------------------------------------------------------------------------

describe("tool execution", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("successful execution returns only output, no receipt metadata", async () => {
    mockRoutes({
      "/v1/actions": {
        actions: [
          { action_id: "http_fetch", version: "1.0.0", risk_level: "low" },
        ],
      },
      "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
      "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
    });

    const { latchgateToolset } = await import("../src/toolset.js");

    const mockResult = {
      output: { status: 200, body: "ok" },
      receiptId: "rcpt_01JTEST",
      traceId: "trace_01JTEST",
      verification: { outcome: "verified" },
    };

    const mockClient = {
      execute: vi.fn().mockResolvedValue(mockResult),
    };

    const { tools } = await latchgateToolset({
      gateUrl: "http://localhost:3000",
      client: mockClient as any,
    });

    const toolResult = await (tools["http_fetch"] as any).execute({
      url: "https://httpbin.org/get",
    });

    expect(toolResult.output.status).toBe(200);
    expect(toolResult.output.body).toBe("ok");
    // Enforcement internals must not appear in model-visible output.
    expect(toolResult.receiptId).toBeUndefined();
    expect(toolResult.traceId).toBeUndefined();
    expect(toolResult.verification).toBeUndefined();
  });

  it("forwards all arguments to client.execute", async () => {
    mockRoutes({
      "/v1/actions": {
        actions: [
          { action_id: "http_fetch", version: "1.0.0", risk_level: "low" },
        ],
      },
      "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
      "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
    });

    const { latchgateToolset } = await import("../src/toolset.js");

    const mockClient = {
      execute: vi.fn().mockResolvedValue({
        output: {},
        receiptId: "r",
        traceId: "t",
      }),
    };

    const { tools } = await latchgateToolset({
      gateUrl: "http://localhost:3000",
      client: mockClient as any,
    });

    await (tools["http_fetch"] as any).execute({
      url: "https://x.com",
      method: "HEAD",
    });

    expect(mockClient.execute).toHaveBeenCalledWith("http_fetch", {
      url: "https://x.com",
      method: "HEAD",
    });
  });

  it("errors never throw — always return LatchGateToolError", async () => {
    mockRoutes({
      "/v1/actions": {
        actions: [{ action_id: "test", version: "1.0.0", risk_level: "low" }],
      },
      "/v1/actions/test/schema/request": { type: "object", properties: {} },
      "/v1/actions/test": { action_id: "test" },
    });

    const { latchgateToolset } = await import("../src/toolset.js");

    const mockClient = {
      execute: vi.fn().mockRejectedValue(new Error("kaboom")),
    };

    const { tools } = await latchgateToolset({
      gateUrl: "http://localhost:3000",
      client: mockClient as any,
    });

    // Should NOT throw — should return error object
    const toolResult = await (tools["test"] as any).execute({});
    expect(toolResult.error).toBeDefined();
    expect(toolResult.actionId).toBe("test");
  });

  it("invokes onAudit callback on successful execution", async () => {
    mockRoutes({
      "/v1/actions": {
        actions: [
          { action_id: "http_fetch", version: "1.0.0", risk_level: "low" },
        ],
      },
      "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
      "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
    });

    const { latchgateToolset } = await import("../src/toolset.js");

    const mockResult = {
      output: { status: 200 },
      receiptId: "rcpt_AUDIT",
      traceId: "trace_AUDIT",
      verification: { outcome: "verified" },
    };

    const mockClient = {
      execute: vi.fn().mockResolvedValue(mockResult),
    };

    const auditCallback = vi.fn();

    const { tools } = await latchgateToolset({
      gateUrl: "http://localhost:3000",
      client: mockClient as any,
      onAudit: auditCallback,
    });

    await (tools["http_fetch"] as any).execute({ url: "https://example.com" });

    expect(auditCallback).toHaveBeenCalledOnce();
    expect(auditCallback).toHaveBeenCalledWith({
      actionId: "http_fetch",
      receiptId: "rcpt_AUDIT",
      traceId: "trace_AUDIT",
      verification: { outcome: "verified" },
    });
  });

  it("does not invoke onAudit on error", async () => {
    mockRoutes({
      "/v1/actions": {
        actions: [{ action_id: "test", version: "1.0.0", risk_level: "low" }],
      },
      "/v1/actions/test/schema/request": { type: "object", properties: {} },
      "/v1/actions/test": { action_id: "test" },
    });

    const { latchgateToolset } = await import("../src/toolset.js");
    const { LatchGateDenied } = await import("latchgate");

    const mockClient = {
      execute: vi.fn().mockRejectedValue(new LatchGateDenied("test", "denied")),
    };

    const auditCallback = vi.fn();

    const { tools } = await latchgateToolset({
      gateUrl: "http://localhost:3000",
      client: mockClient as any,
      onAudit: auditCallback,
    });

    await (tools["test"] as any).execute({});

    expect(auditCallback).not.toHaveBeenCalled();
  });
});
