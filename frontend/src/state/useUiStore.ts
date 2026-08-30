import { create } from "zustand";

interface Banner {
  message: string;
  kind: "error" | "warning" | "info";
}

interface UiState {
  banner: Banner | null;
  setBanner: (message: string, kind?: Banner["kind"]) => void;
  dismissBanner: () => void;
}

/**
 * Global UI store: connection banner (HTTP-3) and transient UI state.
 * Banners are non-fatal — the app shell stays interactive behind them.
 */
export const useUiStore = create<UiState>((set) => ({
  banner: null,
  setBanner: (message, kind = "error") => set({ banner: { message, kind } }),
  dismissBanner: () => set({ banner: null }),
}));
