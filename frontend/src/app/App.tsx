import { useEffect } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { ApiClient } from "../api/ApiClient";
import { ConnectionBanner } from "../components/shell/ConnectionBanner";
import { Palette } from "../components/palette/Palette";
import { FlowCanvas } from "../components/canvas/FlowCanvas";
import { GraphIO } from "../components/graphio/GraphIO";
import { PropertiesPanel } from "../components/properties/PropertiesPanel";
import { RunControls } from "../components/job/RunControls";
import { SimpleMode } from "../components/simple/SimpleMode";
import { useHealthCheck } from "../state/useHealthCheck";
import { usePaletteStore } from "../state/usePaletteStore";
import { useUiStore } from "../state/useUiStore";

export function App() {
  const { retry } = useHealthCheck();
  const setBanner = useUiStore((s) => s.setBanner);
  const mode = useUiStore((s) => s.mode);
  const setMode = useUiStore((s) => s.setMode);

  // Load the node catalog once, up front, so Simple Mode presets can resolve
  // schemas even though the palette (the other consumer) is only mounted in
  // Advanced mode. Mounted at the app root => always available.
  useEffect(() => {
    const { status, fetch } = usePaletteStore.getState();
    if (status === "idle") void fetch(new ApiClient());
  }, []);

  return (
    <ReactFlowProvider>
      <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "#121212" }}>
      <ConnectionBanner onRetry={retry} />
      <header
        style={{
          padding: "12px 16px",
          borderBottom: "1px solid #333",
          background: "#1a1a1a",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <h1 style={{ margin: 0, fontSize: "20px", color: "#e0e0e0" }}>AImation Flow</h1>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <div
            data-testid="mode-toggle"
            style={{
              display: "flex",
              background: "#121212",
              border: "1px solid #444",
              borderRadius: 6,
              overflow: "hidden",
            }}
          >
            <button
              type="button"
              data-testid="mode-simple"
              onClick={() => setMode("simple")}
              style={{
                cursor: "pointer",
                padding: "4px 12px",
                fontSize: 12,
                border: "none",
                background: mode === "simple" ? "#2a6f4f" : "transparent",
                color: mode === "simple" ? "#fff" : "#9ca3af",
              }}
            >
              Simple
            </button>
            <button
              type="button"
              data-testid="mode-advanced"
              onClick={() => setMode("advanced")}
              style={{
                cursor: "pointer",
                padding: "4px 12px",
                fontSize: 12,
                border: "none",
                background: mode === "advanced" ? "#2a6f4f" : "transparent",
                color: mode === "advanced" ? "#fff" : "#9ca3af",
              }}
            >
              Advanced
            </button>
          </div>
          <GraphIO catalog={() => usePaletteStore.getState().catalog} />
        </div>
      </header>
      <main style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {mode === "simple" ? (
          <section style={{ flex: 1, position: "relative" }}>
            <SimpleMode />
          </section>
        ) : (
          <>
            <aside
              style={{ width: "220px", borderRight: "1px solid #333", background: "#1a1a1a", padding: "12px", overflow: "auto" }}
            >
              <Palette />
            </aside>
            <section style={{ flex: 1, position: "relative" }}>
              <div
                data-testid="canvas-host"
                style={{ position: "absolute", inset: 0, background: "#121212" }}
              >
                <FlowCanvas />
              </div>
            </section>
            <aside
              data-testid="properties-host"
              style={{ width: "300px", borderLeft: "1px solid #333", background: "#1a1a1a", padding: "12px", overflow: "auto" }}
            >
              <PropertiesPanel />
            </aside>
          </>
        )}
      </main>
      <footer style={{ padding: "10px 16px", borderTop: "1px solid #333", background: "#1a1a1a" }}>
        <RunControls
          onError={(msg) => setBanner(msg)}
        />
      </footer>
      </div>
    </ReactFlowProvider>
  );
}
