import { useEffect, useState } from "react";
import { ApiClient } from "../../api/ApiClient";
import type { NodeCategory, NodeSchema } from "../../api/types";
import { usePaletteStore } from "../../state/usePaletteStore";
import { useFlowStore } from "../../state/useFlowStore";

const CATEGORY_ORDER: NodeCategory[] = [
  "source",
  "ai",
  "cleanup",
  "enrichment",
  "rigging",
  "output",
  "logic",
];

const CATEGORY_LABEL: Record<NodeCategory, string> = {
  source: "Sources",
  ai: "AI",
  cleanup: "Cleanup",
  enrichment: "Enrichment",
  rigging: "Rigging",
  output: "Output",
  logic: "Logic",
};

/**
 * Live schema-driven palette (NP-1, NP-2). Node types come from
 * `GET /nodes/types` at runtime (never hardcoded) and are grouped by category.
 * Clicking an entry adds an instance to the canvas. A search box filters the
 * catalog case-insensitively by title/type/description. Fetch failures surface
 * a retryable error state, and `retry` re-fetches without a reload.
 */
export function Palette({ client = new ApiClient() }: { client?: ApiClient }) {
  const catalog = usePaletteStore((s) => s.catalog);
  const status = usePaletteStore((s) => s.status);
  const error = usePaletteStore((s) => s.error);
  const fetchCatalog = usePaletteStore((s) => s.fetch);
  const retry = usePaletteStore((s) => s.retry);
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (status === "idle") {
      void fetchCatalog(client);
    }
  }, [status, fetchCatalog, client]);

  const needle = query.trim().toLowerCase();
  const visible = needle
    ? catalog.filter(
        (n) =>
          n.title.toLowerCase().includes(needle) ||
          n.type.toLowerCase().includes(needle) ||
          (n.description ?? "").toLowerCase().includes(needle),
      )
    : catalog;

  const grouped = CATEGORY_ORDER.map((category) => ({
    category,
    nodes: visible.filter((n) => n.category === category),
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
      <input
        data-testid="palette-search"
        type="search"
        placeholder="Search nodes…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Search nodes"
        style={{
          width: "100%",
          boxSizing: "border-box",
          marginBottom: 8,
          padding: "5px 8px",
          background: "#121212",
          color: "#ccc",
          border: "1px solid #444",
          borderRadius: 4,
          fontSize: 12,
          outline: "none",
        }}
      />
      {grouped.map((group) => (
        <section key={group.category}>
          <h3 style={{ fontSize: "12px", textTransform: "uppercase", margin: "8px 0 4px", color: "#999" }}>
            {CATEGORY_LABEL[group.category]}
          </h3>
          {group.nodes.map((node) => (
            <button
              key={node.type}
              type="button"
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData("application/reactflow", node.type);
                e.dataTransfer.effectAllowed = "move";
              }}
              onDragEnd={(e) => {
                e.dataTransfer.clearData();
              }}
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
      {needle && grouped.length === 0 ? (
        <p data-testid="palette-no-results" style={{ fontSize: 12, color: "#9ca3af", marginTop: 4 }}>
          No nodes match “{query.trim()}”.
        </p>
      ) : null}
    </div>
  );
}
