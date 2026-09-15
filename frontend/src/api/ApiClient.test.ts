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

  it("graphExecute propagates an optional AbortSignal to the request", async () => {
    const { transport, client } = makeClient("tok");
    const graph = { version: "1.0", nodes: [], edges: [] };
    transport.enqueue(200, { job_id: "j1", kind: "graph-execute", status: "running" });
    const controller = new AbortController();
    await client.graphExecute(graph, controller.signal);
    expect(transport.requests[0].signal).toBe(controller.signal);
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
      outputs: [{ name: "frames", data_type: "frames", required: true, default: null, description: "" }],
      params: [
        { name: "start", data_type: "number", required: true, default: null, description: "" },
      ],
    };
    transport.enqueue(200, [schema]);
    const result = await client.nodes();
    expect(result[0].type).toBe("frame-range");
    expect(result[0].outputs[0].data_type).toBe("frames");
  });

  it("getJobLogs returns a string list", async () => {
    const { transport, client } = makeClient("tok");
    transport.enqueue(200, ["a", "b", "c"]);
    const logs = await client.getJobLogs("j1");
    expect(logs).toEqual(["a", "b", "c"]);
  });
});

describe("ApiClient media + pose surface (Phase A frame-pose-detection)", () => {
  it("fetchFrameJpeg GETs /media/frame with query params and returns blob + X-Frame-Count", async () => {
    const { transport, client } = makeClient("tok");
    const jpeg = new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xd9])], { type: "image/jpeg" });
    await transport.enqueueBlob(jpeg, 200, { "X-Frame-Count": "120" });
    const result = await client.fetchFrameJpeg("uploads/ab12_video.mp4", 7, 640);
    const req = transport.requests[0];
    expect(req.method).toBe("GET");
    expect(req.url).toBe(
      "http://127.0.0.1:8765/media/frame?video_path=uploads%2Fab12_video.mp4&frame_index=7&width=640",
    );
    expect(req.headers.get("authorization")).toBe("Bearer tok");
    expect(result.frameCount).toBe(120);
    expect(result.blob.type).toBe("image/jpeg");
    const bytes = new Uint8Array(await result.blob.arrayBuffer());
    expect(bytes.length).toBe(4);
  });

  it("fetchFrameJpeg omits width and reports 0 frame count on a missing header", async () => {
    const { transport, client } = makeClient("tok");
    await transport.enqueueBlob(new Blob([new Uint8Array([1, 2, 3])]), 200);
    const result = await client.fetchFrameJpeg("uploads/ab12_video.mp4", 1);
    const req = transport.requests[0];
    expect(req.url).toBe("http://127.0.0.1:8765/media/frame?video_path=uploads%2Fab12_video.mp4&frame_index=1");
    expect(result.frameCount).toBe(0);
  });

  it("fetchFrameJpeg maps 401 to ApiError kind 'unauthorized'", async () => {
    const { transport, client } = makeClient("bad");
    transport.enqueue(401, { detail: "Not authenticated" });
    const err = await client.fetchFrameJpeg("uploads/ab12_video.mp4", 1).catch((e) => e);
    expect(err).toMatchObject({ kind: "unauthorized" });
    expect(String(err.message)).toContain("Not authenticated");
  });

  it("detectPose GETs /detect/{video_path}/{frame_index} and returns SingleFramePose", async () => {
    const { transport, client } = makeClient("tok");
    const pose = {
      keypoints: [{ label: "nose", x: 0.5, y: 0.2, confidence: 0.95 }],
      confidence: 0.95,
    };
    transport.enqueue(200, pose);
    const result = await client.detectPose("uploads/ab12_video.mp4", 5);
    const req = transport.requests[0];
    expect(req.method).toBe("GET");
    expect(req.url).toBe("http://127.0.0.1:8765/detect/uploads/ab12_video.mp4/5");
    expect(req.headers.get("authorization")).toBe("Bearer tok");
    expect(result).toEqual(pose);
    expect(result.confidence).toBe(0.95);
    expect(result.keypoints[0].label).toBe("nose");
  });

  it("detectPose maps 501 (backend unavailable) to ApiError kind 'server'", async () => {
    const { transport, client } = makeClient("tok");
    transport.enqueue(501, { detail: "ONNX single-frame inference not yet implemented (Phase C)" });
    const err = await client.detectPose("uploads/ab12_video.mp4", 5).catch((e) => e);
    expect(err).toMatchObject({ kind: "server" });
    expect(String(err.message)).toContain("ONNX");
  });

  it("uploadVideo POSTs multipart FormData and returns the stored reference", async () => {
    const { transport, client } = makeClient("tok");
    transport.enqueue(200, { reference: "uploads/ab12videos_video.mp4" });
    const file = new File(["fake video bytes"], "video.mp4", { type: "video/mp4" });
    const reference = await client.uploadVideo(file);
    const req = transport.requests[0];
    expect(req.method).toBe("POST");
    expect(req.url).toBe("http://127.0.0.1:8765/media/upload");
    expect(req.headers.get("authorization")).toBe("Bearer tok");
    expect(req.headers.get("content-type")).toBeNull();
    expect(req.body).toBeInstanceOf(FormData);
    const entry = (req.body as FormData).get("file");
    expect(entry).toBeInstanceOf(File);
    expect((entry as File).name).toBe("video.mp4");
    expect((entry as File).size).toBe(file.size);
    expect(reference).toBe("uploads/ab12videos_video.mp4");
  });

  it("uploadVideo throws ApiError kind 'invalid' when the response lacks a reference", async () => {
    const { transport, client } = makeClient("tok");
    transport.enqueue(200, {});
    const err = await client.uploadVideo(new File(["x"], "video.mp4")).catch((e) => e);
    expect(err).toMatchObject({ kind: "invalid" });
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
