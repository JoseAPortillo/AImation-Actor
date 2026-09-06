import { create } from "zustand";
import { ApiClient } from "../api/ApiClient";
import type { NodeSchema } from "../api/types";

type PaletteStatus = "idle" | "loading" | "ready" | "error";

interface PaletteState {
  catalog: NodeSchema[];
  status: PaletteStatus;
  error: string | null;
  fetch: (client?: ApiClient) => Promise<void>;
  retry: (client?: ApiClient) => Promise<void>;
}

/**
 * Palette store (NP-1): loads the live node catalog from `GET /nodes/types`
 * via the ApiClient. Failures map to a retryable `error` state rather than a
 * crash; `retry` re-fetches without a full reload.
 */
export const usePaletteStore = create<PaletteState>((set, get) => ({
  catalog: [],
  status: "idle",
  error: null,
  async fetch(client = new ApiClient()) {
    set({ status: "loading", error: null });
    try {
      const catalog = await client.nodes();
      set({ catalog, status: "ready", error: null });
    } catch (err) {
      set({
        status: "error",
        error: err instanceof Error ? err.message : "failed to load node catalog",
      });
    }
  },
  async retry(client = new ApiClient()) {
    await get().fetch(client);
  },
}));
