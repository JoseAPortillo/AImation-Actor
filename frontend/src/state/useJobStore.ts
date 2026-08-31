/**
 * Job initiation store (GE-1..3): submits the current graph, polls the job to
 * a terminal state, and records logs + result. All actions are reducers;
 * network access goes through an injectable `ApiClient` so the store is
 * unit-testable without a live backend.
 */

import { create } from "zustand";
import { ApiClient, DEFAULT_URL } from "../api/ApiClient";
import type { JobStatus } from "../api/types";
import type { AimGraph } from "../core/graph";
import type { FlowNode } from "./useFlowStore";

/** Frontend-facing job lifecycle (adds `idle` before any submission). */
export type JobRunStatus = "idle" | JobStatus;

export const POLL_INTERVAL_MS = 800;
export const MAX_POLLS = 60;

export interface RunReadiness {
  ready: boolean;
  /** Names of required params (no default) that are missing from the graph. */
  missing: string[];
}

/**
 * GE-3: a run is blocked when any node is missing a required param that has no
 * default value. Params with a non-null default are never blocking (the default
 * applies). Also blocks an empty graph.
 */
export function validateRunReadiness(nodes: FlowNode[]): RunReadiness {
  if (nodes.length === 0) return { ready: false, missing: ["(empty graph)"] };
  const missing: string[] = [];
  for (const node of nodes) {
    for (const param of node.data.schema.params) {
      if (param.required && param.default === null) {
        const value = node.data.params[param.name];
        if (value === undefined || value === null || value === "") {
          missing.push(`${node.id}:${param.name}`);
        }
      }
    }
  }
  return { ready: missing.length === 0, missing };
}

interface JobState {
  jobId: string | null;
  status: JobRunStatus;
  error: string | null;
  logs: string[];
  result: Record<string, unknown> | null;
  /** Injectable for tests; defaults to a real client over the base URL. */
  api: ApiClient;
  submit: (graph: AimGraph) => Promise<void>;
  cancel: () => Promise<void>;
  reset: () => void;
}

let pollTimer: ReturnType<typeof setInterval> | null = null;
let pollCount = 0;

function stopPolling(): void {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  pollCount = 0;
}

export const useJobStore = create<JobState>((set, get) => ({
  jobId: null,
  status: "idle",
  error: null,
  logs: [],
  result: null,
  api: new ApiClient(DEFAULT_URL),

  submit: async (graph) => {
    stopPolling();
    set({ status: "running", error: null, logs: [], result: null });
    let id: string | null = null;
    try {
      const job = await get().api.graphExecute(graph);
      id = job.job_id;
      set({ jobId: id, status: job.status, error: job.error });
    } catch (err) {
      set({
        status: "failed",
        error: err instanceof Error ? err.message : "failed to submit job",
      });
      return;
    }
    if (id === null) return;

    const tick = async () => {
      const snapshot = await get().api.getJob(id!);
      set({
        status: snapshot.status,
        error: snapshot.error,
        logs: snapshot.logs ?? [],
      });
      if (snapshot.status === "succeeded" || snapshot.status === "failed" || snapshot.status === "cancelled") {
        stopPolling();
        // Fetch the accumulated logs on any terminal state (GE-1, GE-2).
        try {
          const logs = await get().api.getJobLogs(id!);
          set({ logs });
        } catch {
          /* logs are best-effort */
        }
        set({ result: snapshot.result });
      }
    };

    // Drive pollCount per interval tick.
    pollTimer = setInterval(() => {
      pollCount += 1;
      void tick().catch(() => {
        // Keep polling on transient errors until MAX_POLLS.
        if (pollCount >= MAX_POLLS) {
          stopPolling();
          set({ status: "failed", error: "poll limit reached" });
        }
      });
    }, POLL_INTERVAL_MS);
  },

  cancel: async () => {
    stopPolling();
    const current = get().jobId;
    if (!current) return;
    try {
      const job = await get().api.cancel(current);
      set({ jobId: job.job_id, status: job.status, error: job.error });
    } catch (err) {
      set({ status: "failed", error: err instanceof Error ? err.message : "failed to cancel" });
    }
  },

  reset: () => {
    stopPolling();
    set({ jobId: null, status: "idle", error: null, logs: [], result: null });
  },
}));
