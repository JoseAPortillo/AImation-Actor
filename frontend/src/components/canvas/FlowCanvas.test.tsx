import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ReactFlowProvider, type Edge } from "@xyflow/react";
import type { FlowNode } from "../../state/useFlowStore";
import { useFlowStore } from "../../state/useFlowStore";
import nodeCatalogFixture from "../../test/fixtures/nodeCatalog.json";
import type { NodeSchema } from "../../api/types";
import { FlowCanvas } from "./FlowCanvas";
import "@xyflow/react/dist/style.css";

const catalog = nodeCatalogFixture as NodeSchema[];
const videoSource = catalog.find((n) => n.type === "video-source")!;
const pose2d = catalog.find((n) => n.type === "pose-2d")!;

function makeNode(schema: NodeSchema): FlowNode {
  return {
    id: `${schema.type}_abcdef12`,
    type: "schema",
    position: { x: 0, y: 0 },
    data: { schema, params: {} },
  };
}

// FlowCanvas uses `useReactFlow()` (screenToFlowPosition) for palette drag &
// drop, so it must render under a ReactFlowProvider — mirroring the App tree.
function renderCanvas() {
  return render(
    <ReactFlowProvider>
      <FlowCanvas />
    </ReactFlowProvider>,
  );
}

beforeEach(() => {
  useFlowStore.setState({
    nodes: [],
    edges: [],
    selectedNodeId: null,
    connectionHint: null,
    connectionOrigin: null,
    historyPast: [],
    historyFuture: [],
  });
});

describe("FlowCanvas schema handles (EC-1)", () => {
  it("renders one source handle per schema output port with no ghost ports", async () => {
    useFlowStore.setState({ nodes: [makeNode(videoSource)] });
    renderCanvas();
    // video-source: 2 outputs (frames, fps) and 0 inputs.
    await waitFor(() => {
      expect(screen.getAllByTestId("schema-output-handle")).toHaveLength(2);
    });
    expect(screen.queryAllByTestId("schema-input-handle")).toHaveLength(0);
  });

  it("renders both input and output handles for a two-sided node (EC-1 s1)", async () => {
    useFlowStore.setState({ nodes: [makeNode(pose2d)] });
    renderCanvas();
    await waitFor(() => {
      expect(screen.getAllByTestId("schema-input-handle")).toHaveLength(1);
    });
    expect(screen.getByText("Pose 2D")).toBeInTheDocument();
    expect(screen.getAllByTestId("schema-output-handle")).toHaveLength(1);
  });

  it("integrates into the App canvas host and renders all store nodes", async () => {
    const nodes: FlowNode[] = [makeNode(videoSource), makeNode(pose2d)];
    const edges: Edge[] = [];
    useFlowStore.setState({ nodes, edges });
    renderCanvas();
    await waitFor(() => {
      expect(screen.getByText("Frame Extractor")).toBeInTheDocument();
    });
    expect(screen.getByText("Pose 2D")).toBeInTheDocument();
    // 3 schema handles across both nodes (2 out + 1 in + 1 out).
    expect(screen.getAllByTestId("schema-output-handle")).toHaveLength(3);
    expect(screen.getAllByTestId("schema-input-handle")).toHaveLength(1);
  });
});

describe("FlowCanvas minimap navigation", () => {
  it("renders a pannable minimap overlay for large graphs", async () => {
    useFlowStore.setState({ nodes: [makeNode(videoSource), makeNode(pose2d)] });
    renderCanvas();
    const minimap = await screen.findByTestId("rf__minimap");
    expect(minimap).toBeInTheDocument();
  });
});

describe("FlowCanvas live connection validity feedback (EC-2 s3)", () => {
  it("shows no validity state on any handle while no connection drag is active", async () => {
    useFlowStore.setState({ nodes: [makeNode(videoSource), makeNode(pose2d)] });
    renderCanvas();
    await waitFor(() => {
      expect(screen.getAllByTestId("schema-input-handle")).toHaveLength(1);
    });
    const inputHandle = screen.getByTestId("schema-input-handle");
    expect(inputHandle).not.toHaveAttribute("data-valid");
    expect(inputHandle).not.toHaveAttribute("data-invalid");
  });

  it("glows a compatible target handle green while dragging a compatible source", async () => {
    useFlowStore.setState({ nodes: [makeNode(videoSource), makeNode(pose2d)] });
    useFlowStore.setState({
      connectionOrigin: {
        nodeId: "video-source_abcdef12",
        handleId: "frames",
        handleType: "source",
        dataType: "frames",
      },
    });
    renderCanvas();
    await waitFor(() => {
      expect(screen.getAllByTestId("schema-input-handle")).toHaveLength(1);
    });
    // pose-2d.frames accepts frames → valid highlight.
    expect(screen.getByTestId("schema-input-handle")).toHaveAttribute(
      "data-valid",
    );
  });

  it("dims an incompatible target handle while dragging", async () => {
    // temporal-cleanup consumes neutral_animation; frames cannot feed it.
    const temporalCleanup = catalog.find((n) => n.type === "temporal-cleanup")!;
    useFlowStore.setState({
      nodes: [makeNode(videoSource), makeNode(temporalCleanup)],
      connectionOrigin: {
        nodeId: "video-source_abcdef12",
        handleId: "frames",
        handleType: "source",
        dataType: "frames",
      },
    });
    renderCanvas();
    await waitFor(() => {
      expect(screen.getAllByTestId("schema-input-handle")).toHaveLength(1);
    });
    expect(screen.getByTestId("schema-input-handle")).toHaveAttribute(
      "data-invalid",
    );
    expect(screen.getByTestId("schema-input-handle")).not.toHaveAttribute(
      "data-valid",
    );
  });

  it("leaves handles unfazed when the drag originates on the same node", async () => {
    // pose-2d has both an input (frames) and an output (keypoints_2d).
    useFlowStore.setState({ nodes: [makeNode(pose2d)] });
    useFlowStore.setState({
      connectionOrigin: {
        nodeId: "pose-2d_abcdef12",
        handleId: "keypoints",
        handleType: "source",
        dataType: "keypoints_2d",
      },
    });
    renderCanvas();
    await waitFor(() => {
      expect(screen.getAllByTestId("schema-input-handle")).toHaveLength(1);
    });
    expect(screen.getByTestId("schema-input-handle")).not.toHaveAttribute(
      "data-valid",
    );
    expect(screen.getByTestId("schema-input-handle")).not.toHaveAttribute(
      "data-invalid",
    );
  });
});
