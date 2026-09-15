import { describe, it, expect, beforeEach } from "vitest";
import { usePinsStore } from "./usePinsStore";
import { ApiClient } from "../api/ApiClient";
import { MockTransport, type Transport } from "../api/transport";

/** Transport that defers responses until the test resolves them (guard tests). */
class DeferredTransport implements Transport {
  requests: { method: string; url: string }[] = [];
  private pending: Array<(resp: Response) => void> = [];

  request(path: string, init?: RequestInit): Promise<Response> {
    this.requests.push({ method: init?.method ?? "GET", url: path });
    return new Promise((resolve) => {
      this.pending.push(resolve);
    });
  }

  resolveNext(body: unknown, status = 200): void {
    const resolve = this.pending.shift();
    resolve?.(new Response(JSON.stringify(body), { status }));
  }
}

function makeClient() {
  const transport = new MockTransport();
  const api = new ApiClient("http://127.0.0.1:8765", "tok", transport);
  return { transport, api };
}

function addFirstPin(nodeId: string, frame: number): string {
  usePinsStore.getState().addPin(nodeId, frame);
  return usePinsStore.getState().pinsByNode[nodeId][0].id;
}

describe("usePinsStore pin CRUD (Phase A golden-poses-ux)", () => {
  beforeEach(() => {
    usePinsStore.setState({ pinsByNode: {} });
  });

  it("addPin creates the first pin as G1 with status 'processing' at the given frame", () => {
    usePinsStore.getState().addPin("node-a", 12);
    const pins = usePinsStore.getState().pinsByNode["node-a"];
    expect(pins).toHaveLength(1);
    expect(pins[0].label).toBe("G1");
    expect(pins[0].frame).toBe(12);
    expect(pins[0].status).toBe("processing");
    expect(pins[0].confidence).toBeNull();
    expect(pins[0].detection).toBeNull();
    expect(pins[0].id).toBeTruthy();
  });

  it("addPin labels are sequential per node (G1, G2) and independent across nodes", () => {
    const store = usePinsStore.getState();
    store.addPin("node-a", 1);
    store.addPin("node-a", 2);
    store.addPin("node-b", 3);
    expect(usePinsStore.getState().pinsByNode["node-a"].map((p) => p.label)).toEqual([
      "G1",
      "G2",
    ]);
    expect(usePinsStore.getState().pinsByNode["node-b"][0].label).toBe("G1");
  });

  it("addPin issues distinct pin ids", () => {
    const store = usePinsStore.getState();
    store.addPin("node-a", 1);
    store.addPin("node-a", 2);
    const ids = usePinsStore.getState().pinsByNode["node-a"].map((p) => p.id);
    expect(ids[0]).not.toBe(ids[1]);
  });

  it("movePin repositions the target pin at the new frame", () => {
    const store = usePinsStore.getState();
    store.addPin("node-a", 5);
    const pinId = usePinsStore.getState().pinsByNode["node-a"][0].id;
    store.movePin("node-a", pinId, 42);
    expect(usePinsStore.getState().pinsByNode["node-a"][0].frame).toBe(42);
  });

  it("movePin with an unknown pin id is a no-op", () => {
    const store = usePinsStore.getState();
    store.addPin("node-a", 5);
    store.movePin("node-a", "missing-pin", 99);
    expect(usePinsStore.getState().pinsByNode["node-a"][0].frame).toBe(5);
  });

  it("removePin deletes only the target pin and keeps remaining labels unchanged", () => {
    const store = usePinsStore.getState();
    store.addPin("node-a", 1);
    store.addPin("node-a", 2);
    store.addPin("node-a", 3);
    const pins = usePinsStore.getState().pinsByNode["node-a"];
    store.removePin("node-a", pins[1].id); // remove G2
    const remaining = usePinsStore.getState().pinsByNode["node-a"];
    expect(remaining.map((p) => p.label)).toEqual(["G1", "G3"]);
    expect(remaining.map((p) => p.frame)).toEqual([1, 3]);
  });

  it("removePin leaves the node entry as [] when the last pin is removed", () => {
    const store = usePinsStore.getState();
    store.addPin("node-a", 1);
    const pinId = usePinsStore.getState().pinsByNode["node-a"][0].id;
    store.removePin("node-a", pinId);
    expect(usePinsStore.getState().pinsByNode["node-a"]).toEqual([]);
  });

  it("removeNodePins clears all pins for a node and drops the key", () => {
    const store = usePinsStore.getState();
    store.addPin("node-a", 1);
    store.addPin("node-a", 2);
    store.addPin("node-b", 3);
    store.removeNodePins("node-a");
    const state = usePinsStore.getState();
    expect(state.pinsByNode["node-a"]).toBeUndefined();
    expect(state.pinsByNode["node-b"]).toHaveLength(1);
  });

  it("removeNodePins for an unknown node is a no-op", () => {
    const store = usePinsStore.getState();
    store.addPin("node-a", 1);
    store.removeNodePins("node-unknown");
    expect(usePinsStore.getState().pinsByNode["node-a"]).toHaveLength(1);
  });
});

describe("usePinsStore detection lifecycle ⏳→✓/✗ (D1 single-in-flight guard)", () => {
  beforeEach(() => {
    usePinsStore.setState({ pinsByNode: {} });
  });

  it("detectPin marks the pin 'success' with confidence + keypoints from the API", async () => {
    const { transport, api } = makeClient();
    usePinsStore.setState({ api });
    const pinId = addFirstPin("node-a", 7);

    const pose = {
      keypoints: [
        { label: "nose", x: 0.5, y: 0.2, confidence: 0.95 },
        { label: "left_shoulder", x: 0.4, y: 0.35, confidence: 0.95 },
      ],
      confidence: 0.95,
    };
    transport.enqueue(200, pose);
    await usePinsStore.getState().detectPin("node-a", pinId, "uploads/ab12_video.mp4");

    expect(transport.requests[0].url).toBe(
      "http://127.0.0.1:8765/detect/uploads/ab12_video.mp4/7",
    );
    const pin = usePinsStore.getState().pinsByNode["node-a"][0];
    expect(pin.status).toBe("success");
    expect(pin.confidence).toBe(0.95);
    expect(pin.detection).toHaveLength(2);
    expect(pin.detection![0].label).toBe("nose");
  });

  it("detectPin marks the pin 'error' when the API fails and keeps it editable", async () => {
    const { transport, api } = makeClient();
    usePinsStore.setState({ api });
    const pinId = addFirstPin("node-a", 7);

    transport.enqueue(501, { detail: "ONNX single-frame inference not yet implemented" });
    await usePinsStore.getState().detectPin("node-a", pinId, "uploads/ab12_video.mp4");

    const pin = usePinsStore.getState().pinsByNode["node-a"][0];
    expect(pin.status).toBe("error");
    expect(pin.confidence).toBeNull();
    expect(pin.detection).toBeNull();
  });

  it("does NOT issue overlapping detection requests while a pin is 'processing' (D1 guard)", async () => {
    const deferred = new DeferredTransport();
    const api = new ApiClient("http://127.0.0.1:8765", "tok", deferred);
    usePinsStore.setState({ api });
    const pinId = addFirstPin("node-a", 7);

    const first = usePinsStore.getState().detectPin("node-a", pinId, "uploads/ab12_video.mp4");
    // Concurrent call while the first is in flight — swallowed by the guard.
    await usePinsStore.getState().detectPin("node-a", pinId, "uploads/ab12_video.mp4");
    deferred.resolveNext({ keypoints: [], confidence: 0.9 });
    await first;

    expect(deferred.requests).toHaveLength(1);
    expect(usePinsStore.getState().pinsByNode["node-a"][0].status).toBe("success");
  });

  it("re-runs detection on a 'success' pin when asked again (only 'processing' is guarded)", async () => {
    const deferred = new DeferredTransport();
    const api = new ApiClient("http://127.0.0.1:8765", "tok", deferred);
    usePinsStore.setState({ api });
    const pinId = addFirstPin("node-a", 7);

    const first = usePinsStore.getState().detectPin("node-a", pinId, "uploads/ab12_video.mp4");
    deferred.resolveNext({ keypoints: [], confidence: 0.9 });
    await first;

    const second = usePinsStore.getState().detectPin("node-a", pinId, "uploads/ab12_video.mp4");
    deferred.resolveNext({ keypoints: [], confidence: 0.8 });
    await second;

    expect(deferred.requests).toHaveLength(2);
    expect(usePinsStore.getState().pinsByNode["node-a"][0].status).toBe("success");
    expect(usePinsStore.getState().pinsByNode["node-a"][0].confidence).toBe(0.8);
  });
});