import { describe, it, expect, beforeEach } from "vitest";
import { usePaletteStore } from "./usePaletteStore";
import { ApiClient } from "../api/ApiClient";
import { MockTransport } from "../api/transport";

const TWO_NODES = [
  {
    type: "video-source",
    category: "source",
    title: "Frame Extractor",
    description: "",
    inputs: [],
    outputs: [],
    params: [],
  },
  {
    type: "frame-range",
    category: "source",
    title: "Frame Range",
    description: "",
    inputs: [],
    outputs: [],
    params: [],
  },
];

describe("usePaletteStore (NP-1)", () => {
  beforeEach(() => {
    usePaletteStore.setState({ catalog: [], status: "idle", error: null });
  });

  it("fetches and stores the node catalog, transitioning to ready", async () => {
    const transport = new MockTransport();
    transport.enqueue(200, TWO_NODES);
    const client = new ApiClient("http://127.0.0.1:8765", "tok", transport);
    const store = usePaletteStore.getState();

    const promise = store.fetch(client);
    expect(usePaletteStore.getState().status).toBe("loading");
    await promise;

    const state = usePaletteStore.getState();
    expect(state.status).toBe("ready");
    expect(state.catalog).toHaveLength(2);
    expect(state.catalog[0].type).toBe("video-source");
  });

  it("on failure sets status error with the message, ready to retry", async () => {
    const transport = new MockTransport();
    transport.enqueue(401, { detail: "Not authenticated" });
    const client = new ApiClient("http://127.0.0.1:8765", "bad", transport);

    await usePaletteStore.getState().fetch(client);

    const state = usePaletteStore.getState();
    expect(state.status).toBe("error");
    expect(state.error).toBeTruthy();
    expect(state.catalog).toHaveLength(0);
  });

  it("retry re-fetches after a failure and becomes ready", async () => {
    const transport = new MockTransport();
    transport.enqueue(500, { error: "boom" });
    transport.enqueue(200, TWO_NODES);
    const client = new ApiClient("http://127.0.0.1:8765", "tok", transport);

    await usePaletteStore.getState().fetch(client);
    expect(usePaletteStore.getState().status).toBe("error");

    await usePaletteStore.getState().retry(client);
    const state = usePaletteStore.getState();
    expect(state.status).toBe("ready");
    expect(state.catalog).toHaveLength(2);
  });
});
