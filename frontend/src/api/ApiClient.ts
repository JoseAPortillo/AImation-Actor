/**
 * Pure HTTP client mirroring `aimation_actor_core/cli.py` ApiClient.
 *
 * All client logic is testable without a live network via an injected
 * `Transport` (fetchTransport / MockTransport). Errors are normalized to a
 * typed `ApiError` and never thrown out as raw fetch failures (HTTP-3).
 */

import { fetchTransport, type Transport } from "./transport";
import { sessionToken } from "./token";
import type {
  DetectedKeypoint,
  DetectedKeypoint3D,
  JobResultResponse,
  JobSnapshot,
  LiftPose3DRequest,
  LiftPose3DResponse,
  NodeSchema,
  SingleFramePose,
} from "./types";

export const DEFAULT_URL = "http://127.0.0.1:8765";

export type ApiErrorKind =
  | "network"
  | "unauthorized"
  | "not_found"
  | "server"
  | "empty"
  | "invalid";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;

  constructor(kind: ApiErrorKind, message: string, status?: number) {
    super(message);
    this.kind = kind;
    this.status = status;
  }
}

function joinBase(base: string, path: string): string {
  return `${base.replace(/\/+$/, "")}${path}`;
}

function normalizeStatus(status: number): ApiErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 404) return "not_found";
  if (status >= 500) return "server";
  return "server";
}

function detailFrom(body: unknown, text: string): string {
  if (body && typeof body === "object") {
    const obj = body as Record<string, unknown>;
    const d = obj["detail"] ?? obj["error"];
    if (typeof d === "string" && d) return d;
  }
  return (text ?? "").trim() || "request failed";
}

export class ApiClient {
  readonly baseUrl: string;
  private readonly token: string;
  private readonly transport: Transport;

  constructor(
    baseUrl: string = DEFAULT_URL,
    token: string = sessionToken(),
    transport: Transport = fetchTransport,
  ) {
    this.baseUrl = baseUrl;
    this.token = token;
    this.transport = transport;
  }

  private headers(requiresAuth: boolean, multipart = false): Headers {
    const headers = new Headers();
    if (!multipart) {
      headers.set("Content-Type", "application/json");
    }
    if (requiresAuth && this.token) {
      headers.set("Authorization", `Bearer ${this.token}`);
    }
    return headers;
  }

  private async request(
    method: string,
    path: string,
    body?: unknown,
    requiresAuth = true,
    signal?: AbortSignal,
    multipart = false,
  ): Promise<Response> {
    const init: RequestInit = {
      method,
      headers: this.headers(requiresAuth, multipart),
      signal,
    };
    if (body !== undefined) {
      // Multipart bodies (FormData) must reach the wire un-serialized so fetch
      // can set the boundary itself; everything else goes as JSON.
      init.body = multipart ? (body as FormData) : JSON.stringify(body);
    }
    try {
      return await this.transport.request(joinBase(this.baseUrl, path), init);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError("network", err instanceof Error ? err.message : "Network error");
    }
  }

  /** Build a normalized ApiError from a non-2xx response body (HTTP-3). */
  private async errorFor(resp: Response): Promise<ApiError> {
    const text = await resp.text().catch(() => "");
    let body: unknown = null;
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
    return new ApiError(
      normalizeStatus(resp.status),
      `HTTP ${resp.status}: ${detailFrom(body, text)}`,
      resp.status,
    );
  }

  private async expectObject(resp: Response): Promise<Record<string, unknown>> {
    if (resp.status >= 400) {
      throw await this.errorFor(resp);
    }
    const text = await resp.text().catch(() => "");
    if (!text) throw new ApiError("empty", "empty response");
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        throw new ApiError("invalid", `expected a JSON object, got ${Array.isArray(parsed) ? "array" : typeof parsed}`);
      }
      return parsed as Record<string, unknown>;
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError("invalid", "invalid JSON response");
    }
  }

  private async expectList(resp: Response): Promise<unknown[]> {
    if (resp.status >= 400) {
      throw await this.errorFor(resp);
    }
    const text = await resp.text().catch(() => "");
    if (!text) throw new ApiError("empty", "empty response");
    try {
      const parsed = JSON.parse(text);
      if (!Array.isArray(parsed)) {
        throw new ApiError("invalid", `expected a JSON array, got ${typeof parsed}`);
      }
      return parsed;
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError("invalid", "invalid JSON response");
    }
  }

  /** GET /health — public, no Authorization header (HTTP-1). */
  async health(): Promise<Record<string, unknown>> {
    return this.expectObject(await this.request("GET", "/health", undefined, false));
  }

  /** GET /nodes/types — the node catalog. */
  async nodes(): Promise<NodeSchema[]> {
    return (await this.expectList(await this.request("GET", "/nodes/types"))) as NodeSchema[];
  }

  /** POST /jobs/graph/execute — submit a graph; returns the job snapshot. */
  async graphExecute(graph: Record<string, unknown>, signal?: AbortSignal): Promise<JobSnapshot> {
    return (await this.expectObject(
      await this.request("POST", "/jobs/graph/execute", graph, true, signal),
    )) as unknown as JobSnapshot;
  }

  /** GET /jobs/{id} — current job snapshot. */
  async getJob(jobId: string): Promise<JobSnapshot> {
    return (await this.expectObject(
      await this.request("GET", `/jobs/${jobId}`),
    )) as unknown as JobSnapshot;
  }

  /** GET /jobs/{id}/result. */
  async getJobResult(jobId: string): Promise<JobResultResponse> {
    return (await this.expectObject(
      await this.request("GET", `/jobs/${jobId}/result`),
    )) as unknown as JobResultResponse;
  }

  /** GET /jobs/{id}/logs. */
  async getJobLogs(jobId: string): Promise<string[]> {
    return (await this.expectList(
      await this.request("GET", `/jobs/${jobId}/logs`),
    )) as string[];
  }

  /** POST /jobs/{id}/cancel. */
  async cancel(jobId: string): Promise<JobSnapshot> {
    return (await this.expectObject(
      await this.request("POST", `/jobs/${jobId}/cancel`),
    )) as unknown as JobSnapshot;
  }

  /**
   * GET /media/frame — fetch one video frame as a JPEG Blob.
   *
   * `frame_index` is 1-based (the backend boundary contract). The response's
   * `X-Frame-Count` header carries the video's total frame count so the
   * timeslider can size its range without an extra request.
   */
  async fetchFrameJpeg(
    videoPath: string,
    frameIndex: number,
    width?: number,
  ): Promise<{ blob: Blob; frameCount: number }> {
    const query = new URLSearchParams();
    query.set("video_path", videoPath);
    query.set("frame_index", String(frameIndex));
    if (width !== undefined) {
      query.set("width", String(width));
    }
    const resp = await this.request("GET", `/media/frame?${query.toString()}`);
    if (resp.status >= 400) {
      throw await this.errorFor(resp);
    }
    // Fetch API normalizes headers to lowercase
    const raw = resp.headers.get("x-frame-count");
    const frameCount = raw !== null && Number.isFinite(Number(raw)) ? Number(raw) : 0;
    const blob = await resp.blob();
    return { blob, frameCount };
  }

  /**
   * POST /media/upload — upload a video file as multipart/form-data.
   *
   * Returns the stored media reference (e.g. `uploads/ab12…_video.mp4`)
   * relative to the media-root allowlist.
   */
  async uploadVideo(file: File): Promise<string> {
    const form = new FormData();
    form.append("file", file, file.name);
    const resp = await this.request("POST", "/media/upload", form, true, undefined, true);
    const obj = await this.expectObject(resp);
    const reference = obj["reference"];
    if (typeof reference !== "string" || reference.length === 0) {
      throw new ApiError("invalid", "upload response missing reference");
    }
    return reference;
  }

  /**
   * GET /detect/{video_path}/{frame_index} — detect the 2D pose of a single
   * 1-based frame (decision D1). Returns named keypoints with normalized x/y
   * plus a frame-level confidence.
   */
  async detectPose(videoPath: string, frameIndex: number): Promise<SingleFramePose> {
    return (await this.expectObject(
      await this.request("GET", `/detect/${videoPath}/${frameIndex}`),
    )) as unknown as SingleFramePose;
  }

  /**
   * POST /pose/lift — bulk deterministic 2D→3D lift of every keypoint.
   *
   * @param frames One 2D COCO keypoint array per video frame, in sequence order.
   * @returns The same shape/order with a heuristic `z` added per keypoint.
   */
  async liftPose3D(frames: DetectedKeypoint[][]): Promise<DetectedKeypoint3D[][]> {
    const body: LiftPose3DRequest = { frames };
    const obj = (await this.expectObject(
      await this.request("POST", "/pose/lift", body),
    )) as unknown as LiftPose3DResponse;
    return obj.frames;
  }

  // ── Phase B: Round-trip Blender endpoints ───────────────────────────────

  /**
   * POST /sessions/{sessionId}/push_result — send golden poses to Blender addon.
   *
   * @param sessionId - The active DCC session ID
   * @param motion - The NeutralMotion document with golden pose data
   */
  async pushPosesToBlender(sessionId: string, motion: Record<string, unknown>): Promise<void> {
    const payload = {
      kind: "golden_poses",
      motion,
    };
    const resp = await this.request("POST", `/sessions/${sessionId}/push_result`, payload);
    if (resp.status >= 400) {
      throw await this.errorFor(resp);
    }
  }

  /**
   * GET /sessions/{sessionId}/pending — poll for edited poses from Blender.
   *
   * Returns the edited NeutralMotion document, or null if no pending payloads.
   *
   * @param sessionId - The active DCC session ID
   */
  async requestEditedPoses(sessionId: string): Promise<Record<string, unknown> | null> {
    const resp = await this.request("GET", `/sessions/${sessionId}/pending`);
    if (resp.status === 204) {
      return null;
    }
    if (resp.status >= 400) {
      throw await this.errorFor(resp);
    }
    const obj = await this.expectObject(resp);
    return obj["motion"] as Record<string, unknown> | null;
  }

  // ── Phase C: Generate motion endpoint ───────────────────────────────────

  /**
   * POST /generate-motion — generate motion between golden poses.
   *
   * @param params - Golden poses + slider parameters (naturalidad, respetarPoses)
   * @returns NeutralMotionDoc with generated frames
   */
  async generateMotion(params: {
    goldenPoses: Array<{
      frame: number;
      label: string;
      confidence: number | null;
      detection: import("./types").DetectedKeypoint[] | null;
    }>;
    naturalidad: number;
    respetarPoses: number;
  }): Promise<Record<string, unknown>> {
    const resp = await this.request("POST", "/generate-motion", params);
    return this.expectObject(resp);
  }
}
