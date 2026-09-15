import "@testing-library/jest-dom";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeAll, afterAll } from "vitest";
import { server } from "./server";

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

// jsdom does not implement URL.createObjectURL/revokeObjectURL. Add a harmless
// in-memory stub so components that preview fetched blobs (VideoTimeslider)
// keep working under test — the fake URLs never load, which is fine for jsdom.
if (typeof URL.createObjectURL !== "function") {
  let blobSeq = 0;
  (URL as { createObjectURL: (blob: Blob) => string }).createObjectURL = (blob: Blob) =>
    `blob:jsdom-${blobSeq++}-${blob.size}`;
  (URL as { revokeObjectURL: (url: string) => void }).revokeObjectURL = () => {};
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => server.close());
