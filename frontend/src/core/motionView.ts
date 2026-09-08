/**
 * Pure functions for the neutral-motion stick-figure viewer.
 *
 * All functions are side-effect-free and canvas-independent so they can be
 * unit-tested without a DOM.  The canvas rendering lives in MotionViewer.tsx.
 */

import type {
  NeutralMotionDoc,
  Vec3,
} from "../api/types";

/* ── extraction ──────────────────────────────────────────────────────────── */

/**
 * Type-guard: does `candidate` look like a NeutralMotionDoc?
 *
 * Checks for the three required top-level keys (`meta`, `skeleton`, `frames`)
 * and that `frames` is an array.  Exported so extraction helpers and tests can
 * share the same predicate.
 */
export function isNeutralMotionDoc(
  candidate: unknown,
): candidate is NeutralMotionDoc {
  return (
    !!candidate &&
    typeof candidate === "object" &&
    "meta" in candidate &&
    "skeleton" in candidate &&
    "frames" in candidate &&
    Array.isArray((candidate as { frames?: unknown }).frames)
  );
}

/**
 * Pull the NeutralMotion payload out of a raw job result.
 *
 * Results from a graph run are keyed by node id:
 *
 *   `result.outputs["<any-node-id>"]["motion"]`    (blocking-input, video-to-motion)
 *   `result.outputs["<any-node-id>"]`              (direct doc as the node value)
 *
 * The first motion-shaped value found across all outputs wins. Returns `null`
 * when the structure is missing or nothing looks like a motion, keeping
 * backward compatibility with the legacy `video-to-motion` node id (Simple
 * Mode's preset uses that stable id).
 */
export function extractMotion(
  result: Record<string, unknown> | null,
): NeutralMotionDoc | null {
  if (!result || typeof result !== "object") return null;

  const outputs = result.outputs as Record<string, unknown> | undefined;
  if (!outputs || typeof outputs !== "object") return null;

  for (const v of Object.values(outputs)) {
    if (!v || typeof v !== "object") continue;

    if (
      typeof v === "object" &&
      "motion" in v &&
      isNeutralMotionDoc((v as { motion?: unknown }).motion)
    ) {
      return (v as { motion: NeutralMotionDoc }).motion;
    }

    if (isNeutralMotionDoc(v)) return v;
  }

  return null;
}

/**
 * Extract the NeutralMotion payload for a *specific* node from a graph result.
 *
 * Unlike `extractMotion` (which returns the first motion found across all
 * outputs), this targets a single node id so the per-node preview knows
 * exactly which output belongs to it.
 *
 * Returns `null` when:
 *   - `result` is null or has no `outputs`
 *   - `nodeId` is not present in outputs
 *   - The value for `nodeId` is not a motion-shaped object (direct doc or
 *     `{ motion: NeutralMotionDoc }` wrapper)
 */
export function extractNodeMotion(
  result: Record<string, unknown> | null,
  nodeId: string,
): NeutralMotionDoc | null {
  if (!result || typeof result !== "object") return null;

  const outputs = result.outputs as Record<string, unknown> | undefined;
  if (!outputs || typeof outputs !== "object") return null;

  const v = outputs[nodeId];
  if (!v || typeof v !== "object") return null;

  // Wrapper form: { motion: NeutralMotionDoc }
  if ("motion" in v && isNeutralMotionDoc((v as { motion?: unknown }).motion)) {
    return (v as { motion: NeutralMotionDoc }).motion;
  }

  // Direct doc form: the value IS the NeutralMotionDoc.
  if (isNeutralMotionDoc(v)) return v;

  return null;
}

/* ── FK accumulation ─────────────────────────────────────────────────────── */

/**
 * Compute absolute 3D positions for every bone at `frameIndex`.
 *
 * **Algorithm** — forward-kinematics additive blend:
 *
 * The skeleton bones are already stored parent-first so a single pass suffices.
 * For each bone we:
 *   1. Grab its LOCAL translation for the requested frame (the `Vec3` inside
 *      `pose.transforms[boneName].translation`).  If the bone is missing from
 *      the frame we fall back to `rest_position` as a zero-velocity default.
 *   2. Add that local translation to the absolute position of the bone's
 *      parent.  Root has no parent, so its absolute = rest + local.
 *
 * This matches `only_local: true` semantics (all translations are offsets
 * relative to the parent bone's coordinate frame).
 *
 * Edge cases:
 *   - `frames` empty or `frameIndex` out of range → returns `{}`.
 *   - Bone present in skeleton but missing from frame transforms → uses
 *     `rest_position` as local offset (static bone).
 *
 * @returns Record keyed by bone name → `[x, y, z]` absolute position.
 */
export function absolutePositions(
  motion: NeutralMotionDoc,
  frameIndex: number,
): Record<string, Vec3> {
  const result: Record<string, Vec3> = {};

  if (motion.frames.length === 0) return result;
  const clamped = Math.max(0, Math.min(frameIndex, motion.frames.length - 1));
  const frame = motion.frames[clamped];
  const { transforms } = frame.pose;
  const { bones } = motion.skeleton;

  for (const name of Object.keys(bones)) {
    const bone = bones[name];
    // Local translation: frame data or rest_position fallback.
    const t = transforms[name]?.translation ?? bone.rest_position;
    const parentAbs = bone.parent != null ? result[bone.parent] : null;
    if (parentAbs != null) {
      result[name] = [
        parentAbs[0] + t[0],
        parentAbs[1] + t[1],
        parentAbs[2] + t[2],
      ];
    } else {
      // Root (or orphan): absolute = rest + local (rest is effectively 0,0,0
      // for Root, but we add it for generality).
      result[name] = [bone.rest_position[0] + t[0], bone.rest_position[1] + t[1], bone.rest_position[2] + t[2]];
    }
  }

  return result;
}

/* ── bone pairs for drawing ──────────────────────────────────────────────── */

/**
 * Return every `(parent, child)` pair that should be drawn as a line.
 *
 * The Root bone is treated as the invisible origin — it has no parent line
 * drawn TO it, but lines FROM Root to its children are included.
 * Filtering rule: `child !== "Root"`.
 */
export function drawBones(
  motion: NeutralMotionDoc,
): Array<{ parent: string; child: string }> {
  const pairs: Array<{ parent: string; child: string }> = [];
  for (const bone of Object.values(motion.skeleton.bones)) {
    if (bone.parent != null && bone.name !== "Root") {
      pairs.push({ parent: bone.parent, child: bone.name });
    }
  }
  return pairs;
}
