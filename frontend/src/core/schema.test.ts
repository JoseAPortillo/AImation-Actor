import { describe, it, expect } from "vitest";
import nodeCatalogFixture from "../test/fixtures/nodeCatalog.json";
import type { NodeSchema } from "../api/types";
import {
  findInputPort,
  findOutputPort,
  findParam,
  getDefaultedParams,
  validateSchemaShape,
} from "./schema";

const catalog = nodeCatalogFixture as NodeSchema[];

describe("core/schema helpers (EC-1, PP-1)", () => {
  const videoSource = catalog.find((n) => n.type === "video-source")!;
  const pose2d = catalog.find((n) => n.type === "pose-2d")!;
  const v2m = catalog.find((n) => n.type === "video-to-motion")!;

  it("findOutputPort returns the schema output port by name", () => {
    const port = findOutputPort(videoSource, "frames");
    expect(port).not.toBeUndefined();
    expect(port!.name).toBe("frames");
    expect(port!.data_type).toBe("frames");
  });

  it("findInputPort returns the schema input port by name", () => {
    const port = findInputPort(pose2d, "frames");
    expect(port).not.toBeUndefined();
    expect(port!.name).toBe("frames");
    expect(port!.data_type).toBe("frames");
  });

  it("findParam returns the schema param spec by name and undefined when absent", () => {
    const start = findParam(videoSource, "start");
    expect(start).not.toBeUndefined();
    expect(start!.data_type).toBe("number");
    expect(findParam(videoSource, "does-not-exist")).toBeUndefined();
  });

  it("findOutputPort/findInputPort return undefined for a missing port", () => {
    expect(findOutputPort(videoSource, "nope")).toBeUndefined();
    expect(findInputPort(videoSource, "nope")).toBeUndefined();
  });

  it("getDefaultedParams fills numerics/booleans default for unset params (PP-1)", () => {
    const params = getDefaultedParams(v2m, {});
    // person_height_cm default 172.0, only_local default true.
    expect(params.person_height_cm).toBe(172.0);
    expect(params.only_local).toBe(true);
  });

  it("getDefaultedParams never overwrites a user-provided value", () => {
    const merged = getDefaultedParams(v2m, { only_local: false });
    expect(merged.only_local).toBe(false);
    expect(merged.person_height_cm).toBe(172.0);
  });

  it("getDefaultedParams drops null-default params so required validation can catch unset (GE-3)", () => {
    // video-source: video_path default null → absent; start default 0 → filled.
    const filled = getDefaultedParams(videoSource, {});
    expect(filled.start).toBe(0);
    expect(Object.keys(filled)).not.toContain("video_path");
  });

  it("validateSchemaShape accepts a well-formed schema and flags malformed ones", () => {
    expect(validateSchemaShape(videoSource)).toEqual({ valid: true, errors: [] });
    const missingTitle: NodeSchema = { ...videoSource, title: "" };
    expect(validateSchemaShape(missingTitle).valid).toBe(false);
    const badPort: NodeSchema = {
      ...videoSource,
      outputs: [{ ...videoSource.outputs[0], name: "" }],
    };
    expect(validateSchemaShape(badPort).valid).toBe(false);
  });
});
