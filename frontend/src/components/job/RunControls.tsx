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
import { fromFlow } from "../../core/serialize";
import type { FlowNode } from "../../state/useFlowStore";
import type { Edge } from "@xyflow/react";

export interface RunControlsProps {
  /** Current canvas nodes (injected so the component stays testable). */
  getNodes: () => FlowNode[];
  /** Current canvas edges. */
  getEdges?: () => Edge[];
  /** Error surface for non-job failures (HTTP-3). */
  onError: (message: string) => void;
}

export function RunControls({ getNodes, getEdges, onError }: RunControlsProps) {
  const status = useJobStore((s) => s.status);
  const error = useJobStore((s) => s.error);
  const logs = useJobStore((s) => s.logs);
  const result = useJobStore((s) => s.result);
  const submit = useJobStore((s) => s.submit);
  const cancel = useJobStore((s) => s.cancel);

  const nodes = getNodes();
  const readiness = validateRunReadiness(nodes);
  const busy = status === "queued" || status === "running";

  async function handleRun() {
    const edges = getEdges?.() ?? [];
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
        style={{ fontSize: 12, padding: "4px 10px", cursor: "pointer" }}
      >
        Run
      </button>
      {busy && (
        <button
          type="button"
          data-testid="stop-button"
          onClick={() => void cancel()}
          style={{ fontSize: 12, padding: "4px 10px", cursor: "pointer" }}
        >
          Stop
        </button>
      )}
      {!readiness.ready && (
        <span data-testid="run-block-reason" style={{ color: "#b33", fontSize: 12 }}>
          Missing required: {readiness.missing.join(", ")}
        </span>
      )}
      {status !== "idle" && (
        <span data-testid="job-status" style={{ fontSize: 12 }}>
          {status}
        </span>
      )}
      {error && (
        <span data-testid="job-error" style={{ color: "#b33", fontSize: 12 }}>
          {error}
        </span>
      )}
      {logs.length > 0 && (
        <div data-testid="job-logs" style={{ fontSize: 12 }}>
          {logs.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
      )}
      {result && (
        <pre data-testid="job-result" style={{ fontSize: 12, maxHeight: 120, overflow: "auto" }}>
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  );
}
