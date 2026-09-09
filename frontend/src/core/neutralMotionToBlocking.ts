/**
 * Frontend conversion bridge: NeutralMotionDoc → BlockingInput payload.
 *
 * When a user loads an exported "Video to Motion (Enriched)" result into the
 * blocking-input param, the file is a full NeutralMotionDoc. This module
 * converts it into a valid BlockingInput payload so the strict backend
 * validation passes. The backend contract itself stays untouched.
 */
import type { NeutralMotionDoc, SkeletonDoc, Transform3D } from "../api/types";

/** Mirror of the core DEFAULT_BLOCKING_FPS (blocking timeline frame rate). */
export const BLOCKING_FPS = 24;

/** Mirror of the core MAX_KEYPOSES bound. */
export const MAX_CONVERTED_KEYPOSES = 1000;

export interface BlockingInputKeypose {
  frame: number;
  pose: Record<string, Transform3D>;
  weight: number;
}

export interface BlockingInputPayload {
  skeleton?: SkeletonDoc;
  keyposes: BlockingInputKeypose[];
}

export interface NeutralMotionToBlockingResult {
  /** Converted payload JSON when input was a convertible doc, else null. */
  json: string | null;
  /** Human note when the input was a doc (converted or unconvertible), else null. */
  note: string | null;
}

/**
 * Heuristic: non-null object with a `frames` property that is an array, plus a
 * `skeleton` object or `meta` object present. This must NOT match a plain
 * BlockingInput payload (`{keyposes:[...]}`).
 */
export function isNeutralMotionDoc(payload: unknown): payload is NeutralMotionDoc {
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    return false;
  }
  const obj = payload as Record<string, unknown>;
  if (!Array.isArray(obj.frames)) {
    return false;
  }
  // Must NOT be a plain BlockingInput payload.
  if ("keyposes" in obj && !("meta" in obj) && !("skeleton" in obj)) {
    return false;
  }
  return "skeleton" in obj || "meta" in obj;
}

/**
 * Convert a NeutralMotionDoc into a valid BlockingInput payload.
 *
 * Returns null when the doc has no usable frames or keyposes.
 */
export function convertNeutralMotionToBlockingInput(
  doc: NeutralMotionDoc,
): BlockingInputPayload | null {
  type Candidate = { time: number; pose: Record<string, Transform3D>; weight: number };
  const candidates: Candidate[] = [];

  const authoredKeyPoses = doc.keyposes;
  if (Array.isArray(authoredKeyPoses) && authoredKeyPoses.length > 0) {
    // Authored keyposes: find matching frames in doc.frames.
    const frameByNumber = new Map<number, (typeof doc.frames)[number]>();
    for (const f of doc.frames) {
      if (typeof f.frame === "number") {
        frameByNumber.set(f.frame, f);
      }
    }
    for (const kp of authoredKeyPoses) {
      if (typeof kp.frame !== "number" || !Number.isInteger(kp.frame)) continue;
      const frame = frameByNumber.get(kp.frame);
      if (!frame) continue;
      if (!frame.pose?.transforms || Object.keys(frame.pose.transforms).length === 0) continue;
      candidates.push({
        time: frame.time,
        pose: frame.pose.transforms,
        weight: typeof kp.weight === "number" ? kp.weight : 1.0,
      });
    }
  } else {
    // No authored keyposes: sample frames.
    const frames = doc.frames;
    let selected: typeof frames;
    if (frames.length <= MAX_CONVERTED_KEYPOSES) {
      selected = frames;
    } else {
      const n = MAX_CONVERTED_KEYPOSES;
      const indices = Array.from({ length: n }, (_, i) =>
        Math.round((i * (frames.length - 1)) / (n - 1)),
      );
      selected = indices.map((i) => frames[i]);
    }
    for (const frame of selected) {
      if (!frame.pose?.transforms || Object.keys(frame.pose.transforms).length === 0) continue;
      candidates.push({ time: frame.time, pose: frame.pose.transforms, weight: 1.0 });
    }
  }

  if (candidates.length === 0) {
    return null;
  }

  // Rebase onto blocking timeline: sort by time, convert to blocking frames,
  // dedupe keeping the LAST entry per blocking frame.
  candidates.sort((a, b) => a.time - b.time);

  const deduped = new Map<number, Candidate>();
  for (const c of candidates) {
    const blockingFrame = Math.max(1, Math.round(c.time * BLOCKING_FPS));
    deduped.set(blockingFrame, c);
  }

  const keyposes: BlockingInputKeypose[] = [...deduped.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([frame, c]) => ({
      frame,
      pose: c.pose,
      weight: c.weight,
    }));

  if (keyposes.length === 0) {
    return null;
  }

  const payload: BlockingInputPayload = { keyposes };

  // Include skeleton only when the doc has a proper skeleton object.
  if (
    doc.skeleton &&
    typeof doc.skeleton === "object" &&
    doc.skeleton.bones &&
    typeof doc.skeleton.bones === "object"
  ) {
    payload.skeleton = doc.skeleton;
  }

  return payload;
}

/**
 * Parse a JSON string and attempt to convert a NeutralMotionDoc into a
 * BlockingInput payload.
 *
 * Returns `{ json: null, note: null }` when the input is not a doc (caller
 * should use the raw text). Returns a note when it IS a doc but conversion
 * failed or succeeded.
 */
export function neutralMotionToBlockingJson(
  text: string,
): NeutralMotionToBlockingResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { json: null, note: null };
  }

  if (!isNeutralMotionDoc(parsed)) {
    return { json: null, note: null };
  }

  const payload = convertNeutralMotionToBlockingInput(parsed);
  if (payload) {
    return {
      json: JSON.stringify(payload, null, 2),
      note: `Converted NeutralMotion doc → BlockingInput: ${payload.keyposes.length} keyposes, rebased to ${BLOCKING_FPS} fps.`,
    };
  }
  return {
    json: null,
    note: "Loaded file looks like a NeutralMotion doc but has no usable frames or keyposes to convert.",
  };
}
