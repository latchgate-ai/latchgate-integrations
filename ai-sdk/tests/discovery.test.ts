import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { discoverActions } from "../src/discovery.js";

// ---------------------------------------------------------------------------
// Mock fetch
// ---------------------------------------------------------------------------

const SAMPLE_ACTIONS = {
  actions: [
    { action_id: "http_fetch", version: "1.0.0", risk_level: "low" },
    { action_id: "send_message", version: "1.0.0", risk_level: "high" },
    {
      action_id: "database",
      version: "1.0.0",
      risk_level: "medium",
      database_mode: "hybrid",
    },
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
  egress: {
    profile: "proxy_allowlist",
    allowed_domains: ["api.github.com"],
  },
};

const SAMPLE_DATABASE_DETAIL = {
  action_id: "database",
  version: "1.0.0",
  risk_level: "medium",
  declared_side_effects: ["database_write"],
  database: {
    mode: "hybrid",
    statements: [
      {
        id: "get_user",
        operation: "select",
        tables: ["users"],
        param_count: 1,
      },
    ],
    allows_parameterized_queries: true,
    parameterized_operations: ["select"],
  },
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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("discoverActions", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("discovers all actions", async () => {
    mockRoutes({
      "/v1/actions": SAMPLE_ACTIONS,
      "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
      "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
      "/v1/actions/send_message/schema/request": { type: "object" },
      "/v1/actions/send_message": { action_id: "send_message" },
      "/v1/actions/database/schema/request": { type: "object" },
      "/v1/actions/database": SAMPLE_DATABASE_DETAIL,
    });

    const descriptors = await discoverActions("http://localhost:3000");

    expect(descriptors).toHaveLength(3);
    const ids = new Set(descriptors.map((d) => d.actionId));
    expect(ids).toEqual(new Set(["http_fetch", "send_message", "database"]));
  });

  it("applies include filter", async () => {
    mockRoutes({
      "/v1/actions": SAMPLE_ACTIONS,
      "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
      "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
    });

    const descriptors = await discoverActions("http://localhost:3000", {
      include: new Set(["http_fetch"]),
    });

    expect(descriptors).toHaveLength(1);
    expect(descriptors[0].actionId).toBe("http_fetch");
  });

  it("applies exclude filter", async () => {
    mockRoutes({
      "/v1/actions": SAMPLE_ACTIONS,
      "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
      "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
      "/v1/actions/send_message/schema/request": { type: "object" },
      "/v1/actions/send_message": { action_id: "send_message" },
    });

    const descriptors = await discoverActions("http://localhost:3000", {
      exclude: new Set(["database"]),
    });

    expect(descriptors).toHaveLength(2);
    expect(descriptors.map((d) => d.actionId)).not.toContain("database");
  });

  it("returns permissive schema on 404", async () => {
    mockRoutes({
      "/v1/actions": {
        actions: [
          { action_id: "no_schema", version: "1.0.0", risk_level: "low" },
        ],
      },
      "/v1/actions/no_schema": { action_id: "no_schema" },
    });

    const descriptors = await discoverActions("http://localhost:3000", {
      allowSchemaless: true,
    });

    expect(descriptors).toHaveLength(1);
  });

  it("returns empty array for zero actions", async () => {
    mockRoutes({ "/v1/actions": { actions: [] } });

    const descriptors = await discoverActions("http://localhost:3000");
    expect(descriptors).toEqual([]);
  });

  it("normalizes trailing slash in gate URL", async () => {
    mockRoutes({
      "/v1/actions": {
        actions: [{ action_id: "test", version: "1.0.0", risk_level: "low" }],
      },
      "/v1/actions/test/schema/request": { type: "object" },
      "/v1/actions/test": { action_id: "test" },
    });

    const descriptors = await discoverActions("http://localhost:3000/");
    expect(descriptors).toHaveLength(1);
  });

  it("default description redacts egress internals", async () => {
    mockRoutes({
      "/v1/actions": {
        actions: [
          { action_id: "http_fetch", version: "1.0.0", risk_level: "low" },
        ],
      },
      "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
      "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
    });

    const descriptors = await discoverActions("http://localhost:3000");
    expect(descriptors[0].description).not.toContain("proxy_allowlist");
    expect(descriptors[0].description).not.toContain("api.github.com");
    expect(descriptors[0].description).toContain("http_read");
  });

  it("debug description includes egress info", async () => {
    mockRoutes({
      "/v1/actions": {
        actions: [
          { action_id: "http_fetch", version: "1.0.0", risk_level: "low" },
        ],
      },
      "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
      "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
    });

    const descriptors = await discoverActions("http://localhost:3000", {
      securityDetail: "debug",
    });
    expect(descriptors[0].description).toContain("proxy_allowlist");
    expect(descriptors[0].description).toContain("api.github.com");
    expect(descriptors[0].description).toContain("http_read");
  });

  it("default description redacts database internals", async () => {
    mockRoutes({
      "/v1/actions": {
        actions: [
          { action_id: "database", version: "1.0.0", risk_level: "medium" },
        ],
      },
      "/v1/actions/database/schema/request": { type: "object" },
      "/v1/actions/database": SAMPLE_DATABASE_DETAIL,
    });

    const descriptors = await discoverActions("http://localhost:3000");
    expect(descriptors[0].description).not.toContain("hybrid");
    expect(descriptors[0].description).not.toContain("get_user");
  });

  it("debug description includes database info", async () => {
    mockRoutes({
      "/v1/actions": {
        actions: [
          { action_id: "database", version: "1.0.0", risk_level: "medium" },
        ],
      },
      "/v1/actions/database/schema/request": { type: "object" },
      "/v1/actions/database": SAMPLE_DATABASE_DETAIL,
    });

    const descriptors = await discoverActions("http://localhost:3000", {
      securityDetail: "debug",
    });
    expect(descriptors[0].description).toContain("hybrid");
    expect(descriptors[0].description).toContain("get_user");
    expect(descriptors[0].description).toContain("Parameterized");
  });

  it("include + exclude combined", async () => {
    mockRoutes({
      "/v1/actions": SAMPLE_ACTIONS,
      "/v1/actions/http_fetch/schema/request": SAMPLE_HTTP_FETCH_SCHEMA,
      "/v1/actions/http_fetch": SAMPLE_HTTP_FETCH_DETAIL,
    });

    const descriptors = await discoverActions("http://localhost:3000", {
      include: new Set(["http_fetch", "send_message"]),
      exclude: new Set(["send_message"]),
    });

    expect(descriptors).toHaveLength(1);
    expect(descriptors[0].actionId).toBe("http_fetch");
  });
});
