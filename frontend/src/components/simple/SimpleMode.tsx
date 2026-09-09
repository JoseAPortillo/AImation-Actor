import { useState } from "react";
import { usePaletteStore } from "../../state/usePaletteStore";
import { useUiStore } from "../../state/useUiStore";
import { useJobStore } from "../../state/useJobStore";
import { mergeGraphIntoFlow } from "../../core/serialize";
import { presets, loadCustomPresets, deleteCustomPreset } from "../../core/presets";
import { extractMotion } from "../../core/motionView";
import { MotionViewer } from "../motion/MotionViewer";
import { downloadTextFile, motionExportPayloads } from "../../core/export";

/**
 * Simple Mode (AR-3): a curated, no-node-editor entry point.
 *
 * Presents ready-made flows as cards.  Picking one merges its canonical graph
 * into the canvas in place (by stable node id), so re-picking the same preset
 * updates layout/params instead of stacking duplicates.
 *
 * The canvas stays the single source of truth — Simple Mode is a launcher, not
 * a parallel editor, so Advanced mode sees exactly the same graph.
 */
export function SimpleMode() {
  const catalog = usePaletteStore((s) => s.catalog);
  const status = usePaletteStore((s) => s.status);
  const setMode = useUiStore((s) => s.setMode);
  const jobStatus = useJobStore((s) => s.status);
  const jobResult = useJobStore((s) => s.result);
  const [, setRefresh] = useState(0);

  const motion = extractMotion(jobResult);
  const showResult = jobStatus === "succeeded" && motion !== null;
  const customPresets = loadCustomPresets();

  function handlePick(id: string) {
    const preset =
      presets().find((p) => p.id === id) ??
      loadCustomPresets().find((p) => p.id === id);
    if (!preset) return;
    if (catalog.length === 0) return; // not ready yet
    mergeGraphIntoFlow(preset.graph, catalog);
    setMode("advanced");
  }

  function handleDeleteCustom(id: string) {
    deleteCustomPreset(id);
    setRefresh((n) => n + 1);
  }

  return (
    <div
      data-testid="simple-mode"
      style={{
        height: "100%",
        overflow: "auto",
        padding: "24px 20px",
        background: "#121212",
      }}
    >
      <h2
        data-testid="simple-mode-title"
        style={{ margin: "0 0 6px", fontSize: 18, color: "#e0e0e0" }}
      >
        Choose a flow to start
      </h2>
      <p style={{ margin: "0 0 20px", fontSize: 13, color: "#9ca3af" }}>
        Pick a ready-made pipeline. It loads into the canvas already wired up —
        set your input and run.
      </p>

      {showResult && motion !== null && (
        <div
          data-testid="simple-mode-result"
          style={{
            marginBottom: 20,
            padding: "16px",
            background: "#1a1a1a",
            border: "1px solid #333",
            borderRadius: 8,
          }}
        >
          <h3 style={{ margin: "0 0 12px", fontSize: 15, color: "#e0e0e0" }}>
            Result
          </h3>
          <MotionViewer motion={motion} />
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button
              type="button"
              data-testid="simple-mode-export-bvh"
              onClick={() => {
                const payloads = motionExportPayloads(motion);
                downloadTextFile(payloads.bvh.filename, payloads.bvh.content, payloads.bvh.mimeType);
              }}
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
              Export BVH
            </button>
            <button
              type="button"
              data-testid="simple-mode-export-json"
              onClick={() => {
                const payloads = motionExportPayloads(motion);
                downloadTextFile(payloads.json.filename, payloads.json.content, payloads.json.mimeType);
              }}
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
              Export JSON
            </button>
          </div>
        </div>
      )}

      {status === "loading" || catalog.length === 0 ? (
        <p data-testid="simple-mode-loading" style={{ color: "#9ca3af", fontSize: 13 }}>
          Loading flow catalog…
        </p>
      ) : (
        <div
          data-testid="simple-mode-grid"
          style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 12 }}
        >
          {presets().map((p) => (
            <button
              key={p.id}
              type="button"
              data-testid={`preset-${p.id}`}
              onClick={() => handlePick(p.id)}
              style={{
                textAlign: "left",
                display: "flex",
                flexDirection: "column",
                gap: 6,
                padding: "14px 16px",
                cursor: "pointer",
                background: "#1a1a1a",
                border: "1px solid #333",
                borderRadius: 8,
                color: "#e0e0e0",
              }}
            >
              <span style={{ fontSize: 15, fontWeight: 600 }}>{p.title}</span>
              <span style={{ fontSize: 12, color: "#9ca3af" }}>{p.description}</span>
            </button>
          ))}
        </div>
      )}

      {customPresets.length > 0 && (
        <>
          <h2
            data-testid="simple-mode-custom-title"
            style={{ margin: "24px 0 6px", fontSize: 18, color: "#e0e0e0" }}
          >
            My Presets
          </h2>
          <div
            data-testid="simple-mode-custom-grid"
            style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 12 }}
          >
            {customPresets.map((p) => (
              <button
                key={p.id}
                type="button"
                data-testid={`preset-custom-${p.id}`}
                onClick={() => handlePick(p.id)}
                style={{
                  textAlign: "left",
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                  padding: "14px 16px",
                  cursor: "pointer",
                  background: "#1a1a1a",
                  border: "1px solid #333",
                  borderRadius: 8,
                  color: "#e0e0e0",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: 15, fontWeight: 600 }}>{p.title}</span>
                  <span
                    role="button"
                    data-testid={`preset-custom-delete-${p.id}`}
                    aria-label="Delete preset"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteCustom(p.id);
                    }}
                    style={{
                      fontSize: 14,
                      padding: "2px 6px",
                      cursor: "pointer",
                      color: "#9ca3af",
                      borderRadius: 4,
                      border: "1px solid #444",
                      background: "transparent",
                    }}
                  >
                    ×
                  </span>
                </div>
                <span style={{ fontSize: 12, color: "#9ca3af" }}>{p.description}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
