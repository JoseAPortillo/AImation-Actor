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
  | "rigging"
  | "output"
  | "logic";

export interface PortSpec {
  name: string;
  data_type: DataType;
  required: boolean;
  default: string | number | boolean | null;
  description: string;
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
