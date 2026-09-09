import { useEffect, useRef, useState } from "react";
import { useFlowStore } from "../../state/useFlowStore";
import type { NodeSchema } from "../../api/types";
import { serializeGraph, parseGraph, fromFlow, mergeGraphIntoFlow } from "../../core/serialize";
import { saveCustomPreset } from "../../core/presets";

/** Supplies the node schema catalog used to resolve loaded node types. */
export type CatalogProvider = () => NodeSchema[];

/**
 * Save/Load graph I/O toolbar (AR-1, AR-2).
 *
 * Save serializes the current flow store to canonical `.aimgraph` v1.0 bytes
 * and triggers a browser download. Load reads a `.aimgraph` file, validates the
 * version (rejecting unsupported versions WITHOUT mutating the canvas), then
 * merges the nodes/edges into the store by id (existing nodes keep their
 * runtime params, new nodes are appended, layout extras applied).
 */
export function GraphIO({ catalog }: { catalog: CatalogProvider }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [showPresetForm, setShowPresetForm] = useState(false);
  const [presetTitle, setPresetTitle] = useState("");
  const [presetSaved, setPresetSaved] = useState<string | null>(null);

  // Clean up the transient confirmation on unmount
  useEffect(() => {
    if (!presetSaved) return;
    const timer = setTimeout(() => setPresetSaved(null), 2000);
    return () => clearTimeout(timer);
  }, [presetSaved]);

  function handleSave() {
    const { nodes, edges } = useFlowStore.getState();
    const bytes = serializeGraph(fromFlow(nodes, edges));
    const blob = new Blob([bytes], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "graph.aimgraph.json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setError(null);
  }

  async function handleLoad(file: File) {
    setError(null);
    let text: string;
    try {
      text = await file.text();
    } catch {
      setError("Could not read the selected file.");
      return;
    }
    const result = parseGraph(text);
    if (!result.ok) {
      // Rejected: never mutate the canvas (AR-2 s3).
      setError(result.error ?? "Invalid graph file.");
      return;
    }
    mergeGraphIntoFlow(result.graph!, catalog());
    if (fileInput.current) fileInput.current.value = "";
  }

  function handleSavePreset() {
    const { nodes, edges } = useFlowStore.getState();
    if (nodes.length === 0) {
      setError("Cannot save an empty canvas as a preset.");
      return;
    }
    const graph = fromFlow(nodes, edges);
    const record = saveCustomPreset(presetTitle.trim(), "Custom preset", graph);
    setPresetTitle("");
    setShowPresetForm(false);
    setPresetSaved(`Saved preset "${record.title}"`);
  }

  return (
    <div data-testid="graphio" style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <button
        type="button"
        data-testid="graphio-save"
        onClick={handleSave}
        style={{
          fontSize: 12,
          padding: "4px 10px",
          cursor: "pointer",
          background: "#2a2a2a",
          color: "#ccc",
          border: "1px solid #444",
          borderRadius: 4,
        }}
      >
        Save
      </button>
      <label
        data-testid="graphio-load-label"
        style={{
          fontSize: 12,
          padding: "4px 10px",
          cursor: "pointer",
          border: "1px solid #444",
          borderRadius: 4,
          background: "#2a2a2a",
          color: "#ccc",
        }}
      >
        Load
        <input
          ref={fileInput}
          data-testid="graphio-load"
          type="file"
          accept=".json,application/json"
          style={{ display: "none" }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void handleLoad(file);
          }}
        />
      </label>
      <button
        type="button"
        data-testid="graphio-save-preset"
        onClick={() => { setShowPresetForm((v) => !v); setError(null); }}
        style={{
          fontSize: 12,
          padding: "4px 10px",
          cursor: "pointer",
          background: "#2a2a2a",
          color: "#ccc",
          border: "1px solid #444",
          borderRadius: 4,
        }}
      >
        Save Preset
      </button>
      {showPresetForm && (
        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          <input
            data-testid="graphio-preset-title"
            type="text"
            placeholder="Preset name…"
            value={presetTitle}
            onChange={(e) => setPresetTitle(e.target.value)}
            style={{
              fontSize: 12,
              padding: "4px 8px",
              border: "1px solid #444",
              borderRadius: 4,
              background: "#1a1a1a",
              color: "#e0e0e0",
              outline: "none",
            }}
          />
          <button
            type="button"
            data-testid="graphio-preset-confirm"
            onClick={handleSavePreset}
            style={{
              fontSize: 12,
              padding: "4px 10px",
              cursor: "pointer",
              background: "#2a2a2a",
              color: "#ccc",
              border: "1px solid #444",
              borderRadius: 4,
            }}
          >
            ✓
          </button>
          <button
            type="button"
            data-testid="graphio-preset-cancel"
            onClick={() => { setShowPresetForm(false); setPresetTitle(""); setError(null); }}
            style={{
              fontSize: 12,
              padding: "4px 10px",
              cursor: "pointer",
              background: "#2a2a2a",
              color: "#ccc",
              border: "1px solid #444",
              borderRadius: 4,
            }}
          >
            ✕
          </button>
        </div>
      )}
      {presetSaved && (
        <span data-testid="graphio-preset-saved" style={{ color: "#4ade80", fontSize: 12 }}>
          {presetSaved}
        </span>
      )}
      {error && (
        <span data-testid="graphio-error" style={{ color: "#f87171", fontSize: 12 }}>
          {error}
        </span>
      )}
    </div>
  );
}
