/**
 * Frontend-only golden-pin store (Phase A, decision D2).
 *
 * Pins are pure frontend state per node: the `video-source` schema MUST NOT
 * change and nothing here is persisted to the backend. Each pin carries its
 * own detection lifecycle ⏳ (processing) → ✓ (success) / ✗ (error); a single
 * in-flight guard (decision D1) prevents overlapping detection requests for
 * the same pin. Network access goes through an injectable `ApiClient` so the
 * store is unit-testable without a live backend (matches useJobStore).
 */

import { create } from "zustand";
import { ApiClient, DEFAULT_URL } from "../api/ApiClient";
import type { DetectedKeypoint } from "../api/types";

export type PinStatus = "processing" | "success" | "error";

export interface Pin {
  id: string;
  /** Sequential label per node, G1, G2, G3… (never renumbered). */
  label: string;
  /** 1-based video frame the pin is anchored to. */
  frame: number;
  status: PinStatus;
  /** Frame-level detection confidence in [0, 1], null until detection succeeds. */
  confidence: number | null;
  /** Detected keypoints, null until detection succeeds. */
  detection: DetectedKeypoint[] | null;
}

interface PinState {
  /** Pins grouped by flow node id. */
  pinsByNode: Record<string, Pin[]>;
  /** Injectable for tests; defaults to a real client over the base URL. */
  api: ApiClient;
  /** Add a pin at `frame`, labeled G{maxSuffix+1} and marked ⏳ processing. */
  addPin(nodeId: string, frame: number): void;
  /** Reposition an existing pin to a new frame (label and status unchanged). */
  movePin(nodeId: string, pinId: string, frame: number): void;
  /** Delete one pin; remaining pins keep their labels. */
  removePin(nodeId: string, pinId: string): void;
  /** Delete every pin of a node (used by flow-store node removal). */
  removeNodePins(nodeId: string): void;
  /**
   * Run single-frame detection for a pin: ⏳ processing → ✓ success / ✗ error.
   * Skips the request while the pin is already processing (D1 guard).
   */
  detectPin(nodeId: string, pinId: string, videoPath: string): Promise<void>;
}

const LABEL_RE = /^G(\d+)$/;

/**
 * Pin ids with a detection request currently in flight. This is the D1
 * single-in-flight guard: `status === "processing"` is also the initial state
 * set by addPin, so guarding on status alone would swallow the first request.
 */
const inFlight = new Set<string>();

/** Highest existing numeric pin label for a node, or 0 when none match. */
function maxLabelSuffix(pins: Pin[]): number {
  let max = 0;
  for (const pin of pins) {
    const match = LABEL_RE.exec(pin.label);
    if (match) max = Math.max(max, Number(match[1]));
  }
  return max;
}

/** Map one pin entry with `replacePin` returning the updated pin (or null). */
function updatePin(
  state: PinState,
  nodeId: string,
  pinId: string,
  update: (pin: Pin) => Pin,
): Partial<PinState> {
  const pins = state.pinsByNode[nodeId];
  if (!pins) return {};
  return {
    pinsByNode: {
      ...state.pinsByNode,
      [nodeId]: pins.map((p) => (p.id === pinId ? update(p) : p)),
    },
  };
}

export const usePinsStore = create<PinState>((set, get) => ({
  pinsByNode: {},
  api: new ApiClient(DEFAULT_URL),

  addPin: (nodeId, frame) => {
    const pins = get().pinsByNode[nodeId] ?? [];
    const label = `G${maxLabelSuffix(pins) + 1}`;
    const pin: Pin = {
      id: crypto.randomUUID(),
      label,
      frame,
      status: "processing",
      confidence: null,
      detection: null,
    };
    set((state) => ({
      pinsByNode: { ...state.pinsByNode, [nodeId]: [...pins, pin] },
    }));
  },

  movePin: (nodeId, pinId, frame) => {
    set((state) =>
      updatePin(state, nodeId, pinId, (pin) => ({ ...pin, frame })),
    );
  },

  removePin: (nodeId, pinId) => {
    set((state) => {
      const pins = state.pinsByNode[nodeId];
      if (!pins) return {};
      return {
        pinsByNode: {
          ...state.pinsByNode,
          [nodeId]: pins.filter((p) => p.id !== pinId),
        },
      };
    });
  },

  removeNodePins: (nodeId) => {
    set((state) => {
      if (!(nodeId in state.pinsByNode)) return {};
      const { [nodeId]: _removed, ...rest } = state.pinsByNode;
      return { pinsByNode: rest };
    });
  },

  detectPin: async (nodeId, pinId, videoPath) => {
    const key = `${nodeId}:${pinId}`;
    const current = get().pinsByNode[nodeId]?.find((p) => p.id === pinId);
    if (!current || inFlight.has(key)) return; // D1 single-in-flight guard

    inFlight.add(key);
    set((state) =>
      updatePin(state, nodeId, pinId, (pin) => ({ ...pin, status: "processing" })),
    );

    try {
      const pose = await get().api.detectPose(videoPath, current.frame);
      set((state) =>
        updatePin(state, nodeId, pinId, (pin) => ({
          ...pin,
          status: "success",
          confidence: pose.confidence,
          detection: pose.keypoints,
        })),
      );
    } catch {
      set((state) =>
        updatePin(state, nodeId, pinId, (pin) => ({
          ...pin,
          status: "error",
          confidence: null,
          detection: null,
        })),
      );
    } finally {
      inFlight.delete(key);
    }
  },
}));