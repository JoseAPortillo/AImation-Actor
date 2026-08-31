import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { TEST_BASE } from "../../test/handlers/nodeCatalog";
import { Palette } from "./Palette";
import { usePaletteStore } from "../../state/usePaletteStore";
import { useFlowStore } from "../../state/useFlowStore";

// Force the store from any prior test-outcome noise into a clean idle state.
beforeEach(() => {
  usePaletteStore.setState({ catalog: [], status: "idle", error: null });
  useFlowStore.setState({ nodes: [], edges: [] });
});

describe("Palette (NP-1, NP-2)", () => {
  it("renders the 7 real node types grouped under their categories (NP-1)", async () => {
    render(<Palette />);
    // Wait for the catalog to load via MSW.
    expect(await screen.findByTestId("palette")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("Sources")).toBeInTheDocument(),
    );

    // All 7 nodes appear.
    expect(screen.getByText("Frame Extractor")).toBeInTheDocument();
    expect(screen.getByText("Frame Range")).toBeInTheDocument();
    expect(screen.getByText("Pass Through")).toBeInTheDocument();
    expect(screen.getByText("Merge")).toBeInTheDocument();
    expect(screen.getByText("Pose 2D")).toBeInTheDocument();
    expect(screen.getByText("Pose 3D")).toBeInTheDocument();
    expect(screen.getByText("Video to Motion")).toBeInTheDocument();

    // Categories present.
    expect(screen.getByText("AI")).toBeInTheDocument();
    expect(screen.getByText("Output")).toBeInTheDocument();
    expect(screen.getByText("Logic")).toBeInTheDocument();
  });

  it("clicking a palette entry adds a node of that type to the canvas (NP-2)", async () => {
    render(<Palette />);
    await screen.findByText("Frame Extractor");
    fireEvent.click(screen.getByRole("button", { name: "Add Frame Extractor" }));

    const nodes = useFlowStore.getState().nodes;
    expect(nodes).toHaveLength(1);
    expect(nodes[0].data.schema.type).toBe("video-source");
    expect(nodes[0].id.startsWith("video-source_")).toBe(true);
  });

  it("on failure shows a retryable error and retry re-fetches without reload (NP-1 s2)", async () => {
    server.use(
      http.get(`${TEST_BASE}/nodes/types`, () =>
        HttpResponse.json({ detail: "Not authenticated" }, { status: 401 }),
      ),
    );
    render(<Palette />);
    expect(await screen.findByTestId("palette-error")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();

    // Restore the happy-path handler (resets to the fixture) then click Retry.
    server.resetHandlers();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByTestId("palette")).toBeInTheDocument();
  });
});
