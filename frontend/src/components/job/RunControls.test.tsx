import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RunControls, type RunControlsProps } from "./RunControls";
import { useFlowStore } from "../../state/useFlowStore";
import { useJobStore } from "../../state/useJobStore";
import nodeCatalogFixture from "../../test/fixtures/nodeCatalog.json";
import type { NodeSchema } from "../../api/types";
import * as exportModule from "../../core/export";

const catalog = nodeCatalogFixture as NodeSchema[];
const videoSource = catalog.find((n) => n.type === "video-source")!;

/** Minimal NeutralMotionDoc-shaped result value for viewer tests. */
function motionResult(): Record<string, unknown> {
  return {
    outputs: {
      n_ab12cd: {
        motion: {
          meta: {
            version: "1.0",
            fps: 24,
            units: "m",
            up_axis: "Y",
            source_type: "neutral",
            duration_frames: 1,
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
          frames: [
            {
              frame: 1,
              time: 0,
              pose: {
                transforms: {
                  Root: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
                  Hips: { translation: [0, 0.5, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
                },
              },
              confidence: 0.9,
            },
          ],
        },
      },
    },
  };
}

function readyNode(): ReturnType<typeof makeNode> {
  return makeNode("src", { video_path: "ok.avi", end: 5, resize: 64 });
}
function makeNode(id: string, params: Record<string, unknown>) {
  return {
    id,
    type: "schema" as const,
    position: { x: 0, y: 0 },
    data: { schema: videoSource, params },
  };
}

function renderRun(props: Partial<RunControlsProps> = {}) {
  return render(
    <RunControls
      onError={(m) => void m}
      {...props}
    />,
  );
}

beforeEach(() => {
  useFlowStore.setState({ nodes: [], edges: [], selectedNodeId: null, connectionHint: null });
  useJobStore.setState({ jobId: null, status: "idle", error: null, logs: [], result: null });
  vi.restoreAllMocks();
});

describe("RunControls run gating (GE-3)", () => {
  it("disables Run and names the missing param when the graph is incomplete", () => {
    useFlowStore.setState({
      nodes: [makeNode("src", {})] as never,
    });
    renderRun();
    const run = screen.getByTestId("run-button") as HTMLButtonElement;
    expect(run.disabled).toBe(true);
    expect(screen.getByTestId("run-block-reason")).toHaveTextContent(/video_path/);
  });

  it("enables Run when every required param is set", () => {
    useFlowStore.setState({ nodes: [readyNode()] as never });
    renderRun();
    const run = screen.getByTestId("run-button") as HTMLButtonElement;
    expect(run.disabled).toBe(false);
  });
});

describe("RunControls submit (GE-1)", () => {
  it("submits the canonical graph on Run click", async () => {
    useFlowStore.setState({ nodes: [readyNode()] as never });
    const submit = vi
      .spyOn(useJobStore.getState(), "submit")
      .mockResolvedValue(undefined);
    renderRun();
    fireEvent.click(screen.getByTestId("run-button"));
    await waitFor(() => expect(submit).toHaveBeenCalled());
    const arg = submit.mock.calls[0][0];
    expect(arg.version).toBe("1.0");
    expect(arg.nodes[0].type).toBe("video-source");
  });
});

describe("RunControls stop (GE-2)", () => {
  it("calls cancel when the job is running", async () => {
    useJobStore.setState({ jobId: "job-1", status: "running" });
    const cancel = vi.spyOn(useJobStore.getState(), "cancel").mockResolvedValue(undefined);
    renderRun();
    fireEvent.click(screen.getByTestId("stop-button"));
    await waitFor(() => expect(cancel).toHaveBeenCalled());
  });
});

describe("RunControls running feedback", () => {
  it("shows the Processing… status while the job is running", () => {
    useJobStore.setState({ jobId: "job-1", status: "running" });
    renderRun();
    expect(screen.getByTestId("job-status-processing")).toHaveTextContent(/Processing/i);
    expect(screen.queryByTestId("job-status")).toBeNull();
  });
});

describe("RunControls logs + results (GE-1, GE-2)", () => {
  it("renders logs and outputs after a succeeded job", () => {
    useJobStore.setState({
      status: "succeeded",
      logs: ["node ok"],
      result: { outputs: { src: { frames: "yes" } } },
    });
    renderRun();
    expect(screen.getByTestId("job-logs")).toHaveTextContent("node ok");
    expect(screen.getByTestId("job-status")).toHaveTextContent("succeeded");
  });

  it("renders the error message on a failed job", () => {
    useJobStore.setState({ status: "failed", error: "boom", logs: ["step 1"] });
    renderRun();
    expect(screen.getByTestId("job-error")).toHaveTextContent("boom");
    expect(screen.getByTestId("job-logs")).toHaveTextContent("step 1");
  });
});

describe("RunControls motion viewer", () => {
  it("renders the viewer and raw details when the result contains a motion", () => {
    useJobStore.setState({
      status: "succeeded",
      logs: [],
      result: motionResult(),
    });
    renderRun();
    expect(screen.getByTestId("job-result-viewer")).toBeInTheDocument();
    expect(screen.getByTestId("job-result-raw")).toBeInTheDocument();
    // The raw <pre> still exists inside the details.
    expect(screen.getByTestId("job-result")).toBeInTheDocument();
  });

  it("does not render the viewer when the result lacks a motion-shaped value", () => {
    useJobStore.setState({
      status: "succeeded",
      logs: [],
      result: { outputs: { src: { frames: "yes" } } },
    });
    renderRun();
    expect(screen.queryByTestId("job-result-viewer")).toBeNull();
    expect(screen.getByTestId("job-result")).toBeInTheDocument();
  });
});

describe("RunControls export buttons", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders export BVH and JSON buttons when motion is present", () => {
    useJobStore.setState({
      status: "succeeded",
      logs: [],
      result: motionResult(),
    });
    renderRun();
    expect(screen.getByTestId("export-bvh")).toBeInTheDocument();
    expect(screen.getByTestId("export-json")).toBeInTheDocument();
  });

  it("calls downloadTextFile with BVH payload when Export BVH is clicked", async () => {
    const downloadSpy = vi.spyOn(exportModule, "downloadTextFile").mockImplementation(() => {});
    vi.spyOn(exportModule, "motionExportPayloads").mockReturnValue({
      bvh: { filename: "motion.bvh", content: "bvh-content", mimeType: "application/octet-stream" },
      json: { filename: "motion.json", content: "{}", mimeType: "application/json" },
    });

    useJobStore.setState({
      status: "succeeded",
      logs: [],
      result: motionResult(),
    });
    renderRun();

    fireEvent.click(screen.getByTestId("export-bvh"));

    await waitFor(() => {
      expect(downloadSpy).toHaveBeenCalledWith("motion.bvh", "bvh-content", "application/octet-stream");
    });
  });

  it("calls downloadTextFile with JSON payload when Export JSON is clicked", async () => {
    const downloadSpy = vi.spyOn(exportModule, "downloadTextFile").mockImplementation(() => {});
    vi.spyOn(exportModule, "motionExportPayloads").mockReturnValue({
      bvh: { filename: "motion.bvh", content: "", mimeType: "application/octet-stream" },
      json: { filename: "motion.json", content: '{"test": true}', mimeType: "application/json" },
    });

    useJobStore.setState({
      status: "succeeded",
      logs: [],
      result: motionResult(),
    });
    renderRun();

    fireEvent.click(screen.getByTestId("export-json"));

    await waitFor(() => {
      expect(downloadSpy).toHaveBeenCalledWith("motion.json", '{"test": true}', "application/json");
    });
  });

  it("does not render export buttons when motion is not present", () => {
    useJobStore.setState({
      status: "succeeded",
      logs: [],
      result: { outputs: { src: { frames: "yes" } } },
    });
    renderRun();
    expect(screen.queryByTestId("export-bvh")).not.toBeInTheDocument();
    expect(screen.queryByTestId("export-json")).not.toBeInTheDocument();
  });
});
