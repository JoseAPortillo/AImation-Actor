import { describe, it, expect } from "vitest";
import { validateVideoPath, videoPathWarning } from "./videoPath";

describe("core/videoPath validator (PP-2)", () => {
  it("accepts a plain relative-to-media filename", () => {
    expect(validateVideoPath("movie.avi")).toEqual({ valid: true, warning: null });
  });

  it("accepts a relative path into a media subfolder", () => {
    expect(validateVideoPath("clips/clip01.avi")).toEqual({ valid: true, warning: null });
    expect(validateVideoPath("clips/nested/clip01.mp4")).toEqual({ valid: true, warning: null });
  });

  it("rejects an absolute path (windows and posix)", () => {
    expect(validateVideoPath("C:\\media\\movie.avi").valid).toBe(false);
    expect(validateVideoPath("/media/movie.avi").valid).toBe(false);
    expect(validateVideoPath("/home/user/movie.avi").valid).toBe(false);
  });

  it("rejects any parent-directory traversal (../)", () => {
    expect(validateVideoPath("../secret.avi").valid).toBe(false);
    expect(validateVideoPath("clips/../../secret.avi").valid).toBe(false);
    expect(validateVideoPath("a/../b.avi").valid).toBe(false);
  });

  it("produces a non-blocking warning (not a validity error) for guidance", () => {
    const w = videoPathWarning("C:\\media\\movie.avi");
    expect(w).not.toBeNull();
    expect(w).toContain("relative");
    expect(videoPathWarning("movie.avi")).toBeNull();
  });
});
