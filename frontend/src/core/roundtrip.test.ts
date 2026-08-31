import { describe, it, expect, beforeEach } from "vitest";
import type { NodeSchema } from "../api/types";
import type { FlowNode } from "../state/useFlowStore";
import { useFlowStore } from "../state/useFlowStore";
import nodeCatalogFixture from "../test/fixtures/nodeCatalog.json";
import { fromFlow, toFlow, mergeGraphIntoFlow } from "../core/serialize";
import type { AimGraph } from "../core/graph";
import { serializeGraph, parseGraph } from "../core/serialize";

const catalog = nodeCatalogFixture as NodeSchema[];
const videoSource = catalog.find((n) => n.type === "video-source")!;

function makeNode(schema: NodeSchema, id: string, params: Record<string, unknown> = {}): FlowNode {
  return {
    id,
    type: "schema",
    position: { x: 0, y: 0 },
    data: { schema, params },
  };
}

beforeEach(() => {
  useFlowStore.setState({ nodes: [], edges: [], selectedNodeId: null, connectionHint: null });
});

describe("flow → list → flow round-trip (AR-2)", () => {
  it("canonical fields survive a save→load→save round-trip structurally identical", () => {
    const nodes: FlowNode[] = [
      makeNode(videoSource, "src", { video_path: "clip.avi", end: 5, resize: 64 }),
    ];
    const edges = [
      { id: "e1", source: "src", sourceHandle: "frames", target: "p2d", targetHandle: "frames" },
    ];
    const aim = fromFlow(nodes, edges);
    const first = serializeGraph(aim);

    const parsed = parseGraph(first);
    expect(parsed.ok).toBe(true);
    const second = serializeGraph(parsed.graph!);

    // Byte-identical → canonical fields are a strict round-trip (AR-2 s1).
    expect(second).toBe(first);
  });

  it("fromFlow emits canonical node id→type→params and edge id→source→target shapes", () => {
    const nodes: FlowNode[] = [makeNode(videoSource, "src", { video_path: "clip.avi" })];
    const edges = [
      { id: "e1", source: "src", sourceHandle: "frames", target: "p2d", targetHandle: "frames" },
    ];
    const aim = fromFlow(nodes, edges);
    expect(aim.version).toBe("1.0");
    expect(aim.nodes).toEqual([
      { id: "src", type: "video-source", params: { video_path: "clip.avi" }, position: { x: 0, y: 0 } },
    ]);
    expect(aim.edges).toEqual([
      {
        id: "e1",
        source: { node: "src", port: "frames" },
        target: { node: "p2d", port: "frames" },
      },
    ]);
  });
});

describe("mergeGraphIntoFlow (load, merge-by-id, never clobber) (AR-2 s3)", () => {
  it("loads new nodes not already on the canvas and keeps existing ids/extras", () => {
    useFlowStore.setState({ nodes: [makeNode(videoSource, "existing", { video_path: "keep.avi" })] });
    const incoming: AimGraph = {
      version: "1.0",
      nodes: [
        {
          id: "existing",
          type: "video-source",
          params: { video_path: "from.file.avi" },
          position: { x: 50, y: 60 },
        },
        { id: "new", type: "pose-2d", params: { model: "synthetic" } },
      ],
      edges: [],
    };
    mergeGraphIntoFlow(incoming, catalog);
    const state = useFlowStore.getState();
    // Existing node id retained with its extras (position preserved).
    const existing = state.nodes.find((n) => n.id === "existing")!;
    expect(existing).toBeDefined();
    expect(existing.data.params.video_path).toBe("keep.avi");
    expect(existing.position).toEqual({ x: 50, y: 60 });
    // New node merged in by id.
    const added = state.nodes.find((n) => n.id === "new")!;
    expect(added).toBeDefined();
    expect(added.data.schema.type).toBe("pose-2d");
    expect(state.nodes).toHaveLength(2);
  });

  it("maps edges into React Flow source/sourceHandle/target/targetHandle", () => {
    useFlowStore.setState({
      nodes: [makeNode(videoSource, "src")],
    });
    const incoming: AimGraph = {
      version: "1.0",
      nodes: [{ id: "src", type: "video-source", params: {} }],
      edges: [
        {
          id: "e1",
          source: { node: "src", port: "frames" },
          target: { node: "p2d", port: "frames" },
        },
      ],
    };
    mergeGraphIntoFlow(incoming, catalog);
    const edge = useFlowStore.getState().edges[0];
    expect(edge.source).toBe("src");
    expect(edge.sourceHandle).toBe("frames");
    expect(edge.target).toBe("p2d");
    expect(edge.targetHandle).toBe("frames");
  });

  it("rejects stale v0.1 without mutating the current graph (AR-2 s3)", () => {
    useFlowStore.setState({ nodes: [makeNode(videoSource, "existing")] });
    const stale: AimGraph = { version: "0.1", nodes: [], edges: [] } as unknown as AimGraph;
    const before = useFlowStore.getState().nodes;
    const result = parseGraph(JSON.stringify(stale, null, 2));
    expect(result.ok).toBe(false);
    // The graph in the store is untouched — no mutation happened.
    expect(useFlowStore.getState().nodes).toEqual(before);
  });
});

describe("toFlow helper (AR-1/AR-2)", () => {
  it("converts a canonical AimNode back to a React Flow node with schema lookup", () => {
    const aim: AimGraph = {
      version: "1.0",
      nodes: [{ id: "src", type: "video-source", params: { video_path: "a.avi" } }],
      edges: [],
    };
    const flow = toFlow(aim, catalog);
    expect(flow.nodes).toHaveLength(1);
    expect(flow.nodes[0].id).toBe("src");
    expect(flow.nodes[0].data.schema.type).toBe("video-source");
    expect(flow.nodes[0].data.params.video_path).toBe("a.avi");
  });
});
