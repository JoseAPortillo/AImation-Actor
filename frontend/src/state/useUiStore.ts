import { create } from "zustand";

interface Banner {
  message: string;
  kind: "error" | "warning" | "info";
}

/** Which top-level workspace view is active (AR-3). */
export type UiMode = "simple" | "advanced";

interface UiState {
  banner: Banner | null;
  setBanner: (message: string, kind?: Banner["kind"]) => void;
  dismissBanner: () => void;
  mode: UiMode;
  setMode: (mode: UiMode) => void;
}

/**
 * Global UI store: connection banner (HTTP-3), transient UI state, and the
 * workspace mode (Simple vs Advanced). Banners are non-fatal — the app shell
 * stays interactive behind them. `mode` defaults to Simple so new users land on
 * the curated presets, with the node editor one toggle away.
 */
export const useUiStore = create<UiState>((set) => ({
  banner: null,
  setBanner: (message, kind = "error") => set({ banner: { message, kind } }),
  dismissBanner: () => set({ banner: null }),
  mode: "simple",
  setMode: (mode) => set({ mode }),
}));
