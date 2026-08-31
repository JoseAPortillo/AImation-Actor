/**
 * Pure HTTP client mirroring `aimation_actor_core/cli.py` ApiClient.
 *
 * All client logic is testable without a live network via an injected
 * `Transport` (fetchTransport / MockTransport). Errors are normalized to a
 * typed `ApiError` and never thrown out as raw fetch failures (HTTP-3).
 */

import { fetchTransport, type Transport } from "./transport";
import { sessionToken } from "./token";
import type { JobResultResponse, JobSnapshot, NodeSchema } from "./types";

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

  private headers(requiresAuth: boolean): Headers {
    const headers = new Headers();
    headers.set("Content-Type", "application/json");
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
  ): Promise<Response> {
    const init: RequestInit = {
      method,
      headers: this.headers(requiresAuth),
    };
    if (body !== undefined) {
      init.body = JSON.stringify(body);
    }
    try {
      return await this.transport.request(joinBase(this.baseUrl, path), init);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError("network", err instanceof Error ? err.message : "Network error");
    }
  }

  private async expectObject(resp: Response): Promise<Record<string, unknown>> {
    if (resp.status >= 400) {
      const text = await resp.text().catch(() => "");
      let detail = text;
      let body: unknown = null;
      try {
        body = JSON.parse(text);
      } catch {
        body = null;
      }
      detail = detailFrom(body, text);
      throw new ApiError(normalizeStatus(resp.status), `HTTP ${resp.status}: ${detail}`, resp.status);
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
      const text = await resp.text().catch(() => "");
      let detail = text;
      let body: unknown = null;
      try {
        body = JSON.parse(text);
      } catch {
        body = null;
      }
      detail = detailFrom(body, text);
      throw new ApiError(normalizeStatus(resp.status), `HTTP ${resp.status}: ${detail}`, resp.status);
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
  async graphExecute(graph: Record<string, unknown>): Promise<JobSnapshot> {
    return (await this.expectObject(
      await this.request("POST", "/jobs/graph/execute", graph),
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
}
