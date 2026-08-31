import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { FlowNode } from "../../state/useFlowStore";
import { useFlowStore } from "../../state/useFlowStore";
import nodeCatalogFixture from "../../test/fixtures/nodeCatalog.json";
import type { NodeSchema } from "../../api/types";
import { FlowCanvas } from "./FlowCanvas";

const catalog = nodeCatalogFixture as NodeSchema[];
const videoSource = catalog.find((n) => n.type === "video-source")!;
const pose2d = catalog.find((n) => n.type === "pose-2d")!;
const pose3d = catalog.find((n) => n.type === "pose-3d")!;
const merge = catalog.find((n) => n.type === "merge")!;
const passThrough = catalog.find((n) => n.type === "pass-through")!;

function makeNode(schema: NodeSchema): FlowNode {
  return {
    id: `${schema.type}_abcdef12`,
    type: "schema",
    position: { x: 0, y: 0 },
    data: { schema, params: {} },
  };
}

beforeEach(() => {
  useFlowStore.setState({ nodes: [], edges: [], selectedNodeId: null, connectionHint: null });
});

describe("FlowCanvas connection gating (EC-2)", () => {
  it("accepts a compatible source→target connection (video-source.frames → pose-2d.frames)", () => {
    useFlowStore.setState({ nodes: [makeNode(videoSource), makeNode(pose2d)] });
    useFlowStore
      .getState()
      .onConnect({
        source: `${videoSource.type}_abcdef12`,
        sourceHandle: "frames",
        target: `${pose2d.type}_abcdef12`,
        targetHandle: "frames",
      });
    expect(useFlowStore.getState().edges).toHaveLength(1);
    expect(useFlowStore.getState().connectionHint).toBeNull();
  });

  it("rejects an incompatible pair without forming an edge (pose-3d.keypoints_3d → merge.input_a)", () => {
    useFlowStore.setState({ nodes: [makeNode(pose3d), makeNode(merge)] });
    // Simulate the FlowCanvas isValidConnection gate rejecting the attempt.
    useFlowStore
      .getState()
      .onConnect({
        source: `${pose3d.type}_abcdef12`,
        sourceHandle: "keypoints_3d",
        target: `${merge.type}_abcdef12`,
        targetHandle: "input_a",
      });
    expect(useFlowStore.getState().edges).toHaveLength(0);
  });

  it("renders the inline incompatibility hint when set (EC-2 s2)", () => {
    useFlowStore.getState().setConnectionHint(
      "Cannot connect pose_3d → frames: incompatible port types.",
    );
    render(<FlowCanvas />);
    expect(screen.getByTestId("connection-hint")).toHaveTextContent(
      "incompatible port types",
    );
  });

  it("allows an ANY port to accept any typed output (pose-2d.keypoints → pass-through.input)", () => {
    useFlowStore.setState({ nodes: [makeNode(pose2d), makeNode(passThrough)] });
    useFlowStore
      .getState()
      .onConnect({
        source: `${pose2d.type}_abcdef12`,
        sourceHandle: "keypoints",
        target: `${passThrough.type}_abcdef12`,
        targetHandle: "input",
      });
    expect(useFlowStore.getState().edges).toHaveLength(1);
    expect(useFlowStore.getState().connectionHint).toBeNull();
  });
});
