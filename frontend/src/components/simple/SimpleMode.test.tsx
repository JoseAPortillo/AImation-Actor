import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SimpleMode } from "./SimpleMode";
import { usePaletteStore } from "../../state/usePaletteStore";
import { useFlowStore } from "../../state/useFlowStore";
import { useUiStore } from "../../state/useUiStore";
import nodeCatalogFixture from "../../test/fixtures/nodeCatalog.json";

beforeEach(() => {
  usePaletteStore.setState({
    catalog: nodeCatalogFixture as never,
    status: "ready",
    error: null,
  });
  useFlowStore.setState({ nodes: [], edges: [] });
  useUiStore.setState({ mode: "simple" });
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
});
