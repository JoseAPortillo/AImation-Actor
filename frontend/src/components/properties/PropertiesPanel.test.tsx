import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import type { FlowNode } from "../../state/useFlowStore";
import { useFlowStore } from "../../state/useFlowStore";
import nodeCatalogFixture from "../../test/fixtures/nodeCatalog.json";
import type { NodeSchema } from "../../api/types";
import { PropertiesPanel } from "./PropertiesPanel";
import { buildBlockingTemplate, NEUTRAL_SKELETON_BONES } from "../../core/blockingTemplate";

const catalog = nodeCatalogFixture as NodeSchema[];
const frameRange = catalog.find((n) => n.type === "frame-range")!;
const v2m = catalog.find((n) => n.type === "video-to-motion")!;
const videoSource = catalog.find((n) => n.type === "video-source")!;
const blockingInput = catalog.find((n) => n.type === "blocking-input")!;

function makeJsonFile(content: string): File {
  return new File([content], "blocking.json", { type: "application/json" });
}

function fireFileChange(input: HTMLInputElement, file: File) {
  fireEvent.change(input, { target: { files: [file] } });
}

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

  it("renders a JSON-widget param as the JSON editor + Load button, not a plain text input", () => {
    useFlowStore.setState({
      nodes: [makeNode(blockingInput, { blocking: "{}" })],
      selectedNodeId: `${blockingInput.type}_abcdef12`,
    });
    render(<PropertiesPanel />);
    const editor = screen.getByTestId("param-blocking");
    expect(editor.tagName).toBe("DIV");
    expect(within(editor).getByTestId("param-blocking-textarea").tagName).toBe("TEXTAREA");
    expect(within(editor).getByTestId("param-blocking-overlay")).toBeInTheDocument();
    expect(screen.getByTestId("param-load-blocking")).toBeInTheDocument();
    expect(screen.getByTestId("param-file-blocking")).toBeInTheDocument();
  });

  it("does not render a JSON widget for a plain STRING param", () => {
    // pose-3d.model is a plain STRING param without a widget hint.
    const pose3d = catalog.find((n) => n.type === "pose-3d")!;
    useFlowStore.setState({
      nodes: [makeNode(pose3d, { model: "synthetic" })],
      selectedNodeId: `${pose3d.type}_abcdef12`,
    });
    render(<PropertiesPanel />);
    const model = screen.getByTestId("param-model");
    expect(model.tagName).toBe("INPUT");
    expect(model).toHaveAttribute("type", "text");
    expect(screen.queryByTestId("param-load-model")).not.toBeInTheDocument();
    expect(screen.queryByTestId("param-file-model")).not.toBeInTheDocument();
  });

  it("typing in the JSON-widget textarea updates the node params", () => {
    useFlowStore.setState({
      nodes: [makeNode(blockingInput, { blocking: "{}" })],
      selectedNodeId: `${blockingInput.type}_abcdef12`,
    });
    render(<PropertiesPanel />);
    const textarea = screen.getByTestId("param-blocking-textarea");
    fireEvent.change(textarea, { target: { value: '{"keyposes":[{"frame":1,"pose":{}}]}' } });
    const params = useFlowStore.getState().nodes[0].data.params;
    expect(params.blocking).toBe('{"keyposes":[{"frame":1,"pose":{}}]}');
  });

  it("selecting a JSON file populates the param from the file content", async () => {
    useFlowStore.setState({
      nodes: [makeNode(blockingInput, { blocking: "{}" })],
      selectedNodeId: `${blockingInput.type}_abcdef12`,
    });
    render(<PropertiesPanel />);
    const payload = '{"keyposes":[{"frame":1,"pose":{}}]}';
    const input = screen.getByTestId("param-file-blocking") as HTMLInputElement;
    fireFileChange(input, makeJsonFile(payload));
    await waitFor(() => {
      const params = useFlowStore.getState().nodes[0].data.params;
      expect(params.blocking).toBe(payload);
    });
  });

  it("converts a loaded NeutralMotion doc into a BlockingInput payload (blocking-input)", async () => {
    const identityTransform = {
      translation: [0, 0, 0],
      rotation: [1, 0, 0, 0],
      scale: [1, 1, 1],
    };
    const pose = { Root: identityTransform, Head: identityTransform };
    const frames = Array.from({ length: 3 }, (_unused, i) => ({
      frame: i + 1,
      time: i / 2,
      pose: { transforms: pose },
      confidence: 0.9,
    }));
    const neutralDoc = {
      meta: {
        version: "1.0",
        fps: 24,
        units: "meters",
        up_axis: "Y-up",
        source_type: "video",
        duration_frames: 3,
        style: "neutral",
        model_version: "v1",
        graph_hash: "abc",
      },
      skeleton: {
        bones: {
          Root: { name: "Root", parent: null, rest_position: [0, 0, 0] },
          Head: { name: "Head", parent: "Root", rest_position: [0, 1, 0] },
        },
      },
      frames,
      contacts: {},
      keyposes: [],
      tracking: { confidence_per_frame: [0.9, 0.9, 0.9] },
    };

    useFlowStore.setState({
      nodes: [makeNode(blockingInput, { blocking: "{}" })],
      selectedNodeId: `${blockingInput.type}_abcdef12`,
    });
    render(<PropertiesPanel />);

    const input = screen.getByTestId("param-file-blocking") as HTMLInputElement;
    fireFileChange(input, makeJsonFile(JSON.stringify(neutralDoc)));

    await waitFor(() => {
      const params = useFlowStore.getState().nodes[0].data.params;
      const parsed = JSON.parse(String(params.blocking)) as Record<string, unknown>;
      expect(Array.isArray(parsed.keyposes)).toBe(true);
      expect((parsed.keyposes as unknown[]).length).toBeGreaterThanOrEqual(1);
      for (const stripped of ["frames", "meta", "contacts", "tracking"]) {
        expect(parsed).not.toHaveProperty(stripped);
      }
    });
    const note = screen.getByTestId("blocking-convert-note");
    expect(note).toBeInTheDocument();
    expect(note).toHaveTextContent("24 fps");
  });

  it("shows a Download template button for a JSON-widget param", () => {
    useFlowStore.setState({
      nodes: [makeNode(blockingInput, { blocking: "{}" })],
      selectedNodeId: `${blockingInput.type}_abcdef12`,
    });
    render(<PropertiesPanel />);
    expect(screen.getByTestId("param-download-template-blocking")).toBeInTheDocument();
  });

  it("generated blocking template contains every neutral skeleton bone", () => {
    const json = buildBlockingTemplate();
    const parsed = JSON.parse(json) as { keyposes: { pose: Record<string, unknown> }[] };
    const firstPose = parsed.keyposes[0].pose;
    expect(Object.keys(firstPose)).toEqual(NEUTRAL_SKELETON_BONES);
    // Each bone carries the full transform shape.
    const sample = firstPose["Root"] as { translation: unknown[]; rotation: unknown[]; scale: unknown[] };
    expect(sample.translation).toHaveLength(3);
    expect(sample.rotation).toHaveLength(4);
    expect(sample.scale).toHaveLength(3);
  });

  it("template has two example keyposes by default", () => {
    const json = buildBlockingTemplate();
    const parsed = JSON.parse(json) as { keyposes: { frame: number; weight: number }[] };
    expect(parsed.keyposes).toHaveLength(2);
    expect(parsed.keyposes[0].frame).toBe(1);
    expect(parsed.keyposes[1].frame).toBe(30);
  });
});
