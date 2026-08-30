import { ConnectionBanner } from "../components/shell/ConnectionBanner";
import { useHealthCheck } from "../state/useHealthCheck";

export function App() {
  const { retry } = useHealthCheck();
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <ConnectionBanner onRetry={retry} />
      <header style={{ padding: "12px 16px", borderBottom: "1px solid #ddd" }}>
        <h1 style={{ margin: 0, fontSize: "20px" }}>AImation Flow</h1>
      </header>
      <main style={{ flex: 1, padding: "16px" }}>
        <p>Editor coming soon.</p>
      </main>
    </div>
  );
}
