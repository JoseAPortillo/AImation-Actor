import "@testing-library/jest-dom";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeAll, afterAll } from "vitest";
import { server } from "./server";

// Node >= 22 exposes an experimental built-in `localStorage` global that, in the
// jsdom environment, shadows jsdom's Storage with a broken empty object (no
// getItem/setItem/removeItem/clear). Install a minimal in-memory Storage shim on
// both globalThis and window so tests that persist (e.g. custom presets) work.
// The backing store is a private field so `Object.keys(localStorage)` — which the
// token guardrail test uses to prove nothing is persisted — stays empty.
class MemoryStorage {
  #store = new Map<string, string>();
  get length() {
    return this.#store.size;
  }
  clear() {
    this.#store.clear();
  }
  getItem(key: string): string | null {
    return this.#store.has(key) ? this.#store.get(key)! : null;
  }
  setItem(key: string, value: string): void {
    this.#store.set(String(key), String(value));
  }
  removeItem(key: string): void {
    this.#store.delete(key);
  }
  key(index: number): string | null {
    return Array.from(this.#store.keys())[index] ?? null;
  }
}
if (typeof globalThis.localStorage === "undefined" || typeof (globalThis.localStorage as Storage).getItem !== "function") {
  const shim = new MemoryStorage();
  (globalThis as { localStorage: Storage }).localStorage = shim as unknown as Storage;
  if (typeof window !== "undefined") {
    (window as { localStorage: Storage }).localStorage = shim as unknown as Storage;
  }
}

// React Flow (and canvas libraries generally) rely on ResizeObserver to
// measure the viewport. jsdom does not provide it, so stub a no-op observer.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (typeof globalThis.ResizeObserver === "undefined") {
  (globalThis as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub;
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => server.close());
