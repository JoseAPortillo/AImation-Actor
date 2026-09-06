import { describe, it, expect } from "vitest";
import type { AimGraph } from "./graph";
import { serializeGraph, parseGraph } from "./serialize";
import { toCanonicalAimGraph } from "./serialize";

/**
 * Golden fixture mirroring the core's `build_pipeline_graph` canonical output
 * (AR-2 golden canonical bytes). Pins the exact key order and indentation that
 * the core's `_save_pretty_json` (json.dumps indent=2 + trailing newline) emits.
 */
const goldenCanonical = `{
  "version": "1.0",
  "nodes": [
    {
      "id": "src",
      "type": "video-source",
      "params": {
        "video_path": "clip.avi",
        "end": 5,
        "resize": 64
      }
    },
    {
      "id": "p2d",
      "type": "pose-2d",
      "params": {
        "model": "synthetic"
      }
    },
    {
      "id": "p3d",
      "type": "pose-3d",
      "params": {
        "model": "synthetic"
      }
    },
    {
      "id": "v2m",
      "type": "video-to-motion",
      "params": {}
    }
  ],
  "edges": [
    {
      "id": "e1",
      "source": {
        "node": "src",
        "port": "frames"
      },
      "target": {
        "node": "p2d",
        "port": "frames"
      }
    },
    {
      "id": "e2",
      "source": {
        "node": "p2d",
        "port": "keypoints"
      },
      "target": {
        "node": "p3d",
        "port": "keypoints"
      }
    },
    {
      "id": "e3",
      "source": {
        "node": "p3d",
        "port": "keypoints_3d"
      },
      "target": {
        "node": "v2m",
        "port": "keypoints_3d"
      }
    }
  ]
}
`;

const goldenGraph: AimGraph = {
  version: "1.0",
  nodes: [
    {
      id: "src",
      type: "video-source",
      params: { video_path: "clip.avi", end: 5, resize: 64 },
    },
    { id: "p2d", type: "pose-2d", params: { model: "synthetic" } },
    { id: "p3d", type: "pose-3d", params: { model: "synthetic" } },
    { id: "v2m", type: "video-to-motion", params: {} },
  ],
  edges: [
    {
      id: "e1",
      source: { node: "src", port: "frames" },
      target: { node: "p2d", port: "frames" },
    },
    {
      id: "e2",
      source: { node: "p2d", port: "keypoints" },
      target: { node: "p3d", port: "keypoints" },
    },
    {
      id: "e3",
      source: { node: "p3d", port: "keypoints_3d" },
      target: { node: "v2m", port: "keypoints_3d" },
    },
  ],
};

describe("serializeGraph canonical bytes (AR-2 golden)", () => {
  it("serializes the golden build_pipeline_graph byte-for-byte", () => {
    expect(serializeGraph(goldenGraph)).toBe(goldenCanonical);
  });
});

describe("parseGraph (AR-2, AR-1)", () => {
  it("parses canonical v1.0 JSON back into an AimGraph", () => {
    const parsed = parseGraph(goldenCanonical);
    expect(parsed.ok).toBe(true);
    expect(parsed.graph).toEqual(goldenGraph);
    expect(parsed.graph!.version).toBe("1.0");
  });

  it("rejects an unsupported version (v0.1) and reports an error", () => {
    const stale = goldenCanonical.replace('"1.0"', '"0.1"');
    const result = parseGraph(stale);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toContain("unsupported version");
    }
  });

  it("rejects malformed JSON", () => {
    const result = parseGraph("{ not json");
    expect(result.ok).toBe(false);
  });
});

describe("toCanonicalAimGraph strips RF internals and keeps layout extras (AR-1)", () => {
  it("keeps canonical fields and drops measured/__rf but preserves position/viewport", () => {
    const rich: AimGraph = {
      version: "1.0",
      nodes: [
        {
          id: "src",
          type: "video-source",
          params: {},
          measured: { width: 100, height: 50 },
          __rf: { something: true },
          position: { x: 10, y: 20 },
        },
      ],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
    };
    const canonical = toCanonicalAimGraph(rich);
    // position is a whitelisted extra, measured and __rf are stripped.
    expect(canonical.nodes[0].position).toEqual({ x: 10, y: 20 });
    expect("measured" in canonical.nodes[0]).toBe(false);
    expect("__rf" in canonical.nodes[0]).toBe(false);
    expect(canonical.viewport).toEqual({ x: 0, y: 0, zoom: 1 });
  });
});
