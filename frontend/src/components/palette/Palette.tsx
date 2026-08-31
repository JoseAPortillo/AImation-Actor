import { useEffect } from "react";
import { ApiClient } from "../../api/ApiClient";
import type { NodeCategory, NodeSchema } from "../../api/types";
import { usePaletteStore } from "../../state/usePaletteStore";
import { useFlowStore } from "../../state/useFlowStore";

const CATEGORY_ORDER: NodeCategory[] = [
  "source",
  "ai",
  "cleanup",
  "rigging",
  "output",
  "logic",
];

const CATEGORY_LABEL: Record<NodeCategory, string> = {
  source: "Sources",
  ai: "AI",
  cleanup: "Cleanup",
  rigging: "Rigging",
  output: "Output",
  logic: "Logic",
};

/**
 * Live schema-driven palette (NP-1, NP-2). Node types come from
 * `GET /nodes/types` at runtime (never hardcoded) and are grouped by category.
 * Clicking an entry adds an instance to the canvas. Fetch failures surface a
 * retryable error state, and `retry` re-fetches without a reload.
 */
export function Palette({ client = new ApiClient() }: { client?: ApiClient }) {
  const catalog = usePaletteStore((s) => s.catalog);
  const status = usePaletteStore((s) => s.status);
  const error = usePaletteStore((s) => s.error);
  const fetchCatalog = usePaletteStore((s) => s.fetch);
  const retry = usePaletteStore((s) => s.retry);

  useEffect(() => {
    if (status === "idle") {
      void fetchCatalog(client);
    }
  }, [status, fetchCatalog, client]);

  const grouped = CATEGORY_ORDER.map((category) => ({
    category,
    nodes: catalog.filter((n) => n.category === category),
  })).filter((g) => g.nodes.length > 0);

  function handleAdd(schema: NodeSchema) {
    useFlowStore.getState().addNode(schema);
  }

  if (status === "loading") {
    return <div data-testid="palette-loading" style={{ color: "#999" }}>Loading node palette…</div>;
  }

  if (status === "error") {
    return (
      <div data-testid="palette-error">
        <p style={{ color: "#f87171" }}>Could not load node catalog: {error}</p>
        <button type="button" onClick={() => void retry(client)}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div data-testid="palette">
      <h2 style={{ fontSize: "14px", margin: "0 0 8px", color: "#e0e0e0" }}>Nodes</h2>
      {grouped.map((group) => (
        <section key={group.category}>
          <h3 style={{ fontSize: "12px", textTransform: "uppercase", margin: "8px 0 4px", color: "#999" }}>
            {CATEGORY_LABEL[group.category]}
          </h3>
          {group.nodes.map((node) => (
            <button
              key={node.type}
              type="button"
              onClick={() => handleAdd(node)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                margin: "2px 0",
                background: "#2a2a2a",
                color: "#ccc",
                border: "1px solid #444",
                borderRadius: 4,
                padding: "4px 8px",
                cursor: "pointer",
              }}
              aria-label={`Add ${node.title}`}
            >
              {node.title}
            </button>
          ))}
        </section>
      ))}
    </div>
  );
}
