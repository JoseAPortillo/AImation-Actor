import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { FlowNode } from "../../state/useFlowStore";
import { useFlowStore } from "../../state/useFlowStore";
import nodeCatalogFixture from "../../test/fixtures/nodeCatalog.json";
import type { NodeSchema } from "../../api/types";
import { PropertiesPanel } from "./PropertiesPanel";

const catalog = nodeCatalogFixture as NodeSchema[];
const frameRange = catalog.find((n) => n.type === "frame-range")!;
const v2m = catalog.find((n) => n.type === "video-to-motion")!;
const videoSource = catalog.find((n) => n.type === "video-source")!;

function makeNode(schema: NodeSchema, params: Record<string, unknown> = {}): FlowNode {
  return {
    id: `${schema.type}_abcdef12`,
    type: "schema",
    position: { x: 0, y: 0 },
    data: { schema, params },
  };
}

beforeEach(() => {
  useFlowStore.setState({ nodes: [], edges: [], selectedNodeId: null });
});

describe("PropertiesPanel (PP-1, PP-2)", () => {
  it("renders nothing when no node is selected", () => {
    render(<PropertiesPanel />);
    expect(screen.queryByTestId("properties-panel")).not.toBeInTheDocument();
  });

  it("renders NUMBER params as number inputs (frame-range.start/end required)", () => {
    useFlowStore.setState({ nodes: [makeNode(frameRange)], selectedNodeId: `${frameRange.type}_abcdef12` });
    render(<PropertiesPanel />);
    expect(screen.getByLabelText("start")).toBeInTheDocument();
    expect(screen.getByLabelText("end")).toBeInTheDocument();
    expect(screen.getByLabelText("start")).toHaveAttribute("type", "number");
  });

  it("renders BOOLEAN params as checkboxes and STRING params as text inputs", () => {
    useFlowStore.setState({ nodes: [makeNode(v2m)], selectedNodeId: `${v2m.type}_abcdef12` });
    render(<PropertiesPanel />);
    expect(screen.getByLabelText("only_local")).toHaveAttribute("type", "checkbox");
    expect(screen.getByLabelText("person_height_cm")).toHaveAttribute("type", "number");
  });

  it("applies the schema default when the value is unset (PP-1)", () => {
    // v2m params: person_height_cm default 172.0, only_local default true.
    useFlowStore.setState({ nodes: [makeNode(v2m, {})], selectedNodeId: `${v2m.type}_abcdef12` });
    render(<PropertiesPanel />);
    expect(screen.getByLabelText("person_height_cm")).toHaveValue(172);
    expect(screen.getByLabelText("only_local")).toBeChecked();
  });

  it("editing a number param updates the node's in-memory params (PP-1 s2)", () => {
    useFlowStore.setState({
      nodes: [makeNode(frameRange, { start: 0, end: 5 })],
      selectedNodeId: `${frameRange.type}_abcdef12`,
    });
    render(<PropertiesPanel />);
    const start = screen.getByLabelText("start");
    fireEvent.change(start, { target: { value: "10" } });
    const params = useFlowStore.getState().nodes[0].data.params;
    expect(params.start).toBe(10);
  });

  it("shows a non-blocking warning for an absolute video_path (PP-2 s1)", () => {
    useFlowStore.setState({
      nodes: [makeNode(videoSource, { video_path: "C:\\media\\movie.avi" })],
      selectedNodeId: `${videoSource.type}_abcdef12`,
    });
    render(<PropertiesPanel />);
    expect(screen.getByTestId("video-path-warning")).toBeInTheDocument();
    expect(screen.getByTestId("video-path-warning")).toHaveTextContent("relative to the media root");
  });

  it("shows no warning for a valid relative video_path", () => {
    useFlowStore.setState({
      nodes: [makeNode(videoSource, { video_path: "movie.avi" })],
      selectedNodeId: `${videoSource.type}_abcdef12`,
    });
    render(<PropertiesPanel />);
    expect(screen.queryByTestId("video-path-warning")).not.toBeInTheDocument();
  });
});
