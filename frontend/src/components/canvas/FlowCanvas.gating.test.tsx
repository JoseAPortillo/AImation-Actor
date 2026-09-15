import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import { http, HttpResponse } from "msw";
import type { FlowNode } from "../../state/useFlowStore";
import { useFlowStore } from "../../state/useFlowStore";
import { server } from "../../test/server";
import { TEST_BASE } from "../../test/handlers/nodeCatalog";
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

function renderCanvas() {
  return render(
    <ReactFlowProvider>
      <FlowCanvas />
    </ReactFlowProvider>,
  );
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

describe("SchemaNode video-source timeslider gating (golden-poses-ux)", () => {
  /** A 1×1 JPEG blob so fetchFrameJpeg has a real body to return. */
  const JPEG_BYTES = new Uint8Array([
    0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xff, 0xd9,
  ]);

  function videoNode(videoPath: string | null): FlowNode {
    const node = makeNode(videoSource);
    return {
      ...node,
      data: {
        ...node.data,
        params: videoPath !== null ? { video_path: videoPath } : {},
      },
    };
  }

  function stubFrameEndpoint() {
    server.use(
      http.get(`${TEST_BASE}/media/frame`, () =>
        HttpResponse.arrayBuffer(JPEG_BYTES, {
          headers: {
            "Content-Type": "image/jpeg",
            "X-Frame-Count": "3",
          },
        }),
      ),
    );
  }

  it("renders a placeholder for a video-source node without a selected video and issues no frame request", async () => {
    stubFrameEndpoint();
    const onFrame = vi.fn();
    server.use(
      http.get(`${TEST_BASE}/media/frame`, () => {
        onFrame();
        return HttpResponse.arrayBuffer(JPEG_BYTES, {
          headers: { "Content-Type": "image/jpeg", "X-Frame-Count": "3" },
        });
      }),
    );
    useFlowStore.setState({ nodes: [videoNode(null)] });
    renderCanvas();

    expect(screen.getByTestId("timeslider-placeholder")).toBeInTheDocument();
    // No video → the component must not fetch (spec: placeholder, no request).
    expect(onFrame).not.toHaveBeenCalled();
    expect(screen.queryByTestId("timeslider-track")).not.toBeInTheDocument();
  });

  it("renders the live timeslider for a video-source node with a selected video", async () => {
    stubFrameEndpoint();
    useFlowStore.setState({ nodes: [videoNode("uploads/ab12_video.mp4")] });
    renderCanvas();

    const slider = await screen.findByTestId("timeslider-track");
    expect(slider).toBeInTheDocument();
    expect(screen.queryByTestId("timeslider-placeholder")).not.toBeInTheDocument();
  });

  it("renders NO timeslider for non-video-source nodes", () => {
    useFlowStore.setState({ nodes: [makeNode(passThrough), makeNode(pose2d)] });
    renderCanvas();

    expect(screen.queryAllByTestId("timeslider")).toHaveLength(0);
    expect(screen.queryAllByTestId("timeslider-placeholder")).toHaveLength(0);
  });
});