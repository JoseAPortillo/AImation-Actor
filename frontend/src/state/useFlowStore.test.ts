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
