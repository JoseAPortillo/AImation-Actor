import { describe, it, expect, beforeEach } from "vitest";
import { useFlowStore } from "./useFlowStore";
import { usePinsStore, type Pin } from "./usePinsStore";
import type { NodeSchema } from "../api/types";

/** Minimal pin used to prove node removal scrubs pin state (task 4.4). */
function makePin(id: string, frame: number): Pin {
  return {
    id,
    label: "G1",
    frame,
    status: "success",
    confidence: 0.95,
    detection: [],
  };
}

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

describe("useFlowStore removeNode clears pins (4.4)", () => {
  beforeEach(() => {
    useFlowStore.setState({
      nodes: [],
      edges: [],
      selectedNodeId: null,
      connectionHint: null,
    });
    usePinsStore.setState({ pinsByNode: {} });
  });

  it("removing a node also removes its pins", () => {
    useFlowStore.getState().addNode(VIDEO_SOURCE);
    const nodeId = useFlowStore.getState().nodes[0].id;
    // Seed pins as the timeslider would after marking golden poses.
    usePinsStore.setState({
      pinsByNode: { [nodeId]: [makePin("s1", 3), makePin("s2", 9)] },
    });
    expect(usePinsStore.getState().pinsByNode[nodeId]).toHaveLength(2);

    useFlowStore.getState().removeNode(nodeId);
    expect(useFlowStore.getState().nodes).toHaveLength(0);
    // Golden poses are frontend-only (D2) and scoped to the node's lifetime:
    // deleting the node discards its pins (task 4.4).
    expect(usePinsStore.getState().pinsByNode[nodeId]).toBeUndefined();
  });

  it("pins of OTHER nodes survive a node removal", () => {
    useFlowStore.getState().addNode(VIDEO_SOURCE);
    useFlowStore.getState().addNode(POSE_2D);
    const [a, b] = useFlowStore.getState().nodes.map((n) => n.id);
    usePinsStore.setState({
      pinsByNode: {
        [a]: [makePin("s1", 3)],
        [b]: [makePin("t1", 5)],
      },
    });

    useFlowStore.getState().removeNode(a);
    expect(usePinsStore.getState().pinsByNode[a]).toBeUndefined();
    expect(usePinsStore.getState().pinsByNode[b]).toHaveLength(1);
  });
});

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