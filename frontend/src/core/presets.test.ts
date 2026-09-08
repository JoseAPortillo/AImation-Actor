import { describe, it, expect } from "vitest";
import { presets, videoToMotionPreset, videoToMotionEnrichedPreset, blockingToMotionPreset, findPreset } from "./presets";
import { parseGraph, serializeGraph } from "./serialize";

describe("presets", () => {
  it("exposes the presets in display order", () => {
    expect(presets().map((p) => p.id)).toEqual([
      "video-to-motion",
      "video-to-motion-enriched",
      "blocking-to-motion",
    ]);
    expect(presets()[0].title).toBe("Video to Motion");
    expect(presets()[0].description.length).toBeGreaterThan(0);
    expect(presets()[1].title).toBe("Video to Motion (Enriched)");
    expect(presets()[1].description.length).toBeGreaterThan(0);
    expect(presets()[2].title).toBe("Blocking to Motion");
    expect(presets()[2].description.length).toBeGreaterThan(0);
  });

  it("returns a fresh, independent graph instance per call", () => {
    const a = videoToMotionPreset().graph;
    const b = videoToMotionPreset().graph;
    expect(a).not.toBe(b);
    // Mutating one must never affect the other.
    a.nodes[0].params.video_path = "X.mp4";
    expect(b.nodes[0].params.video_path).toBeUndefined();
  });

  it("builds a canonical v1.0 graph that round-trips through parseGraph", () => {
    const { graph } = videoToMotionPreset();
    const result = parseGraph(serializeGraph(graph));
    expect(result.ok).toBe(true);
    const roundTripped = result.ok ? result.graph : undefined;
    expect(roundTripped).toEqual(graph);
    expect(roundTripped?.version).toBe("1.0");
  });

  describe("Video to Motion graph wiring", () => {
    const { graph } = videoToMotionPreset();

    it("chains 4 nodes in the canonical order", () => {
      expect(graph.nodes.map((n) => n.type)).toEqual([
        "video-source",
        "pose-2d",
        "pose-3d",
        "video-to-motion",
      ]);
      // Stable ids for idempotent merge.
      expect(graph.nodes.map((n) => n.id)).toEqual([
        "video-source",
        "pose-2d",
        "pose-3d",
        "video-to-motion",
      ]);
    });

    it("gives nodes flow layout positions", () => {
      for (const n of graph.nodes) {
        expect(n.position).toEqual(expect.objectContaining({ x: expect.any(Number), y: expect.any(Number) }));
      }
    });

    it("wires 3 edges chaining source -> 2D -> 3D -> motion output", () => {
      expect(graph.edges.length).toBe(3);

      const byId = Object.fromEntries(graph.nodes.map((n) => [n.id, n]));
      for (const e of graph.edges) {
        const src = byId[e.source.node];
        const dst = byId[e.target.node];
        // Every edge references nodes that exist in the graph.
        expect(src).toBeDefined();
        expect(dst).toBeDefined();
        // Ports align with the canonical chain.
        expect(e.source.node !== e.target.node).toBe(true);
      }
    });

    it("wires the exact expected connections", () => {
      const connections = graph.edges.map((e) => ({
        s: `${e.source.node}.${e.source.port}`,
        t: `${e.target.node}.${e.target.port}`,
      }));
      expect(connections).toEqual([
        { s: "video-source.frames", t: "pose-2d.frames" },
        { s: "pose-2d.keypoints", t: "pose-3d.keypoints" },
        { s: "pose-3d.keypoints_3d", t: "video-to-motion.keypoints_3d" },
      ]);
    });

    it("seeds sensible default params", () => {
      const byId = Object.fromEntries(graph.nodes.map((n) => [n.id, n]));
      expect(byId["pose-2d"].params.model).toBe("synthetic");
      expect(byId["pose-3d"].params.depth_mode).toBe("proportional");
      expect(byId["video-to-motion"].params.person_height_cm).toBe(172.0);
      expect(byId["video-to-motion"].params.only_local).toBe(true);
    });
  });

  it("finds a preset by stable id", () => {
    const found = findPreset("video-to-motion");
    expect(found?.title).toBe("Video to Motion");
    expect(findPreset("does-not-exist")).toBeUndefined();
  });

  describe("Video to Motion (Enriched) graph wiring", () => {
    const { graph } = videoToMotionEnrichedPreset();

    it("chains 5 nodes adding in-between generation", () => {
      expect(graph.nodes.map((n) => n.type)).toEqual([
        "video-source",
        "pose-2d",
        "pose-3d",
        "video-to-motion",
        "inbetween-generation",
      ]);
      expect(graph.nodes.map((n) => n.id)).toEqual([
        "video-source",
        "pose-2d",
        "pose-3d",
        "video-to-motion",
        "inbetween-generation",
      ]);
    });

    it("wires 4 edges ending in the enrichment node", () => {
      expect(graph.edges.length).toBe(4);
      const connections = graph.edges.map((e) => ({
        s: `${e.source.node}.${e.source.port}`,
        t: `${e.target.node}.${e.target.port}`,
      }));
      expect(connections).toEqual([
        { s: "video-source.frames", t: "pose-2d.frames" },
        { s: "pose-2d.keypoints", t: "pose-3d.keypoints" },
        { s: "pose-3d.keypoints_3d", t: "video-to-motion.keypoints_3d" },
        { s: "video-to-motion.motion", t: "inbetween-generation.motion" },
      ]);
    });

    it("seeds sensible in-between params", () => {
      const byId = Object.fromEntries(graph.nodes.map((n) => [n.id, n]));
      const ib = byId["inbetween-generation"].params;
      expect(ib.interpolation_method).toBe("cubic");
      expect(ib.target_fps).toBe(48);
      expect(ib.easing).toBe("ease-in-out");
      expect(ib.euler_filter).toBe(true);
      expect(ib.tangent_smoothing).toBe(0.0);
    });

    it("builds a canonical v1.0 graph that round-trips through parseGraph", () => {
      const result = parseGraph(serializeGraph(graph));
      expect(result.ok).toBe(true);
      const roundTripped = result.ok ? result.graph : undefined;
      expect(roundTripped).toEqual(graph);
      expect(roundTripped?.version).toBe("1.0");
    });
  });

  describe("Blocking to Motion graph wiring", () => {
    const { graph } = blockingToMotionPreset();

    it("chains 2 nodes: blocking-input -> inbetween-generation", () => {
      expect(graph.nodes.map((n) => n.type)).toEqual([
        "blocking-input",
        "inbetween-generation",
      ]);
      // Stable ids for idempotent merge.
      expect(graph.nodes.map((n) => n.id)).toEqual([
        "blocking-input",
        "inbetween-generation",
      ]);
    });

    it("gives nodes flow layout positions", () => {
      for (const n of graph.nodes) {
        expect(n.position).toEqual(
          expect.objectContaining({ x: expect.any(Number), y: expect.any(Number) }),
        );
      }
    });

    it("wires 1 edge from blocking-input.motion to inbetween-generation.motion", () => {
      expect(graph.edges.length).toBe(1);
      expect(graph.edges[0]).toEqual({
        id: "blocking-input-motion-inbetween-generation-motion",
        source: { node: "blocking-input", port: "motion" },
        target: { node: "inbetween-generation", port: "motion" },
      });
    });

    it("seeds preserve_keyposes true and a 30fps target on inbetween-generation", () => {
      const byId = Object.fromEntries(graph.nodes.map((n) => [n.id, n]));
      const ib = byId["inbetween-generation"].params;
      expect(ib.preserve_keyposes).toBe(true);
      expect(ib.target_fps).toBe(30);
    });

    it("builds a canonical v1.0 graph that round-trips through parseGraph", () => {
      const result = parseGraph(serializeGraph(graph));
      expect(result.ok).toBe(true);
      const roundTripped = result.ok ? result.graph : undefined;
      expect(roundTripped).toEqual(graph);
      expect(roundTripped?.version).toBe("1.0");
    });
  });
});
