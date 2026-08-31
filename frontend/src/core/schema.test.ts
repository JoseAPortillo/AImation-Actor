import { describe, it, expect } from "vitest";
import nodeCatalogFixture from "../test/fixtures/nodeCatalog.json";
import type { NodeSchema } from "../../api/types";

/**
 * Golden-fixture contract (D4): the checked-in node catalog fixture is the
 * live `/nodes/types` capture. If it drifts from the core, this test fails and
 * the fixture must be regenerated. It must expose exactly the 7 real nodes.
 */
const catalog = nodeCatalogFixture as NodeSchema[];

describe("nodeCatalog fixture contract (NP-1, D4)", () => {
  it("exposes exactly the 7 real node types", () => {
    expect(catalog).toHaveLength(7);
    const types = catalog.map((n) => n.type).sort();
    expect(types).toEqual([
      "frame-range",
      "merge",
      "pass-through",
      "pose-2d",
      "pose-3d",
      "video-source",
      "video-to-motion",
    ]);
  });

  it("typed ports are present on the nodes the editor wires", () => {
    const pose3d = catalog.find((n) => n.type === "pose-3d")!;
    expect(pose3d.inputs[0]).toMatchObject({ name: "keypoints", data_type: "keypoints_2d" });
    expect(pose3d.outputs[0]).toMatchObject({ name: "keypoints_3d", data_type: "pose_3d" });

    const videoSource = catalog.find((n) => n.type === "video-source")!;
    expect(videoSource.outputs[0]).toMatchObject({ name: "frames", data_type: "frames" });

    const passThrough = catalog.find((n) => n.type === "pass-through")!;
    expect(passThrough.inputs[0].data_type).toBe("any");
    expect(passThrough.outputs[0].data_type).toBe("any");
  });
});
