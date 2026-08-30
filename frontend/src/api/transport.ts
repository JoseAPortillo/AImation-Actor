/**
 * Transport abstraction around the HTTP layer, mirroring the injectable
 * client seam of `cli.py`. `fetchTransport` uses the browser fetch API;
 * `MockTransport` returns canned `Response` objects for network-free tests.
 */

export interface Transport {
  request(path: string, init?: RequestInit): Promise<Response>;
}

/** Real transport backed by the browser's fetch API. */
export const fetchTransport: Transport = {
  request: (path: string, init?: RequestInit) => fetch(path, init),
};

interface QueuedResponse {
  response: Response | null;
  error: Error | null;
}

/** In-memory transport that returns queued canned responses for unit tests. */
export class MockTransport implements Transport {
  private queue: QueuedResponse[] = [];
  requests: { method: string; url: string; headers: Headers; body: string | null }[] = [];

  enqueue(status: number, body: unknown, headers?: Record<string, string>): void {
    const h = new Headers(headers);
    h.set("Content-Type", "application/json");
    const text = typeof body === "string" ? body : JSON.stringify(body);
    this.queue.push({
      response: new Response(text, { status, headers: h }),
      error: null,
    });
  }

  failNext(error: Error): void {
    this.queue.push({ response: null, error });
  }

  async request(path: string, init?: RequestInit): Promise<Response> {
    this.requests.push({
      method: init?.method ?? "GET",
      url: path,
      headers: (init?.headers as Headers) ?? new Headers(),
      body: (init?.body as string | null) ?? null,
    });
    const next = this.queue.shift();
    if (next === undefined || next.response === null) {
      const error = next?.error ?? new TypeError("Failed to fetch");
      throw error;
    }
    return next.response;
  }
}
