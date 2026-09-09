import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SimpleMode } from "./SimpleMode";
import { usePaletteStore } from "../../state/usePaletteStore";
import { useFlowStore } from "../../state/useFlowStore";
import { useUiStore } from "../../state/useUiStore";
import { useJobStore } from "../../state/useJobStore";
import nodeCatalogFixture from "../../test/fixtures/nodeCatalog.json";
import type { AimGraph } from "../../core/graph";
import { saveCustomPreset, loadCustomPresets } from "../../core/presets";
import * as exportModule from "../../core/export";

beforeEach(() => {
  localStorage.clear();
  usePaletteStore.setState({
    catalog: nodeCatalogFixture as never,
    status: "ready",
    error: null,
  });
  useFlowStore.setState({ nodes: [], edges: [] });
  useUiStore.setState({ mode: "simple" });
  useJobStore.setState({ status: "idle", result: null });
});

describe("SimpleMode (AR-3)", () => {
  it("renders the preset cards when the catalog is ready", () => {
    render(<SimpleMode />);
    expect(screen.getByTestId("simple-mode")).toBeInTheDocument();
    expect(screen.getByText("Video to Motion")).toBeInTheDocument();
  });

  it("shows a loading hint while the catalog is empty", () => {
    usePaletteStore.setState({ catalog: [], status: "loading" });
    render(<SimpleMode />);
    expect(screen.getByTestId("simple-mode-loading")).toBeInTheDocument();
    // No preset cards are rendered until the catalog resolves.
    expect(screen.queryByTestId("preset-video-to-motion")).not.toBeInTheDocument();
  });

  it("merges the full wired graph into the canvas and switches to Advanced mode", () => {
    render(<SimpleMode />);
    fireEvent.click(screen.getByTestId("preset-video-to-motion"));

    const { nodes, edges } = useFlowStore.getState();
    // All 4 nodes materialized in canonical order.
    expect(nodes.map((n) => n.data.schema.type)).toEqual([
      "video-source",
      "pose-2d",
      "pose-3d",
      "video-to-motion",
    ]);
    // 3 edges chaining source -> 2D -> 3D -> motion.
    expect(edges).toHaveLength(3);
    // Each edge has proper port handles (names, not "null").
    for (const e of edges) {
      expect(e.sourceHandle).toBeTruthy();
      expect(e.targetHandle).toBeTruthy();
    }
    // Auto-switch to the node editor so the user can inspect/edit and run.
    expect(useUiStore.getState().mode).toBe("advanced");
  });

  it("re-picking the same preset does not duplicate nodes (stable ids)", () => {
    render(<SimpleMode />);
    fireEvent.click(screen.getByTestId("preset-video-to-motion"));
    fireEvent.click(screen.getByTestId("preset-video-to-motion"));
    expect(useFlowStore.getState().nodes).toHaveLength(4);
    expect(useFlowStore.getState().edges).toHaveLength(3);
  });

  it("shows the result panel when job succeeded with motion data", () => {
    const motionDoc = {
      meta: { version: "1.0", fps: 24, units: "m", up_axis: "Y", source_type: "neutral", duration_frames: 1, style: "default", model_version: "0.1", graph_hash: "abc" },
      skeleton: {
        bones: {
          Root: { name: "Root", parent: null, rest_position: [0, 0, 0] },
          Hips: { name: "Hips", parent: "Root", rest_position: [0, 1, 0] },
        },
      },
      frames: [
        {
          frame: 1,
          time: 0.041,
          pose: {
            transforms: {
              Root: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
              Hips: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
            },
          },
        },
      ],
    };

    useJobStore.setState({
      status: "succeeded",
      result: { outputs: { "video-to-motion": { motion: motionDoc } } },
    });

    render(<SimpleMode />);
    expect(screen.getByTestId("simple-mode-result")).toBeInTheDocument();
    // Preset cards are still rendered below.
    expect(screen.getByTestId("preset-video-to-motion")).toBeInTheDocument();
  });

  it("does not show the result panel when job status is idle", () => {
    render(<SimpleMode />);
    expect(screen.queryByTestId("simple-mode-result")).not.toBeInTheDocument();
  });

  it("does not show the result panel when job failed", () => {
    useJobStore.setState({ status: "failed", result: null });
    render(<SimpleMode />);
    expect(screen.queryByTestId("simple-mode-result")).not.toBeInTheDocument();
  });

  describe("SimpleMode export buttons", () => {
    beforeEach(() => {
      vi.restoreAllMocks();
    });

    it("renders export BVH and JSON buttons when result is shown", () => {
      const motionDoc = {
        meta: { version: "1.0", fps: 24, units: "m", up_axis: "Y", source_type: "neutral", duration_frames: 1, style: "default", model_version: "0.1", graph_hash: "abc" },
        skeleton: {
          bones: {
            Root: { name: "Root", parent: null, rest_position: [0, 0, 0] },
            Hips: { name: "Hips", parent: "Root", rest_position: [0, 1, 0] },
          },
        },
        frames: [
          {
            frame: 1,
            time: 0.041,
            pose: {
              transforms: {
                Root: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
                Hips: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
              },
            },
          },
        ],
      };

      useJobStore.setState({
        status: "succeeded",
        result: { outputs: { "video-to-motion": { motion: motionDoc } } },
      });

      render(<SimpleMode />);
      expect(screen.getByTestId("simple-mode-export-bvh")).toBeInTheDocument();
      expect(screen.getByTestId("simple-mode-export-json")).toBeInTheDocument();
    });

    it("calls downloadTextFile with BVH payload when Export BVH is clicked", async () => {
      const downloadSpy = vi.spyOn(exportModule, "downloadTextFile").mockImplementation(() => {});
      vi.spyOn(exportModule, "motionExportPayloads").mockReturnValue({
        bvh: { filename: "motion.bvh", content: "bvh-content", mimeType: "application/octet-stream" },
        json: { filename: "motion.json", content: "{}", mimeType: "application/json" },
      });

      const motionDoc = {
        meta: { version: "1.0", fps: 24, units: "m", up_axis: "Y", source_type: "neutral", duration_frames: 1, style: "default", model_version: "0.1", graph_hash: "abc" },
        skeleton: {
          bones: {
            Root: { name: "Root", parent: null, rest_position: [0, 0, 0] },
            Hips: { name: "Hips", parent: "Root", rest_position: [0, 1, 0] },
          },
        },
        frames: [
          {
            frame: 1,
            time: 0.041,
            pose: {
              transforms: {
                Root: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
                Hips: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
              },
            },
          },
        ],
      };

      useJobStore.setState({
        status: "succeeded",
        result: { outputs: { "video-to-motion": { motion: motionDoc } } },
      });

      render(<SimpleMode />);
      fireEvent.click(screen.getByTestId("simple-mode-export-bvh"));

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

      const motionDoc = {
        meta: { version: "1.0", fps: 24, units: "m", up_axis: "Y", source_type: "neutral", duration_frames: 1, style: "default", model_version: "0.1", graph_hash: "abc" },
        skeleton: {
          bones: {
            Root: { name: "Root", parent: null, rest_position: [0, 0, 0] },
            Hips: { name: "Hips", parent: "Root", rest_position: [0, 1, 0] },
          },
        },
        frames: [
          {
            frame: 1,
            time: 0.041,
            pose: {
              transforms: {
                Root: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
                Hips: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
              },
            },
          },
        ],
      };

      useJobStore.setState({
        status: "succeeded",
        result: { outputs: { "video-to-motion": { motion: motionDoc } } },
      });

      render(<SimpleMode />);
      fireEvent.click(screen.getByTestId("simple-mode-export-json"));

      await waitFor(() => {
        expect(downloadSpy).toHaveBeenCalledWith("motion.json", '{"test": true}', "application/json");
      });
    });
  });
});

describe("SimpleMode My Presets", () => {
  const smallGraph: AimGraph = {
    version: "1.0",
    nodes: [
      { id: "src", type: "video-source", params: { video_path: "clip.avi" }, position: { x: 0, y: 0 } },
      { id: "p2d", type: "pose-2d", params: {}, position: { x: 200, y: 0 } },
    ],
    edges: [
      { id: "e1", source: { node: "src", port: "frames" }, target: { node: "p2d", port: "frames" } },
    ],
  };

  it("renders My Presets section when custom presets exist", () => {
    const record = saveCustomPreset("My Flow", "Custom desc", smallGraph);
    render(<SimpleMode />);
    expect(screen.getByTestId("simple-mode-custom-title")).toBeInTheDocument();
    expect(screen.getByTestId(`preset-custom-${record.id}`)).toBeInTheDocument();
  });

  it("does not render My Presets when none exist", () => {
    render(<SimpleMode />);
    expect(screen.queryByTestId("simple-mode-custom-title")).not.toBeInTheDocument();
  });

  it("clicking a custom preset merges its graph and switches to advanced", () => {
    const record = saveCustomPreset("My Flow", "Custom desc", smallGraph);
    render(<SimpleMode />);

    fireEvent.click(screen.getByTestId(`preset-custom-${record.id}`));

    const { nodes, edges } = useFlowStore.getState();
    expect(nodes.map((n) => n.data.schema.type)).toEqual(["video-source", "pose-2d"]);
    expect(edges).toHaveLength(1);
    expect(useUiStore.getState().mode).toBe("advanced");
  });

  it("delete removes the custom preset card", () => {
    const record = saveCustomPreset("My Flow", "Custom desc", smallGraph);
    render(<SimpleMode />);
    expect(screen.getByTestId(`preset-custom-${record.id}`)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId(`preset-custom-delete-${record.id}`));
    expect(screen.queryByTestId(`preset-custom-${record.id}`)).not.toBeInTheDocument();
    expect(loadCustomPresets()).toHaveLength(0);
  });
});
