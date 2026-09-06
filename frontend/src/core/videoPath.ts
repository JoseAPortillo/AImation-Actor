/**
 * video_path validation/guidance (PP-2).
 *
 * The panel validates and guides media-relative paths: reject absolute paths
 * and any `../` parent traversal, accept relative-to-`media/` paths. This is
 * UI guidance only — the core remains the enforcement boundary, so a rejected
 * value is surfaced as a non-blocking warning, never as a submission block.
 */

export interface VideoPathResult {
  valid: boolean;
  warning: string | null;
}

const IS_ABSOLUTE =
  /^(?:[A-Za-z]:[\\/])|^[\\/]/;

const HAS_PARENT_TRAVERSAL = /(?:^|[\\/])\.\.(?:[\\/]|$)/;

export function validateVideoPath(value: string): VideoPathResult {
  if (IS_ABSOLUTE.test(value) || HAS_PARENT_TRAVERSAL.test(value)) {
    return {
      valid: false,
      warning:
        "video_path must be relative to the media root — no absolute paths or '..' allowed.",
    };
  }
  return { valid: true, warning: null };
}

export function videoPathWarning(value: string): string | null {
  return validateVideoPath(value).warning;
}
