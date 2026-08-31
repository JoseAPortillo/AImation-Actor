import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { useJobStore, validateRunReadiness } from "./useJobStore";
import type { ApiClient } from "../api/ApiClient";
import type { JobSnapshot } from "../api/types";
import type { AimGraph } from "../core/graph";
import type { FlowNode } from "./useFlowStore";
import nodeCatalogFixture from "../test/fixtures/nodeCatalog.json";
import type { NodeSchema } from "../api/types";

const catalog = nodeCatalogFixture as NodeSchema[];
const videoSource = catalog.find((n) => n.type === "video-source")!;

const GRAPH: AimGraph = {
  version: "1.0",
  nodes: [{ id: "src", type: "video-source", params: { video_path: "clip.avi" } }],
  edges: [],
};

function snapshot(partial: Partial<JobSnapshot>): JobSnapshot {
  return {
    job_id: "job-1",
    kind: "graph-execute",
    status: "running",
    error: null,
    result: null,
    logs: [],
    ...partial,
  };
}

let mockApi: {
  graphExecute: ReturnType<typeof vi.fn>;
  getJob: ReturnType<typeof vi.fn>;
  getJobLogs: ReturnType<typeof vi.fn>;
  cancel: ReturnType<typeof vi.fn>;
};

function installMock(client: {
  graphExecute?: unknown;
  getJob?: unknown;
  getJobLogs?: unknown;
  cancel?: unknown;
}) {
  mockApi = {
    graphExecute: (client.graphExecute as ReturnType<typeof vi.fn>) ?? vi.fn(),
    getJob: (client.getJob as ReturnType<typeof vi.fn>) ?? vi.fn(),
    getJobLogs: (client.getJobLogs as ReturnType<typeof vi.fn>) ?? vi.fn(),
    cancel: (client.cancel as ReturnType<typeof vi.fn>) ?? vi.fn(),
  };
  useJobStore.setState({ api: mockApi as unknown as ApiClient });
}

beforeEach(() => {
  vi.useFakeTimers();
  useJobStore.setState({
    jobId: null,
    status: "idle",
    error: null,
    logs: [],
    result: null,
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useJobStore.submit (GE-1)", () => {
  it("submits the graph and records the job id + running status", async () => {
    installMock({
      graphExecute: vi.fn().mockResolvedValue(snapshot({ status: "running" })),
      getJob: vi.fn().mockResolvedValue(snapshot({ status: "running" })),
      getJobLogs: vi.fn().mockResolvedValue(["done"]),
    });
    const store = useJobStore.getState();
    await store.submit(GRAPH);

    expect(mockApi.graphExecute).toHaveBeenCalledWith(GRAPH);
    expect(useJobStore.getState().jobId).toBe("job-1");
    expect(useJobStore.getState().status).toBe("running");
  });
});

describe("validateRunReadiness (GE-3)", () => {
  it("returns ready when every required param without a default is set", () => {
    // video_path/end/resize are required with null default (blocking);
    // start has default 0 and is not blocking.
    const nodes: FlowNode[] = [
      {
        id: "src",
        type: "schema",
        position: { x: 0, y: 0 },
        data: {
          schema: videoSource,
          params: { video_path: "ok.avi", end: 5, resize: 64 },
        },
      },
    ];
    const r = validateRunReadiness(nodes);
    expect(r.ready).toBe(true);
  });

  it("returns not-ready with the missing required param name when omitted", () => {
    // video_path has no default and is required → missing.
    // end/resize have default=null and are optional → not missing.
    const nodes: FlowNode[] = [
      {
        id: "src",
        type: "schema",
        position: { x: 0, y: 0 },
        data: { schema: videoSource, params: {} },
      },
    ];
    const r = validateRunReadiness(nodes);
    expect(r.ready).toBe(false);
    if (!r.ready) {
      expect(r.missing).toEqual(
        expect.arrayContaining(["src:video_path"]),
      );
    }
  });

  it("reports an empty graph as not ready", () => {
    const r = validateRunReadiness([]);
    expect(r.ready).toBe(false);
  });
});

describe("useJobStore.poll to terminal (GE-1, GE-2)", () => {
  it("fetches logs + result when the job reaches succeeded", async () => {
    installMock({
      graphExecute: vi.fn().mockResolvedValue(snapshot({ status: "running" })),
      getJob: vi
        .fn()
        .mockResolvedValueOnce(snapshot({ status: "running" }))
        .mockResolvedValueOnce(
          snapshot({
            status: "succeeded",
            result: { outputs: { src: { frames: [] } } },
          }),
        ),
      getJobLogs: vi.fn().mockResolvedValue(["node ok"]),
    });
    const store = useJobStore.getState();
    await store.submit(GRAPH);
    // Advance two poll ticks (running → succeeded).
    await vi.advanceTimersByTimeAsync(1600);
    const s = useJobStore.getState();
    expect(s.status).toBe("succeeded");
    expect(s.logs).toEqual(["node ok"]);
  });

  it("records error logs when the job fails (GE-2)", async () => {
    installMock({
      graphExecute: vi.fn().mockResolvedValue(snapshot({ status: "running" })),
      getJob: vi
        .fn()
        .mockResolvedValueOnce(snapshot({ status: "running" }))
        .mockResolvedValueOnce(snapshot({ status: "failed", error: "boom" })),
      getJobLogs: vi.fn().mockResolvedValue(["step 1", "boom"]),
    });
    const store = useJobStore.getState();
    await store.submit(GRAPH);
    await vi.advanceTimersByTimeAsync(1600);
    const s = useJobStore.getState();
    expect(s.status).toBe("failed");
    expect(s.error).toBe("boom");
    expect(s.logs).toContain("boom");
  });
});

describe("useJobStore.cancel (GE-2)", () => {
  it("posts cancel and records cancelled status", async () => {
    installMock({
      cancel: vi.fn().mockResolvedValue(snapshot({ status: "cancelled" })),
    });
    useJobStore.setState({ jobId: "job-1", status: "running" });
    const st = useJobStore.getState();
    await st.cancel();
    expect(mockApi.cancel).toHaveBeenCalledWith("job-1");
    expect(useJobStore.getState().status).toBe("cancelled");
  });
});
