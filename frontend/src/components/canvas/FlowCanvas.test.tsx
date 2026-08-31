import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { Edge } from "@xyflow/react";
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

beforeEach(() => {
  useFlowStore.setState({ nodes: [], edges: [], selectedNodeId: null });
});

describe("FlowCanvas schema handles (EC-1)", () => {
  it("renders one source handle per schema output port with no ghost ports", async () => {
    useFlowStore.setState({ nodes: [makeNode(videoSource)] });
    render(<FlowCanvas />);
    // video-source: 2 outputs (frames, fps) and 0 inputs.
    await waitFor(() => {
      expect(screen.getAllByTestId("schema-output-handle")).toHaveLength(2);
    });
    expect(screen.queryAllByTestId("schema-input-handle")).toHaveLength(0);
  });

  it("renders both input and output handles for a two-sided node (EC-1 s1)", async () => {
    useFlowStore.setState({ nodes: [makeNode(pose2d)] });
    render(<FlowCanvas />);
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
    render(<FlowCanvas />);
    await waitFor(() => {
      expect(screen.getByText("Frame Extractor")).toBeInTheDocument();
    });
    expect(screen.getByText("Pose 2D")).toBeInTheDocument();
    // 3 schema handles across both nodes (2 out + 1 in + 1 out).
    expect(screen.getAllByTestId("schema-output-handle")).toHaveLength(3);
    expect(screen.getAllByTestId("schema-input-handle")).toHaveLength(1);
  });
});
