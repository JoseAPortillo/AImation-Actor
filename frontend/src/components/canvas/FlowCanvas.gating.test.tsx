import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import type { FlowNode } from "../../state/useFlowStore";
import { useFlowStore } from "../../state/useFlowStore";
import { useJobStore } from "../../state/useJobStore";
import nodeCatalogFixture from "../../test/fixtures/nodeCatalog.json";
import type { NodeSchema, NeutralMotionDoc } from "../../api/types";
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

/** Minimal motion doc reusing the 2-bone skeleton shape from the core tests. */
function motionFixture(): NeutralMotionDoc {
  return {
    meta: {
      version: "1.0",
      fps: 24,
      units: "m",
      up_axis: "Y",
      source_type: "neutral",
      duration_frames: 3,
      style: "default",
      model_version: "0.1",
      graph_hash: "abc",
    },
    skeleton: {
      bones: {
        Root: { name: "Root", parent: null, rest_position: [0, 0, 0] },
        Hips: { name: "Hips", parent: "Root", rest_position: [0, 1, 0] },
      },
    },
    frames: Array.from({ length: 3 }, (_, i) => ({
      frame: i + 1,
      time: (i + 1) * 0.041,
      pose: {
        transforms: {
          Root: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
          Hips: { translation: [0, 0.5 + i * 0.1, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
        },
      },
    })),
  };
}

function renderCanvas() {
  return render(
    <ReactFlowProvider>
      <FlowCanvas />
    </ReactFlowProvider>,
  );
}

beforeEach(() => {
  useFlowStore.setState({ nodes: [], edges: [], selectedNodeId: null, connectionHint: null });
  // Reset the job store so prior tests' succeeded status doesn't leak.
  useJobStore.setState({ status: "idle", result: null });
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
    render(
      <ReactFlowProvider>
        <FlowCanvas />
      </ReactFlowProvider>,
    );
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

describe("SchemaNode inline motion preview (roadmap §20.6)", () => {
  it("renders node-preview for a node with a motion output and not for one without", () => {
    const withMotion = makeNode(pose3d);
    const withoutMotion = makeNode(passThrough);
    useFlowStore.setState({ nodes: [withMotion, withoutMotion] });
    useJobStore.setState({
      status: "succeeded",
      result: {
        outputs: {
          [withMotion.id]: { motion: motionFixture() },
        },
      },
    });
    renderCanvas();

    // Only the node whose id has a motion output gets the preview.
    expect(screen.queryAllByTestId("node-preview")).toHaveLength(1);
  });

  it("does not render the preview when a node's output is not motion-shaped", () => {
    const node = makeNode(pose3d);
    useFlowStore.setState({ nodes: [node] });
    useJobStore.setState({
      status: "succeeded",
      result: {
        outputs: {
          [node.id]: { frames: "yes" },
        },
      },
    });
    renderCanvas();

    expect(screen.queryAllByTestId("node-preview")).toHaveLength(0);
  });
});
