import { describe, it, expect, beforeEach } from "vitest";
import { useFlowStore } from "./useFlowStore";
import type { NodeSchema } from "../api/types";

const VIDEO_SOURCE: NodeSchema = {
  type: "video-source",
  category: "source",
  title: "Frame Extractor",
  description: "",
  inputs: [],
  outputs: [
    { name: "frames", data_type: "frames", required: true, default: null, description: "" },
  ],
  params: [
    { name: "video_path", data_type: "video_path", required: true, default: null, description: "" },
  ],
};

const POSE_2D: NodeSchema = {
  type: "pose-2d",
  category: "ai",
  title: "Pose 2D",
  description: "Estimate 2D keypoints from video frames",
  inputs: [
    { name: "frames", data_type: "frames", required: true, default: null, description: "" },
  ],
  outputs: [
    { name: "keypoints", data_type: "keypoints_2d", required: true, default: null, description: "" },
  ],
  params: [],
};

describe("useFlowStore addNode (NP-2)", () => {
  beforeEach(() => {
    useFlowStore.setState({ nodes: [], edges: [] });
  });

  it("adds a node with a unique id prefixed by the node type and empty params", () => {
    useFlowStore.getState().addNode(VIDEO_SOURCE);
    const nodes = useFlowStore.getState().nodes;
    expect(nodes).toHaveLength(1);
    // React Flow node `type` selects the SchemaNode component; the domain
    // type lives in data.schema.type (per design D/EC-1).
    expect(nodes[0].data.schema.type).toBe("video-source");
    expect(nodes[0].id.startsWith("video-source_")).toBe(true);
    expect(nodes[0].data.params).toEqual({});
  });

  it("produces distinct ids for two additions of the same type", () => {
    useFlowStore.getState().addNode(VIDEO_SOURCE);
    useFlowStore.getState().addNode(VIDEO_SOURCE);
    const nodes = useFlowStore.getState().nodes;
    expect(nodes).toHaveLength(2);
    expect(nodes[0].id).not.toBe(nodes[1].id);
  });
});

describe("undo/redo history", () => {
  beforeEach(() => {
    useFlowStore.setState({
      nodes: [],
      edges: [],
      selectedNodeId: null,
      connectionHint: null,
      historyPast: [],
      historyFuture: [],
    });
  });

  it("addNode is undone and redone", () => {
    const store = useFlowStore.getState();
    store.addNode(VIDEO_SOURCE);
    expect(useFlowStore.getState().nodes).toHaveLength(1);

    useFlowStore.getState().undo();
    expect(useFlowStore.getState().nodes).toHaveLength(0);

    useFlowStore.getState().redo();
    expect(useFlowStore.getState().nodes).toHaveLength(1);
  });

  it("removeNode is undone, restoring both nodes and the edge", () => {
    const store = useFlowStore.getState();
    store.addNode(VIDEO_SOURCE);
    useFlowStore.getState().addNode(POSE_2D);
    // Connect video-source.frames → pose-2d.frames (compatible frames type).
    useFlowStore.getState().onConnect({
      source: useFlowStore.getState().nodes[0].id,
      sourceHandle: "frames",
      target: useFlowStore.getState().nodes[1].id,
      targetHandle: "frames",
    });
    expect(useFlowStore.getState().edges).toHaveLength(1);

    useFlowStore.getState().removeNode(useFlowStore.getState().nodes[0].id);
    expect(useFlowStore.getState().nodes).toHaveLength(1);
    expect(useFlowStore.getState().edges).toHaveLength(0);

    useFlowStore.getState().undo();
    const state = useFlowStore.getState();
    expect(state.nodes).toHaveLength(2);
    expect(state.edges).toHaveLength(1);
  });

  it("duplicateNode and toggleCollapse are undone", () => {
    const store = useFlowStore.getState();
    store.addNode(VIDEO_SOURCE);
    const id = useFlowStore.getState().nodes[0].id;
    const before = useFlowStore.getState().nodes.length;

    useFlowStore.getState().duplicateNode(id);
    expect(useFlowStore.getState().nodes).toHaveLength(before + 1);

    useFlowStore.getState().undo();
    expect(useFlowStore.getState().nodes).toHaveLength(before);

    // toggleCollapse: mutate, then undo restores prior collapsed state.
    useFlowStore.getState().toggleCollapse(id);
    expect(useFlowStore.getState().nodes[0].data.collapsed).toBe(true);

    useFlowStore.getState().undo();
    expect(useFlowStore.getState().nodes[0].data.collapsed).toBeUndefined();
  });

  it("clear is undone", () => {
    const store = useFlowStore.getState();
    store.addNode(VIDEO_SOURCE);
    store.addNode(POSE_2D);
    expect(useFlowStore.getState().nodes).toHaveLength(2);

    useFlowStore.getState().clear();
    expect(useFlowStore.getState().nodes).toHaveLength(0);

    useFlowStore.getState().undo();
    expect(useFlowStore.getState().nodes).toHaveLength(2);
  });

  it("onConnect is undone, restoring the pre-edge node count", () => {
    const store = useFlowStore.getState();
    store.addNode(VIDEO_SOURCE);
    useFlowStore.getState().addNode(POSE_2D);
    const [a, b] = useFlowStore.getState().nodes;

    useFlowStore.getState().onConnect({
      source: a.id,
      sourceHandle: "frames",
      target: b.id,
      targetHandle: "frames",
    });
    expect(useFlowStore.getState().edges).toHaveLength(1);

    useFlowStore.getState().undo();
    const state = useFlowStore.getState();
    expect(state.edges).toHaveLength(0);
    expect(state.nodes).toHaveLength(2);
  });

  it("updateParams undo restores old params", () => {
    const store = useFlowStore.getState();
    store.addNode(VIDEO_SOURCE);
    const id = useFlowStore.getState().nodes[0].id;
    useFlowStore.getState().undo(); // undo the addNode so updateParams is the only committed op
    useFlowStore.getState().redo(); // back to the added node

    useFlowStore.getState().updateParams(id, { a: 1 });
    useFlowStore.getState().updateParams(id, { a: 2 });
    expect(useFlowStore.getState().nodes[0].data.params).toEqual({ a: 2 });

    useFlowStore.getState().undo();
    expect(useFlowStore.getState().nodes[0].data.params).toEqual({ a: 1 });

    useFlowStore.getState().undo();
    expect(useFlowStore.getState().nodes[0].data.params).toEqual({});
  });

  it("undo beyond history is a no-op, likewise redo with empty future", () => {
    const state = useFlowStore.getState();
    expect(() => state.undo()).not.toThrow();
    expect(useFlowStore.getState().nodes).toHaveLength(0);

    expect(() => useFlowStore.getState().redo()).not.toThrow();
    expect(useFlowStore.getState().nodes).toHaveLength(0);
  });

  it("history is capped at 50 entries, dropping the oldest", () => {
    const store = useFlowStore.getState();
    for (let i = 0; i < 55; i++) {
      store.addNode(VIDEO_SOURCE);
    }
    expect(useFlowStore.getState().nodes).toHaveLength(55);
    expect(useFlowStore.getState().historyPast).toHaveLength(50);

    for (let i = 0; i < 50; i++) {
      useFlowStore.getState().undo();
    }
    expect(useFlowStore.getState().nodes).toHaveLength(5);

    useFlowStore.getState().undo();
    expect(useFlowStore.getState().nodes).toHaveLength(5);
  });

  it("drag-position change does not create an undo entry by itself", () => {
    const store = useFlowStore.getState();
    store.addNode(VIDEO_SOURCE);
    const id = useFlowStore.getState().nodes[0].id;
    const initialPosition = useFlowStore.getState().nodes[0].position;
    useFlowStore.getState().undo(); // clear the addNode history
    useFlowStore.getState().redo();
    const historyLengthBeforeDrag = useFlowStore.getState().historyPast.length;

    // Simulate FlowCanvas drag: one commitHistory at drag start, then position
    // changes active through onNodesChange (no history entries per change).
    useFlowStore.getState().commitHistory();
    useFlowStore.getState().onNodesChange([
      { type: "position", id, position: { x: 10, y: 10 } },
    ]);
    expect(useFlowStore.getState().historyPast).toHaveLength(historyLengthBeforeDrag + 1);

    useFlowStore.getState().undo();
    expect(useFlowStore.getState().nodes[0].position).toEqual(initialPosition);
  });

  it("undo after commitHistory restores pre-commit state", () => {
    const store = useFlowStore.getState();
    store.addNode(VIDEO_SOURCE);
    const id = useFlowStore.getState().nodes[0].id;
    const initialPosition = useFlowStore.getState().nodes[0].position;
    useFlowStore.getState().undo(); // clear the addNode history
    useFlowStore.getState().redo();
    const historyLengthBefore = useFlowStore.getState().historyPast.length;

    useFlowStore.getState().commitHistory();
    useFlowStore.getState().onNodesChange([
      { type: "position", id, position: { x: 99, y: 99 } },
    ]);
    expect(useFlowStore.getState().nodes[0].position).toEqual({ x: 99, y: 99 });

    useFlowStore.getState().undo();
    expect(useFlowStore.getState().nodes[0].position).toEqual(initialPosition);
    expect(useFlowStore.getState().historyPast).toHaveLength(historyLengthBefore);
  });
});
