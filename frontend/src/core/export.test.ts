import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { downloadTextFile, motionExportPayloads } from "./export";
import type { NeutralMotionDoc } from "../api/types";

/* ── fixtures ────────────────────────────────────────────────────────────── */

function makeTestMotion(): NeutralMotionDoc {
  return {
    meta: {
      version: "1.0",
      fps: 24,
      units: "m",
      up_axis: "Y",
      source_type: "neutral",
      duration_frames: 1,
      style: "default",
      model_version: "0.1",
      graph_hash: "abc",
    },
    skeleton: {
      bones: {
        Root: { name: "Root", parent: null, rest_position: [0, 0, 0] },
        Head: { name: "Head", parent: "Root", rest_position: [0, 10, 0] },
      },
    },
    frames: [
      {
        frame: 1,
        time: 0,
        pose: {
          transforms: {
            Root: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
            Head: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
          },
        },
      },
    ],
  };
}

/* ── downloadTextFile ────────────────────────────────────────────────────── */

describe("downloadTextFile", () => {
  let createObjectURLSpy: ReturnType<typeof vi.spyOn>;
  let revokeObjectURLSpy: ReturnType<typeof vi.spyOn>;
  let clickSpy: ReturnType<typeof vi.fn>;
  let appendChildSpy: ReturnType<typeof vi.spyOn>;
  let removeChildSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    // Mock URL.createObjectURL and revokeObjectURL
    createObjectURLSpy = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock-url");
    revokeObjectURLSpy = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});

    // Mock document.createElement to return a mock anchor
    clickSpy = vi.fn();
    const mockAnchor = {
      href: "",
      download: "",
      click: clickSpy,
    };
    vi.spyOn(document, "createElement").mockReturnValue(mockAnchor as unknown as HTMLAnchorElement);
    appendChildSpy = vi.spyOn(document.body, "appendChild").mockImplementation(() => mockAnchor as unknown as Node);
    removeChildSpy = vi.spyOn(document.body, "removeChild").mockImplementation(() => mockAnchor as unknown as Node);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls createObjectURL once with a Blob", () => {
    downloadTextFile("test.txt", "content", "text/plain");

    expect(createObjectURLSpy).toHaveBeenCalledOnce();
    const blob = createObjectURLSpy.mock.calls[0][0];
    expect(blob).toBeInstanceOf(Blob);
  });

  it("creates an anchor, clicks it, and revokes the URL", () => {
    downloadTextFile("test.txt", "content", "text/plain");

    expect(clickSpy).toHaveBeenCalledOnce();
    expect(revokeObjectURLSpy).toHaveBeenCalledWith("blob:mock-url");
    expect(appendChildSpy).toHaveBeenCalledOnce();
    expect(removeChildSpy).toHaveBeenCalledOnce();
  });

  it("sets the download attribute to the filename", () => {
    const mockAnchor = { href: "", download: "", click: vi.fn() };
    vi.spyOn(document, "createElement").mockReturnValue(mockAnchor as unknown as HTMLAnchorElement);

    downloadTextFile("motion.bvh", "bvh content", "application/octet-stream");

    expect(mockAnchor.download).toBe("motion.bvh");
  });
});

/* ── motionExportPayloads ────────────────────────────────────────────────── */

describe("motionExportPayloads", () => {
  it("returns bvh and json payloads with correct structure", () => {
    const motion = makeTestMotion();
    const payloads = motionExportPayloads(motion);

    expect(payloads.bvh).toBeDefined();
    expect(payloads.json).toBeDefined();

    expect(payloads.bvh.filename).toBe("motion.bvh");
    expect(payloads.bvh.mimeType).toBe("application/octet-stream");
    expect(payloads.bvh.content).toContain("HIERARCHY");

    expect(payloads.json.filename).toBe("motion.json");
    expect(payloads.json.mimeType).toBe("application/json");
    expect(payloads.json.content).toContain('"meta"');
  });

  it("produces pretty-printed JSON with 2-space indent", () => {
    const motion = makeTestMotion();
    const payloads = motionExportPayloads(motion);

    // Check that JSON is formatted (contains newlines and 2-space indent)
    expect(payloads.json.content).toContain("\n");
    expect(payloads.json.content).toContain('  "meta"');
  });

  it("BVH content is valid BVH text", () => {
    const motion = makeTestMotion();
    const payloads = motionExportPayloads(motion);

    expect(payloads.bvh.content).toContain("HIERARCHY");
    expect(payloads.bvh.content).toContain("ROOT Root");
    expect(payloads.bvh.content).toContain("MOTION");
  });
});
