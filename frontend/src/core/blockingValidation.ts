/**
 * Frontend mirror of the backend BlockingInput payload contract
 * (blocking-input rules: keyposes array, exact bone set per pose, unit
 * quaternions, unique frames, weights in [0, 1], no unknown fields).
 *
 * Pure module: no React, no DOM, no store access. Line numbers are 1-based and
 * computed best-effort from the raw text so the JSON editor can point the user
 * at the exact spot to fix.
 */
import { NEUTRAL_SKELETON_BONES } from "./blockingTemplate";

export interface BlockingValidationIssue {
  line: number | null;
  message: string;
}

export interface BlockingValidationResult {
  issues: BlockingValidationIssue[];
  parsed: Record<string, unknown> | null;
}

const ROTATION_TOLERANCE = 1e-3;
const MAX_KEYPOSES = 1000;

/**
 * Validate a blocking payload string against the backend rules. All issues are
 * collected in a single pass (no early return except when the text cannot be
 * structurally walked any further: unparseable, not an object, or a missing
 * `keyposes` array).
 */
export function validateBlockingPayload(text: string): BlockingValidationResult {
  const issues: BlockingValidationIssue[] = [];

  if (text.trim() === "") {
    return { issues: [{ line: 1, message: "blocking JSON is empty" }], parsed: null };
  }

  const lineStarts = computeLineStarts(text);

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      issues: [
        { line: parseErrorLine(text, lineStarts, message), message: `invalid JSON: ${message}` },
      ],
      parsed: null,
    };
  }

  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return {
      issues: [{ line: null, message: "payload must be a JSON object" }],
      parsed: parsed as Record<string, unknown> | null,
    };
  }

  const payload = parsed as Record<string, unknown>;

  // Mirror `extra="forbid"`: any unknown top-level field is an error.
  for (const key of Object.keys(payload)) {
    if (key !== "keyposes" && key !== "skeleton") {
      issues.push({
        line: lineOf(text, lineStarts, `"${key}"`),
        message: `unknown top-level field: ${key}`,
      });
    }
  }

  // Resolve the expected bone set: a custom skeleton's `bones` keys win,
  // otherwise the neutral 22-bone set. The frontend does not deeply validate a
  // custom skeleton's structure — only that keypose poses address that set.
  let expectedBones: readonly string[] | null = null;
  const skeleton = payload.skeleton;
  if (skeleton === undefined) {
    expectedBones = NEUTRAL_SKELETON_BONES;
  } else if (typeof skeleton !== "object" || skeleton === null || Array.isArray(skeleton)) {
    issues.push({ line: lineOf(text, lineStarts, '"skeleton"'), message: "skeleton must be an object" });
    expectedBones = NEUTRAL_SKELETON_BONES;
  } else {
    const bones = (skeleton as Record<string, unknown>).bones;
    if (typeof bones === "object" && bones !== null && !Array.isArray(bones)) {
      expectedBones = Object.keys(bones as Record<string, unknown>);
    } else {
      issues.push({ line: lineOf(text, lineStarts, '"bones"'), message: "skeleton.bones must be an object" });
      expectedBones = NEUTRAL_SKELETON_BONES;
    }
  }

  const keyposes = payload.keyposes;
  if (!Array.isArray(keyposes)) {
    issues.push({ line: lineOf(text, lineStarts, '"keyposes"'), message: "keyposes must be an array" });
    return { issues, parsed: payload };
  }
  if (keyposes.length < 1) {
    issues.push({ line: lineOf(text, lineStarts, '"keyposes"'), message: "keyposes must contain at least 1 keypose" });
  }
  if (keyposes.length > MAX_KEYPOSES) {
    issues.push({
      line: lineOf(text, lineStarts, '"keyposes"'),
      message: `keyposes must contain at most ${MAX_KEYPOSES} keyposes`,
    });
  }

  const seenFrames = new Set<number>();

  keyposes.forEach((kp, i) => {
    const kpNum = i + 1;
    // Keypose i maps to the i-th `"frame"` occurrence in the raw text.
    const kpLine = nthLineOf(text, lineStarts, '"frame"', i);
    const prefix = `keypose ${kpNum}:`;

    if (typeof kp !== "object" || kp === null || Array.isArray(kp)) {
      issues.push({ line: kpLine, message: `${prefix} must be an object` });
      return;
    }
    const keypose = kp as Record<string, unknown>;

    const frame = keypose.frame;
    if (typeof frame !== "number" || !Number.isInteger(frame) || frame < 1) {
      issues.push({ line: kpLine, message: `${prefix} frame must be an integer >= 1` });
    } else if (seenFrames.has(frame)) {
      issues.push({ line: kpLine, message: `${prefix} frame must be unique` });
    } else {
      seenFrames.add(frame);
    }

    if (keypose.weight !== undefined) {
      const w = keypose.weight;
      if (typeof w !== "number" || !Number.isFinite(w) || w < 0 || w > 1) {
        issues.push({ line: kpLine, message: `${prefix} weight must be a number in [0, 1]` });
      }
    }

    const pose = keypose.pose;
    if (pose === undefined) {
      issues.push({ line: kpLine, message: `${prefix} pose is required` });
      return;
    }
    if (typeof pose !== "object" || pose === null || Array.isArray(pose)) {
      issues.push({ line: kpLine, message: `${prefix} pose must be an object` });
      return;
    }
    const poseRecord = pose as Record<string, unknown>;

    if (expectedBones !== null) {
      const poseKeys = Object.keys(poseRecord);
      const missing = expectedBones.filter((b) => !poseKeys.includes(b)).sort();
      const extra = poseKeys.filter((b) => !expectedBones.includes(b)).sort();
      if (missing.length > 0 || extra.length > 0) {
        issues.push({
          line: kpLine,
          message:
            `${prefix} pose must name exactly the resolved skeleton bones; ` +
            `missing=[${missing.join(", ")}], extra=[${extra.join(", ")}]`,
        });
      }
    }

    for (const bone of Object.keys(poseRecord)) {
      const bonePrefix = `keypose ${kpNum} (${bone}):`;
      const transform = poseRecord[bone];
      if (typeof transform !== "object" || transform === null || Array.isArray(transform)) {
        issues.push({ line: kpLine, message: `${bonePrefix} transform must be an object` });
        continue;
      }
      const t = transform as Record<string, unknown>;

      if (!isFiniteNumberArray(t.translation, 3)) {
        issues.push({ line: kpLine, message: `${bonePrefix} translation must be 3 finite numbers` });
      }
      if (!isFiniteNumberArray(t.rotation, 4)) {
        issues.push({ line: kpLine, message: `${bonePrefix} rotation must be 4 finite numbers` });
      } else {
        const rotation = t.rotation as number[];
        const norm = Math.sqrt(rotation.reduce((sum, v) => sum + v * v, 0));
        if (Math.abs(norm - 1) > ROTATION_TOLERANCE) {
          issues.push({ line: kpLine, message: `${bonePrefix} rotation must be a unit quaternion` });
        }
      }
      if (!isFiniteNumberArray(t.scale, 3)) {
        issues.push({ line: kpLine, message: `${bonePrefix} scale must be 3 finite numbers` });
      }
    }
  });

  return { issues, parsed: payload };
}

function isFiniteNumberArray(value: unknown, length: number): value is number[] {
  return (
    Array.isArray(value) &&
    value.length === length &&
    value.every((n) => typeof n === "number" && Number.isFinite(n))
  );
}

/** Zero-based character offsets of the start of every line (1-based line n = starts[n-1]). */
function computeLineStarts(text: string): number[] {
  const starts = [0];
  for (let i = 0; i < text.length; i++) {
    if (text[i] === "\n") starts.push(i + 1);
  }
  return starts;
}

/** 1-based line number for a zero-based character index. */
function lineAt(lineStarts: number[], index: number): number {
  let lo = 0;
  let hi = lineStarts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (lineStarts[mid] <= index) lo = mid;
    else hi = mid - 1;
  }
  return lo + 1;
}

/** First line containing `needle`, or null when absent. */
function lineOf(text: string, lineStarts: number[], needle: string): number | null {
  const index = text.indexOf(needle);
  return index === -1 ? null : lineAt(lineStarts, index);
}

/** Line of the `nth` (0-based) occurrence of `needle`, or null when absent. */
function nthLineOf(text: string, lineStarts: number[], needle: string, nth: number): number | null {
  let index = -1;
  for (let n = 0; n <= nth; n++) {
    index = text.indexOf(needle, index + 1);
    if (index === -1) return null;
  }
  return lineAt(lineStarts, index);
}

/**
 * Approximate 1-based line of a JSON.parse failure. V8 versions report the
 * failure position in their error message ("at position N"); newer V8 (Node
 * 25+) does not, so we fall back to scanning the text for the first structural
 * violation, then to locating the quoted source snippet from the message.
 */
function parseErrorLine(text: string, lineStarts: number[], message: string): number | null {
  const legacy = /at position (\d+)/.exec(message);
  if (legacy) {
    const position = Math.min(Number(legacy[1]), Math.max(text.length - 1, 0));
    return lineAt(lineStarts, position);
  }
  const scanned = scanJsonErrorIndex(text);
  if (scanned !== null) return lineAt(lineStarts, scanned);
  const snippet = extractJsonMessageSnippet(message);
  if (snippet !== null) {
    const trimmed = snippet.replace(/^\.\.\./, "");
    const index = text.indexOf(trimmed);
    if (index !== -1) return lineAt(lineStarts, index);
  }
  return null;
}

/**
 * Best-effort structural JSON scanner that returns the character index of the
 * first place the text stops being valid JSON (or null when nothing obvious is
 * found). Mirrors the JSON grammar closely enough for error localization:
 * strings, numbers, literals, objects, arrays and trailing content.
 */
function scanJsonErrorIndex(text: string): number | null {
  let i = 0;
  const n = text.length;

  const skipWs = () => {
    while (i < n && (text[i] === " " || text[i] === "\t" || text[i] === "\n" || text[i] === "\r")) i++;
  };

  const scanString = (): boolean => {
    // text[i] is '"'
    i++;
    while (i < n) {
      const c = text[i];
      if (c === "\\") {
        i += 2;
        continue;
      }
      if (c === '"') {
        i++;
        return true;
      }
      i++;
    }
    return false; // unterminated
  };

  const scanNumber = (): boolean => {
    const start = i;
    if (text[i] === "-") i++;
    const digitStart = i;
    while (i < n && text[i] >= "0" && text[i] <= "9") i++;
    if (i === digitStart) {
      i = start;
      return false;
    }
    if (i - digitStart > 1 && text[digitStart] === "0") {
      i = start;
      return false; // leading zeros are not valid JSON
    }
    if (i < n && text[i] === ".") {
      i++;
      const fracStart = i;
      while (i < n && text[i] >= "0" && text[i] <= "9") i++;
      if (i === fracStart) {
        i = start;
        return false;
      }
    }
    if (i < n && (text[i] === "e" || text[i] === "E")) {
      i++;
      if (i < n && (text[i] === "+" || text[i] === "-")) i++;
      const expStart = i;
      while (i < n && text[i] >= "0" && text[i] <= "9") i++;
      if (i === expStart) {
        i = start;
        return false;
      }
    }
    return true;
  };

  const scanLiteral = (word: string): boolean => {
    if (text.startsWith(word, i)) {
      i += word.length;
      return true;
    }
    return false;
  };

  const scanValue = (): number | null => {
    skipWs();
    if (i >= n) return i; // unexpected end of input
    const c = text[i];
    if (c === '"') {
      if (!scanString()) return i; // unterminated string
    } else if (c === "{") {
      i++;
      skipWs();
      if (i < n && text[i] === "}") {
        i++;
      } else {
        for (;;) {
          skipWs();
          if (i >= n) return i;
          if (text[i] !== '"') return i; // expected property name
          if (!scanString()) return i;
          skipWs();
          if (i >= n || text[i] !== ":") return i; // expected colon
          i++;
          const err = scanValue();
          if (err !== null) return err;
          skipWs();
          if (i >= n) return i;
          if (text[i] === ",") {
            i++;
            continue;
          }
          if (text[i] === "}") {
            i++;
            break;
          }
          return i; // expected , or }
        }
      }
    } else if (c === "[") {
      i++;
      skipWs();
      if (i < n && text[i] === "]") {
        i++;
      } else {
        for (;;) {
          skipWs();
          if (i >= n) return i;
          const err = scanValue();
          if (err !== null) return err;
          skipWs();
          if (i >= n) return i;
          if (text[i] === ",") {
            i++;
            continue;
          }
          if (text[i] === "]") {
            i++;
            break;
          }
          return i; // expected , or ]
        }
      }
    } else if (c === "-" || (c >= "0" && c <= "9")) {
      if (!scanNumber()) return i;
    } else if (c === "t") {
      if (!scanLiteral("true")) return i;
    } else if (c === "f") {
      if (!scanLiteral("false")) return i;
    } else if (c === "n") {
      if (!scanLiteral("null")) return i;
    } else {
      return i; // unexpected token
    }
    return null;
  };

  const err = scanValue();
  if (err !== null) return err;
  skipWs();
  if (i < n) return i; // trailing content after the top-level value
  return null;
}

/** Decode the quoted source-snippet V8 embeds in newer error messages. */
function extractJsonMessageSnippet(message: string): string | null {
  const match = /"((?:\\.|[^"\\])*)"/.exec(message);
  if (!match) return null;
  return match[1].replace(/\\(.)/g, (_all, escaped: string) => {
    switch (escaped) {
      case "n":
        return "\n";
      case "t":
        return "\t";
      case "r":
        return "\r";
      case "b":
        return "\b";
      case "f":
        return "\f";
      case '"':
        return '"';
      case "\\":
        return "\\";
      default:
        return escaped;
    }
  });
}