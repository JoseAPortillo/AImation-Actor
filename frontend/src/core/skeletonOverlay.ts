/**
 * 2D skeleton overlay helpers for the video timeslider.
 *
 * `drawSkeleton` maps normalized keypoints (0..1, from single-frame detection)
 * to display pixel coordinates via `x * width` / `y * height`, then pairs them
 * into line segments using the standard COCO-17 skeleton so a canvas renderer
 * (Phase 4) can draw the pose aligned with the video frame. Pure functions —
 * no canvas dependency, trivially unit-testable.
 */

import type { DetectedKeypoint } from "../api/types";

/** A point mapped to display coordinates. */
export interface DisplayPoint {
  label: string;
  x: number;
  y: number;
  confidence: number;
}

/** A bone connecting two mapped keypoints (drawn as a line). */
export interface SkeletonSegment {
  from: DisplayPoint;
  to: DisplayPoint;
}

/** Result of mapping a detection to a display size. */
export interface SkeletonOverlay {
  points: DisplayPoint[];
  segments: SkeletonSegment[];
}

/**
 * Standard COCO-17 skeleton bones (16 pairs over 17 joints), using the same
 * snake_case labels the synthetic backend emits — aligned end-to-end.
 */
export const COCO_BONES: ReadonlyArray<readonly [string, string]> = [
  ["nose", "left_eye"],
  ["nose", "right_eye"],
  ["left_eye", "left_ear"],
  ["right_eye", "right_ear"],
  ["left_shoulder", "right_shoulder"],
  ["left_shoulder", "left_elbow"],
  ["left_elbow", "left_wrist"],
  ["right_shoulder", "right_elbow"],
  ["right_elbow", "right_wrist"],
  ["left_shoulder", "left_hip"],
  ["right_shoulder", "right_hip"],
  ["left_hip", "right_hip"],
  ["left_hip", "left_knee"],
  ["left_knee", "left_ankle"],
  ["right_hip", "right_knee"],
  ["right_knee", "right_ankle"],
];

/**
 * Map normalized keypoints to a display size and pair them into COCO bones.
 *
 * @param keypoints    Detected keypoints with normalized x/y in [0, 1].
 * @param displayWidth  Pixel width of the target display (video element).
 * @param displayHeight Pixel height of the target display.
 * @returns All keypoints mapped to pixel coordinates plus one segment per
 *          present bone (both endpoints must exist in `keypoints`).
 */
export function drawSkeleton(
  keypoints: DetectedKeypoint[],
  displayWidth: number,
  displayHeight: number,
): SkeletonOverlay {
  const points: DisplayPoint[] = keypoints.map((k) => ({
    label: k.label,
    x: k.x * displayWidth,
    y: k.y * displayHeight,
    confidence: k.confidence,
  }));

  const byLabel = new Map(points.map((p) => [p.label, p]));

  const segments: SkeletonSegment[] = [];
  for (const [a, b] of COCO_BONES) {
    const from = byLabel.get(a);
    const to = byLabel.get(b);
    if (from && to) {
      segments.push({ from, to });
    }
  }

  return { points, segments };
}