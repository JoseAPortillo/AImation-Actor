/**
 * Run/Stop job controls (GE-1..3).
 *
 * Validates the current graph (blocking Run and naming any missing required
 * param — GE-3), submits the canonical `.aimgraph` to the job store (GE-1),
 * exposes Stop → cancel (GE-2), and renders the terminal status, error, logs,
 * and results panels.
 */

import { useJobStore } from "../../state/useJobStore";
import { validateRunReadiness } from "../../state/useJobStore";
import { useFlowStore } from "../../state/useFlowStore";
import { fromFlow } from "../../core/serialize";
import { extractMotion } from "../../core/motionView";
import { MotionViewer } from "../motion/MotionViewer";
import { downloadTextFile, motionExportPayloads } from "../../core/export";

export interface RunControlsProps {
  /** Error surface for non-job failures (HTTP-3). */
  onError: (message: string) => void;
}

export function RunControls({ onError }: RunControlsProps) {
  const status = useJobStore((s) => s.status);
  const error = useJobStore((s) => s.error);
  const logs = useJobStore((s) => s.logs);
  const result = useJobStore((s) => s.result);
  const submit = useJobStore((s) => s.submit);
  const cancel = useJobStore((s) => s.cancel);

  // Subscribe to store changes so component re-renders when nodes/edges change
  const nodes = useFlowStore((s) => s.nodes);
  const edges = useFlowStore((s) => s.edges);
  const readiness = validateRunReadiness(nodes);
  const busy = status === "queued" || status === "running";
  const motion = extractMotion(result);

  async function handleRun() {
    try {
      await submit(fromFlow(nodes, edges));
    } catch (err) {
      onError(err instanceof Error ? err.message : "failed to run");
    }
  }

  return (
    <div data-testid="run-controls" style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <button
        type="button"
        data-testid="run-button"
        disabled={!readiness.ready || busy}
        onClick={() => void handleRun()}
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
        Run
      </button>
      {busy && (
        <button
          type="button"
          data-testid="stop-button"
          onClick={() => void cancel()}
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
          Stop
        </button>
      )}
      {!readiness.ready && (
        <span data-testid="run-block-reason" style={{ color: "#f87171", fontSize: 12 }}>
          Missing required: {readiness.missing.join(", ")}
        </span>
      )}
      {status === "running" && (
        <span
          data-testid="job-status-processing"
          style={{ fontSize: 12, color: "#fbbf24", fontWeight: 600 }}
        >
          Processing… — use Stop to cancel
        </span>
      )}
      {status !== "idle" && status !== "running" && (
        <span data-testid="job-status" style={{ fontSize: 12, color: "#e0e0e0" }}>
          {status}
        </span>
      )}
      {error && (
        <span data-testid="job-error" style={{ color: "#f87171", fontSize: 12 }}>
          {error}
        </span>
      )}
      {logs.length > 0 && (
        <div data-testid="job-logs" style={{ fontSize: 12, color: "#ccc" }}>
          {logs.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
      )}
      {result && (
        <>
          {status === "succeeded" && motion !== null && (
            <div
              data-testid="job-result-viewer"
              style={{
                background: "#1a1a1a",
                border: "1px solid #333",
                borderRadius: 8,
                padding: 12,
              }}
            >
              <h3 style={{ margin: "0 0 12px", fontSize: 15, color: "#e0e0e0" }}>
                Result
              </h3>
              <MotionViewer motion={motion} />
              <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                <button
                  type="button"
                  data-testid="export-bvh"
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
                  data-testid="export-json"
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
              <details data-testid="job-result-raw">
                <summary style={{ fontSize: 13, color: "#9ca3af", cursor: "pointer" }}>
                  Raw JSON
                </summary>
                <pre
                  data-testid="job-result"
                  style={{
                    fontSize: 12,
                    maxHeight: 120,
                    overflow: "auto",
                    background: "#2a2a2a",
                    color: "#e0e0e0",
                    border: "1px solid #444",
                    borderRadius: 4,
                    padding: "4px 8px",
                  }}
                >
                  {JSON.stringify(result, null, 2)}
                </pre>
              </details>
            </div>
          )}
          {motion === null && (
            <pre
              data-testid="job-result"
              style={{
                fontSize: 12,
                maxHeight: 120,
                overflow: "auto",
                background: "#2a2a2a",
                color: "#e0e0e0",
                border: "1px solid #444",
                borderRadius: 4,
                padding: "4px 8px",
              }}
            >
              {JSON.stringify(result, null, 2)}
            </pre>
          )}
        </>
      )}
    </div>
  );
}
