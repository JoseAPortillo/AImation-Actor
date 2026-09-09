/**
 * Export utilities for motion data.
 *
 * Provides download functions and payload builders for BVH and JSON export.
 * DOM-dependent downloadTextFile is guarded for jsdom/SSR safety.
 */

import type { NeutralMotionDoc } from "../api/types";
import { neutralToBvh } from "./bvh";

/**
 * Download a text file via browser Blob API.
 *
 * Guards against missing DOM/Blob/URL for jsdom and SSR environments.
 *
 * @param filename - The filename to download as
 * @param content - The text content of the file
 * @param mimeType - The MIME type for the blob
 */
export function downloadTextFile(
  filename: string,
  content: string,
  mimeType: string
): void {
  // Guard for SSR/jsdom environments
  if (
    typeof document === "undefined" ||
    typeof Blob === "undefined" ||
    typeof URL === "undefined"
  ) {
    return;
  }

  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);

  URL.revokeObjectURL(url);
}

/**
 * Build export payloads for BVH and JSON formats.
 *
 * Keeps serialization logic out of components and makes happy path testable.
 *
 * @param motion - The motion document to export
 * @returns Object with bvh and json payloads
 */
export function motionExportPayloads(motion: NeutralMotionDoc): {
  bvh: { filename: string; content: string; mimeType: string };
  json: { filename: string; content: string; mimeType: string };
} {
  return {
    bvh: {
      filename: "motion.bvh",
      content: neutralToBvh(motion),
      mimeType: "application/octet-stream",
    },
    json: {
      filename: "motion.json",
      content: JSON.stringify(motion, null, 2),
      mimeType: "application/json",
    },
  };
}
