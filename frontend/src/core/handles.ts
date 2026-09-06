/**
 * Handle & category color maps for the dark-theme AImation-style node canvas.
 * Pure data, no React dependency.
 */
import type { DataType, NodeCategory } from "../api/types";

const HANDLE_COLORS: Record<DataType, string> = {
  video_path: "#4ade80",
  frames: "#4ade80",
  frame_stream: "#4ade80",
  image: "#f97316",
  keypoints_2d: "#a78bfa",
  pose_3d: "#a78bfa",
  neutral_pose: "#a78bfa",
  neutral_animation: "#a78bfa",
  mesh: "#facc15",
  graph: "#38bdf8",
  boolean: "#f472b6",
  number: "#60a5fa",
  string: "#94a3b8",
  any: "#888",
};

const CATEGORY_COLORS: Record<NodeCategory, string> = {
  source: "#2563eb",
  ai: "#7c3aed",
  cleanup: "#059669",
  rigging: "#d97706",
  output: "#dc2626",
  logic: "#0891b2",
};

export function getHandleColor(dataType: DataType): string {
  return HANDLE_COLORS[dataType] ?? "#888";
}

export function getCategoryColor(category: NodeCategory): string {
  return CATEGORY_COLORS[category] ?? "#555";
}
