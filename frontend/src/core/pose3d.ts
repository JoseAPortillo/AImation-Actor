/**
 * Pure 3D math for the authored-poses preview viewport.
 *
 * Turns the 2D keypoint sequence returned by `POST /pose/lift` into a stable,
 * orbitable orthographic scene: bounds are computed over the whole sequence so
 * framing does not jump between frames, points are normalized into a centered
 * cube, projected with a yaw/pitch orbit, and interpolated linearly for
 * scrubbing between consecutive poses. No DOM, no canvas, no third-party
 * deps — unit-testable in plain vitest (see pose3d.test.ts).
 */

import type { DetectedKeypoint3D } from "../api/types";

/** A point in 3D scene space (normalized, mathematical y-up convention). */
export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

/** A 2D position in canvas pixels (origin top-left, y grows downward). */
export interface ScreenPoint {
  x: number;
  y: number;
}

/** Axis-aligned bounds of the whole pose sequence (stable framing). */
export interface SceneBounds {
  min: Vec3;
  max: Vec3;
}

/**
 * Canonical half-extent of the normalized scene cube.
 *
 * `normalizeScene(..., targetSize)` maps the sequence into
 * `[-targetSize / 2, +targetSize / 2]`. Callers that feed
 * `projectOrthographic` should pass `targetSize = SCENE_HALF_EXTENT * 2`
 * (= 2) so the projector's fit matches the normalized cube.
 */
export const SCENE_HALF_EXTENT = 1;

/** Fixed pixel margin kept between the fitted scene and the viewport edge. */
export const VIEWPORT_MARGIN = 16;

/**
 * Compute the axis-aligned bounds of every keypoint across all frames.
 *
 * Uses min/max over x, y and z of every keypoint of every frame so the whole
 * sequence shares one stable framing (no per-frame "camera jump"). An empty
 * sequence (or all-empty frames) yields a degenerate zero cube instead of
 * ±Infinity, keeping downstream math NaN-free.
 */
export function sceneBounds(frames: DetectedKeypoint3D[][]): SceneBounds {
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let minZ = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  let maxZ = Number.NEGATIVE_INFINITY;

  for (const frame of frames) {
    for (const kp of frame) {
      minX = Math.min(minX, kp.x);
      minY = Math.min(minY, kp.y);
      minZ = Math.min(minZ, kp.z);
      maxX = Math.max(maxX, kp.x);
      maxY = Math.max(maxY, kp.y);
      maxZ = Math.max(maxZ, kp.z);
    }
  }

  if (!Number.isFinite(minX)) {
    return { min: { x: 0, y: 0, z: 0 }, max: { x: 0, y: 0, z: 0 } };
  }

  return {
    min: { x: minX, y: minY, z: minZ },
    max: { x: maxX, y: maxY, z: maxZ },
  };
}

/**
 * Centered, normalized position of `value` within [lo, hi] (0 = middle of the
 * range, -0.5/+0.5 = edges). A degenerate (empty or zero-range) axis falls
 * back to 0 so callers never divide by zero.
 */
function centered(value: number, lo: number, hi: number): number {
  const span = hi - lo;
  if (!(span > 0)) return 0;
  return (value - lo) / span - 0.5;
}

/**
 * Map one scene-space point from `bounds` into a centered cube.
 *
 * Each axis maps from [min, max] to `[-targetSize / 2, +targetSize / 2]` with
 * 0 = bounds center. The raw keypoint `y` axis is screen-down (0 = top of the
 * video frame), so it is inverted here to keep the scene y axis mathematically
 * up; `projectOrthographic` flips back to screen coordinates (y down) when
 * mapping to canvas pixels.
 */
export function normalizeScene(point: Vec3, bounds: SceneBounds, targetSize: number): Vec3 {
  return {
    x: centered(point.x, bounds.min.x, bounds.max.x) * targetSize,
    y: -centered(point.y, bounds.min.y, bounds.max.y) * targetSize,
    z: centered(point.z, bounds.min.z, bounds.max.z) * targetSize,
  };
}

/**
 * Orthographic projection of a normalized scene point to canvas pixels.
 *
 * Rotates the point around the up Y axis by `yaw` and around the X axis by
 * `pitch` (perspective-free), then uniformly fits the canonical scene cube
 * (half-extent `SCENE_HALF_EXTENT`) into `min(width, height) / 2` minus
 * `VIEWPORT_MARGIN`. The scene center maps to the canvas center for any
 * yaw/pitch; screen y grows downward.
 */
export function projectOrthographic(
  point: Vec3,
  yaw: number,
  pitch: number,
  width: number,
  height: number,
): ScreenPoint {
  const cosYaw = Math.cos(yaw);
  const sinYaw = Math.sin(yaw);
  const cosPitch = Math.cos(pitch);
  const sinPitch = Math.sin(pitch);

  // Yaw: rotate around the (up) Y axis, then pitch: rotate around the X axis.
  // Orthographic projection keeps the rotated x/y and drops the depth (z).
  const xAfterYaw = point.x * cosYaw + point.z * sinYaw;
  const yAfterYaw = point.y;
  const zAfterYaw = -point.x * sinYaw + point.z * cosYaw;
  const xAfterPitch = xAfterYaw;
  const yAfterPitch = yAfterYaw * cosPitch - zAfterYaw * sinPitch;

  const fitHalf = Math.min(width, height) / 2 - VIEWPORT_MARGIN;
  const scale = fitHalf / SCENE_HALF_EXTENT;
  const cx = width / 2;
  const cy = height / 2;

  return {
    x: cx + xAfterPitch * scale,
    y: cy - yAfterPitch * scale, // screen y grows downward (flip back from y-up)
  };
}

/**
 * Linearly interpolate between two lifted poses.
 *
 * Keypoints are matched by label; only labels present in BOTH `prev` and
 * `next` are returned, in `prev` order (labels missing from either side are
 * skipped). `t` is clamped to [0, 1]: 0 yields `prev` values, 1 yields `next`
 * values.
 */
export function interpolatePose(
  prev: DetectedKeypoint3D[],
  next: DetectedKeypoint3D[],
  t: number,
): DetectedKeypoint3D[] {
  const clamped = Math.max(0, Math.min(1, t));
  const nextByLabel = new Map(next.map((kp) => [kp.label, kp]));

  const result: DetectedKeypoint3D[] = [];
  for (const a of prev) {
    const b = nextByLabel.get(a.label);
    if (!b) continue;
    result.push({
      label: a.label,
      x: a.x + (b.x - a.x) * clamped,
      y: a.y + (b.y - a.y) * clamped,
      z: a.z + (b.z - a.z) * clamped,
      confidence: a.confidence + (b.confidence - a.confidence) * clamped,
    });
  }
  return result;
}