import { ConnectionBanner } from "../components/shell/ConnectionBanner";
import { Palette } from "../components/palette/Palette";
import { FlowCanvas } from "../components/canvas/FlowCanvas";
import { GraphIO } from "../components/graphio/GraphIO";
import { RunControls } from "../components/job/RunControls";
import { useHealthCheck } from "../state/useHealthCheck";
import { usePaletteStore } from "../state/usePaletteStore";
import { useFlowStore } from "../state/useFlowStore";
import { useUiStore } from "../state/useUiStore";

export function App() {
  const { retry } = useHealthCheck();
  const setBanner = useUiStore((s) => s.setBanner);
  return (
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
        <GraphIO catalog={() => usePaletteStore.getState().catalog} />
      </header>
      <main style={{ flex: 1, display: "flex", minHeight: 0 }}>
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
      </main>
      <footer style={{ padding: "10px 16px", borderTop: "1px solid #333", background: "#1a1a1a" }}>
        <RunControls
          getNodes={() => useFlowStore.getState().nodes}
          getEdges={() => useFlowStore.getState().edges}
          onError={(msg) => setBanner(msg)}
        />
      </footer>
    </div>
  );
}
