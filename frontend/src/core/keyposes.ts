/**
 * Pure merge helper: maps frontend pins onto NeutralMotionDoc.keyposes.
 *
 * All pins whose frame is in the valid range [1, duration_frames] are merged
 * sorted by frame (stable for equal frames). Pins outside the range are
 * silently dropped. When no pins are in range the doc is returned unchanged
 * (same reference, no mutation).
 */

import type { NeutralMotionDoc, KeyPose } from "../api/types";

/**
 * Structural contract for the pin objects that `applyKeyposes` reads.
 *
 * Kept minimal to avoid a circular dependency on the store: any object with
 * `frame` (1-based) and `confidence` (0..1 | null) satisfies this interface.
 * `Pin` from usePinsStore is structurally assignable to this.
 */
export interface KeyposeSource {
  frame: number;
  confidence: number | null;
}

/**
 * Return a new doc whose `keyposes` contains one {@link KeyPose} per in-range
 * pin, sorted by frame.  When no pins are in range the original doc is
 * returned as-is (same reference — no unnecessary allocation).
 */
export function applyKeyposes(
  result: NeutralMotionDoc,
  pins: KeyposeSource[],
): NeutralMotionDoc {
  const duration = result.meta?.duration_frames;
  if (typeof duration !== "number" || duration <= 0) return result;

  const inRange = pins.filter((p) => p.frame >= 1 && p.frame <= duration);
  if (inRange.length === 0) return result;

  // Array.sort is stable in V8 (Node ≥ 12 / Chrome ≥ 70).
  inRange.sort((a, b) => a.frame - b.frame);

  const keyposes: KeyPose[] = inRange.map((p) => ({
    frame: p.frame,
    weight: p.confidence ?? 1,
  }));

  return { ...result, keyposes };
}
