import { describe, it, expect } from "vitest";
import { ApiClient } from "./ApiClient";
import { MockTransport } from "./transport";
import type { NodeSchema } from "./types";

function makeClient(token = "secret-token") {
  const transport = new MockTransport();
  const client = new ApiClient("http://127.0.0.1:8765", token, transport);
  return { transport, client };
}

describe("ApiClient endpoint surface (HTTP-1)", () => {
  it("health hits GET /health and carries NO Authorization header (HTTP-1/HTTP-2)", async () => {
    const { transport, client } = makeClient("secret-token");
    transport.enqueue(200, { status: "ok" });
    const result = await client.health();
    const req = transport.requests[0];
    expect(req.method).toBe("GET");
    expect(req.url).toBe("http://127.0.0.1:8765/health");
    expect(req.headers.get("authorization")).toBeNull();
    expect(result).toEqual({ status: "ok" });
  });

  it("nodes hits GET /nodes/types and carries the Bearer header", async () => {
    const { transport, client } = makeClient("token-abc");
    transport.enqueue(200, [
      { type: "video-source", category: "source", title: "Frame Extractor" },
    ]);
    const result = await client.nodes();
    const req = transport.requests[0];
    expect(req.method).toBe("GET");
    expect(req.url).toBe("http://127.0.0.1:8765/nodes/types");
    expect(req.headers.get("authorization")).toBe("Bearer token-abc");
    expect(result).toHaveLength(1);
  });

  it("graphExecute POSTs the graph to /jobs/graph/execute", async () => {
    const { transport, client } = makeClient("tok");
    const graph = { version: "1.0", nodes: [], edges: [] };
    transport.enqueue(200, { job_id: "j1", kind: "graph-execute", status: "running" });
    const result = await client.graphExecute(graph);
    const req = transport.requests[0];
    expect(req.method).toBe("POST");
    expect(req.url).toBe("http://127.0.0.1:8765/jobs/graph/execute");
    expect(JSON.parse(req.body as string)).toEqual(graph);
    expect(req.headers.get("authorization")).toBe("Bearer tok");
    expect(result.job_id).toBe("j1");
  });

  it("getJob/getJobResult/getJobLogs/cancel hit the exact paths", async () => {
    const { transport, client } = makeClient("tok");
    transport.enqueue(200, { job_id: "j1", kind: "graph-execute", status: "succeeded" });
    await client.getJob("j1");
    expect(transport.requests[0].url).toBe("http://127.0.0.1:8765/jobs/j1");

    transport.enqueue(200, { status: "succeeded", result: { outputs: {} } });
    await client.getJobResult("j1");
    expect(transport.requests[1].url).toBe("http://127.0.0.1:8765/jobs/j1/result");

    transport.enqueue(200, ["line1", "line2"]);
    await client.getJobLogs("j1");
    expect(transport.requests[2].url).toBe("http://127.0.0.1:8765/jobs/j1/logs");

    transport.enqueue(200, { job_id: "j1", kind: "graph-execute", status: "cancelled" });
    await client.cancel("j1");
    const req = transport.requests[3];
    expect(req.method).toBe("POST");
    expect(req.url).toBe("http://127.0.0.1:8765/jobs/j1/cancel");
  });

  it("parses node catalog into typed NodeSchema list", async () => {
    const { transport, client } = makeClient("tok");
    const schema: NodeSchema = {
      type: "frame-range",
      category: "source",
      title: "Frame Range",
      description: "",
      inputs: [],
      outputs: [{ name: "frames", data_type: "frame_stream", required: true, default: null, description: "" }],
      params: [
        { name: "start", data_type: "number", required: true, default: null, description: "" },
      ],
    };
    transport.enqueue(200, [schema]);
    const result = await client.nodes();
    expect(result[0].type).toBe("frame-range");
    expect(result[0].outputs[0].data_type).toBe("frame_stream");
  });

  it("getJobLogs returns a string list", async () => {
    const { transport, client } = makeClient("tok");
    transport.enqueue(200, ["a", "b", "c"]);
    const logs = await client.getJobLogs("j1");
    expect(logs).toEqual(["a", "b", "c"]);
  });
});

describe("ApiClient error normalization (HTTP-3)", () => {
  it("maps 401 to ApiError kind 'unauthorized' with message, non-fatal", async () => {
    const { transport, client } = makeClient("bad");
    transport.enqueue(401, { detail: "Not authenticated" });
    const err = await client.nodes().catch((e) => e);
    expect(err).toMatchObject({ kind: "unauthorized" });
    expect(String(err.message)).toContain("Not authenticated");
  });

  it("maps 404 to ApiError kind 'not_found'", async () => {
    const { transport, client } = makeClient("tok");
    transport.enqueue(404, { detail: "job not found" });
    const err = await client.getJob("nope").catch((e) => e);
    expect(err).toMatchObject({ kind: "not_found" });
  });

  it("maps 5xx to ApiError kind 'server'", async () => {
    const { transport, client } = makeClient("tok");
    transport.enqueue(500, { error: "boom" });
    const err = await client.nodes().catch((e) => e);
    expect(err).toMatchObject({ kind: "server" });
  });

  it("maps network failure to ApiError kind 'network'", async () => {
    const { transport, client } = makeClient("tok");
    transport.failNext(new TypeError("Failed to fetch"));
    const err = await client.nodes().catch((e) => e);
    expect(err).toMatchObject({ kind: "network" });
  });
});

describe("ApiClient token behavior (HTTP-2)", () => {
  it("no token configured means authenticated endpoints carry no Authorization", async () => {
    const { transport, client } = makeClient("");
    transport.enqueue(200, []);
    await client.nodes();
    expect(transport.requests[0].headers.get("authorization")).toBeNull();
  });

  it("never writes the token to any web storage (localStorage/sessionStorage)", async () => {
    const { client } = makeClient("super-secret");
    expect(client).toBeDefined();
    const lk = (() => {
      try {
        return typeof globalThis.localStorage === "undefined"
          ? []
          : Object.keys(globalThis.localStorage as Storage);
      } catch {
        return [];
      }
    })();
    const sk = (() => {
      try {
        return typeof globalThis.sessionStorage === "undefined"
          ? []
          : Object.keys(globalThis.sessionStorage as Storage);
      } catch {
        return [];
      }
    })();
    const all = [...lk, ...sk].filter((k) => k.toLowerCase().includes("token"));
    expect(all).toHaveLength(0);
  });
});
