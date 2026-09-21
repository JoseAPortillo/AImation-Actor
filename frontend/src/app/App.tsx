import { useEffect } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { ApiClient } from "../api/ApiClient";
import { ConnectionBanner } from "../components/shell/ConnectionBanner";
import { Wizard } from "../components/wizard/Wizard";
import { FlowCanvas } from "../components/canvas/FlowCanvas";
import { GraphIO } from "../components/graphio/GraphIO";
import { useHealthCheck } from "../state/useHealthCheck";
import { usePaletteStore } from "../state/usePaletteStore";
import { useUiStore } from "../state/useUiStore";

export function App() {
  const { retry } = useHealthCheck();
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
      <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "#0a0a0a" }}>
      <ConnectionBanner onRetry={retry} />
      <header
        style={{
          padding: "12px 16px",
          borderBottom: "1px solid #1f2937",
          background: "#111827",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <h1 style={{ margin: 0, fontSize: "18px", color: "#f9fafb", fontWeight: 600 }}>
          AImation Actor
        </h1>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <div
            data-testid="mode-toggle"
            style={{
              display: "flex",
              background: "#0a0a0a",
              border: "1px solid #374151",
              borderRadius: 6,
              overflow: "hidden",
            }}
          >
            <button
              type="button"
              data-testid="mode-wizard"
              onClick={() => setMode("simple")}
              style={{
                cursor: "pointer",
                padding: "6px 14px",
                fontSize: 12,
                border: "none",
                background: mode === "simple" ? "#2563eb" : "transparent",
                color: mode === "simple" ? "#fff" : "#9ca3af",
                fontWeight: mode === "simple" ? 500 : 400,
              }}
            >
              🧙 Asistente
            </button>
            <button
              type="button"
              data-testid="mode-advanced"
              onClick={() => setMode("advanced")}
              style={{
                cursor: "pointer",
                padding: "6px 14px",
                fontSize: 12,
                border: "none",
                background: mode === "advanced" ? "#7c3aed" : "transparent",
                color: mode === "advanced" ? "#fff" : "#9ca3af",
                fontWeight: mode === "advanced" ? 500 : 400,
              }}
            >
              🔧 Avanzado
            </button>
          </div>
          {mode === "advanced" && <GraphIO catalog={() => usePaletteStore.getState().catalog} />}
        </div>
      </header>
      <main style={{ flex: 1, display: "flex", minHeight: 0, overflow: "hidden" }}>
        {mode === "simple" ? (
          <section style={{ flex: 1, overflow: "auto" }}>
            <Wizard />
          </section>
        ) : (
          <>
            <aside
              style={{ width: "220px", borderRight: "1px solid #1f2937", background: "#111827", padding: "12px", overflow: "auto" }}
            >
              {/* Palette placeholder for advanced mode */}
              <div style={{ color: "#6b7280", fontSize: 12, textAlign: "center", paddingTop: 20 }}>
                Modo avanzado — nodos disponibles próximamente
              </div>
            </aside>
            <section style={{ flex: 1, position: "relative" }}>
              <div
                data-testid="canvas-host"
                style={{ position: "absolute", inset: 0, background: "#0a0a0a" }}
              >
                <FlowCanvas />
              </div>
            </section>
          </>
        )}
      </main>
      </div>
    </ReactFlowProvider>
  );
}
