import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RunControls, type RunControlsProps } from "./RunControls";
import { useFlowStore } from "../../state/useFlowStore";
import { useJobStore } from "../../state/useJobStore";
import nodeCatalogFixture from "../../test/fixtures/nodeCatalog.json";
import type { NodeSchema } from "../../api/types";

const catalog = nodeCatalogFixture as NodeSchema[];
const videoSource = catalog.find((n) => n.type === "video-source")!;

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
      getNodes={() => useFlowStore.getState().nodes}
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
