import type { AimGraph } from "./graph";

/**
 * Simple Mode presets (AR-3).
 *
 * Each preset is a canonical `.aimgraph` v1.0 graph (see `graph.ts`) with stable,
 * deterministic node ids. Stable ids are what let a preset be re-applied without
 * duplicating nodes: `mergeGraphIntoFlow` merges by node id, so re-picking the
 * same preset updates layout/params in place instead of stacking duplicates.
 *
 * Positions are laid out left-to-right in flow coordinates.
 */

export interface Preset {
  /** Stable id used by the UI (also the user-facing key). */
  id: string;
  /** Short title shown on the preset card. */
  title: string;
  /** One-line description shown on the preset card. */
  description: string;
  /** The canonical graph to merge into the canvas when picked. */
  graph: AimGraph;
}

/** The canonical "Video to Motion" preset: video frames -> 2D -> 3D -> motion. */
export const videoToMotionPreset = (): Preset => ({
  id: "video-to-motion",
  title: "Video to Motion",
  description:
    "Converts a video into a neutral motion sequence: decode frames, estimate 2D keypoints, lift to 3D, and emit motion.",
  graph: {
    version: "1.0",
    nodes: [
      {
        id: "video-source",
        type: "video-source",
        position: { x: 40, y: 120 },
        params: { end: 24, resize: 128 },
      },
      {
        id: "pose-2d",
        type: "pose-2d",
        position: { x: 320, y: 120 },
        params: { model: "synthetic", confidence: 0.0 },
      },
      {
        id: "pose-3d",
        type: "pose-3d",
        position: { x: 600, y: 120 },
        params: { model: "synthetic", depth_mode: "proportional", confidence: 0.0 },
      },
      {
        id: "video-to-motion",
        type: "video-to-motion",
        position: { x: 880, y: 120 },
        params: { person_height_cm: 172.0, only_local: true },
      },
    ],
    edges: [
      {
        id: "video-source-frames-pose-2d-frames",
        source: { node: "video-source", port: "frames" },
        target: { node: "pose-2d", port: "frames" },
      },
      {
        id: "pose-2d-keypoints-pose-3d-keypoints",
        source: { node: "pose-2d", port: "keypoints" },
        target: { node: "pose-3d", port: "keypoints" },
      },
      {
        id: "pose-3d-keypoints_3d-video-to-motion-keypoints_3d",
        source: { node: "pose-3d", port: "keypoints_3d" },
        target: { node: "video-to-motion", port: "keypoints_3d" },
      },
    ],
  },
});

/** "Video to Motion + Enrichment": adds in-between frame generation (upsample). */
export const videoToMotionEnrichedPreset = (): Preset => ({
  id: "video-to-motion-enriched",
  title: "Video to Motion (Enriched)",
  description:
    "Converts a video into motion and upsamples it with in-between generation: smooth cubic interpolation, easing, and rotation continuity.",
  graph: {
    version: "1.0",
    nodes: [
      {
        id: "video-source",
        type: "video-source",
        position: { x: 40, y: 120 },
        params: { end: 24, resize: 128 },
      },
      {
        id: "pose-2d",
        type: "pose-2d",
        position: { x: 320, y: 120 },
        params: { model: "synthetic", confidence: 0.0 },
      },
      {
        id: "pose-3d",
        type: "pose-3d",
        position: { x: 600, y: 120 },
        params: { model: "synthetic", depth_mode: "proportional", confidence: 0.0 },
      },
      {
        id: "video-to-motion",
        type: "video-to-motion",
        position: { x: 880, y: 120 },
        params: { person_height_cm: 172.0, only_local: true },
      },
      {
        id: "inbetween-generation",
        type: "inbetween-generation",
        position: { x: 1160, y: 120 },
        params: {
          interpolation_method: "cubic",
          target_fps: 48,
          easing: "ease-in-out",
          euler_filter: true,
          tangent_smoothing: 0.0,
        },
      },
    ],
    edges: [
      {
        id: "video-source-frames-pose-2d-frames",
        source: { node: "video-source", port: "frames" },
        target: { node: "pose-2d", port: "frames" },
      },
      {
        id: "pose-2d-keypoints-pose-3d-keypoints",
        source: { node: "pose-2d", port: "keypoints" },
        target: { node: "pose-3d", port: "keypoints" },
      },
      {
        id: "pose-3d-keypoints_3d-video-to-motion-keypoints_3d",
        source: { node: "pose-3d", port: "keypoints_3d" },
        target: { node: "video-to-motion", port: "keypoints_3d" },
      },
      {
        id: "video-to-motion-motion-inbetween-generation-motion",
        source: { node: "video-to-motion", port: "motion" },
        target: { node: "inbetween-generation", port: "motion" },
      },
    ],
  },
});

/**
 * All available presets, in display order.
 *
 * The array is a function so each call yields a fresh graph instance (callers
 * may mutate layout/params without leaking state across renders).
 */
export function presets(): Preset[] {
  return [videoToMotionPreset(), videoToMotionEnrichedPreset()];
}

/** Look up a preset by its stable id. */
export function findPreset(id: string): Preset | undefined {
  return presets().find((p) => p.id === id);
}
