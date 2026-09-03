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
 * Pull the NeutralMotion payload out of the raw job result.
 *
 * Expected path: `result.outputs["video-to-motion"]["motion"]`
 * Returns `null` when the structure is missing or malformed.
 */
export function extractMotion(
  result: Record<string, unknown> | null,
): NeutralMotionDoc | null {
  if (!result || typeof result !== "object") return null;

  const outputs = result.outputs as Record<string, unknown> | undefined;
  if (!outputs || typeof outputs !== "object") return null;

  const vtm = outputs["video-to-motion"] as Record<string, unknown> | undefined;
  if (!vtm || typeof vtm !== "object") return null;

  const motion = vtm.motion;
  if (
    !motion ||
    typeof motion !== "object" ||
    !("meta" in motion) ||
    !("skeleton" in motion) ||
    !("frames" in motion)
  ) {
    return null;
  }

  return motion as unknown as NeutralMotionDoc;
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
