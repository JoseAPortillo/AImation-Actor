/**
 * TypeScript mirror of the AImation Actor Core contracts.
 *
 * Hand-mirrored from Python Pydantic models (schema.py, graph.py, job.py) as
 * the single source of truth is the core /nodes/types endpoint. The checked-in
 * golden fixture (`src/test/fixtures/nodeCatalog.json`) drifts when the core
 * schema changes; a contract test fails on that drift.
 */

export type DataType =
  | "frames"
  | "frame_stream"
  | "keypoints_2d"
  | "pose_3d"
  | "neutral_pose"
  | "neutral_animation"
  | "video_path"
  | "image"
  | "mesh"
  | "graph"
  | "boolean"
  | "number"
  | "string"
  | "any";

export const ANY: DataType = "any";

export type NodeCategory =
  | "source"
  | "ai"
  | "cleanup"
  | "enrichment"
  | "rigging"
  | "output"
  | "logic";

export interface PortSpec {
  name: string;
  data_type: DataType;
  required: boolean;
  default: string | number | boolean | null;
  description: string;
  widget?: string | null;
}

export interface NodeSchema {
  type: string;
  category: NodeCategory;
  title: string;
  description: string;
  inputs: PortSpec[];
  outputs: PortSpec[];
  params: PortSpec[];
}

export type JobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface JobSnapshot {
  job_id: string;
  kind: string;
  status: JobStatus;
  error: string | null;
  result: Record<string, unknown> | null;
  logs: string[];
}

export interface JobResultResponse {
  status: JobStatus;
  result: Record<string, unknown> | null;
}

/* ── NeutralMotion types (Video to Motion job output) ────────────────────── */

export type Vec3 = [number, number, number];
export type Vec4 = [number, number, number, number];

export interface Transform3D {
  translation: Vec3;
  rotation: Vec4;
  scale: Vec3;
}

export interface Bone {
  name: string;
  parent: string | null;
  rest_position: Vec3;
}

export interface SkeletonDoc {
  bones: Record<string, Bone>;
}

export interface MotionFrame {
  frame: number;
  time: number;
  pose: {
    transforms: Record<string, Transform3D>;
  };
  confidence?: number;
}

export interface NeutralMotionMeta {
  version: string;
  fps: number;
  units: string;
  up_axis: string;
  source_type: string;
  duration_frames: number;
  style: string;
  model_version: string;
  graph_hash: string;
}

/** A single authored key pose: source frame number (1-based) + lock weight. */
export interface KeyPose {
  frame: number;
  weight: number;
}

export interface NeutralMotionDoc {
  meta: NeutralMotionMeta;
  skeleton: SkeletonDoc;
  frames: MotionFrame[];
  contacts?: Record<string, unknown>;
  keyposes?: KeyPose[];
  tracking?: {
    confidence_per_frame: number[];
  };
}
