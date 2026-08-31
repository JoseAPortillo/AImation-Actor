import { ConnectionBanner } from "../components/shell/ConnectionBanner";
import { Palette } from "../components/palette/Palette";
import { FlowCanvas } from "../components/canvas/FlowCanvas";
import { useHealthCheck } from "../state/useHealthCheck";

export function App() {
  const { retry } = useHealthCheck();
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <ConnectionBanner onRetry={retry} />
      <header style={{ padding: "12px 16px", borderBottom: "1px solid #ddd" }}>
        <h1 style={{ margin: 0, fontSize: "20px" }}>AImation Flow</h1>
      </header>
      <main style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <aside
          style={{ width: "220px", borderRight: "1px solid #ddd", padding: "12px", overflow: "auto" }}
        >
          <Palette />
        </aside>
        <section style={{ flex: 1, position: "relative" }}>
          <div
            data-testid="canvas-host"
            style={{ position: "absolute", inset: 0, background: "#f5f5f5" }}
          >
            <FlowCanvas />
          </div>
        </section>
      </main>
    </div>
  );
}
