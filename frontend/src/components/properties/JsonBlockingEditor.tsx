/**
 * Lightweight JSON editor widget for the blocking param (no external deps).
 *
 * Overlay pattern: a tokenized `<pre>` sits behind a transparent `<textarea>`
 * with identical font metrics; an `onScroll` handler copies the textarea's
 * scroll offsets onto the pre so the colored tokens stay aligned. Inline
 * validation runs the payload through `validateBlockingPayload` and surfaces
 * per-line errors (highlighted in the overlay) plus a click-to-jump issue
 * strip. A collapsible review view beneath the editor provides the honest
 * equivalent of in-text folding: keyposes collapse by default and expand into
 * a per-bone transform summary with per-keypose validation state.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode, UIEvent } from "react";
import { NEUTRAL_SKELETON_BONES } from "../../core/blockingTemplate";
import { validateBlockingPayload } from "../../core/blockingValidation";

export interface JsonBlockingEditorProps {
  value: string;
  onChange: (value: string) => void;
  testId?: string;
}

type TokenKind = "key" | "string" | "number" | "bool" | "punct" | "plain";

interface Token {
  kind: TokenKind;
  text: string;
}

const TOKEN_COLORS: Record<TokenKind, string> = {
  key: "#8ab4f8",
  string: "#9ccc65",
  number: "#f5a742",
  bool: "#c678dd",
  punct: "#666",
  plain: "#ccc",
};

const ERROR_LINE_BG = "rgba(220, 38, 38, 0.15)";
const FLASH_LINE_BG = "rgba(220, 38, 38, 0.35)";

const EDITOR_METRICS: CSSProperties = {
  fontFamily: "monospace",
  fontSize: 12,
  lineHeight: 1.5,
  padding: 4,
};

/**
 * Tokenize one line of JSON-ish text. Strings are checked for a following
 * `:` (after optional whitespace) to distinguish keys from string values.
 * Invalid fragments fall back to plain punctuation/plain coloring.
 */
function tokenizeLine(line: string): Token[] {
  const tokens: Token[] = [];
  const re =
    /"(?:\\.|[^"\\])*"|(-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)|(true|false|null)|[{}\[\],:]|(\s+)|(\S)/gy;
  let m: RegExpExecArray | null;
  while ((m = re.exec(line)) !== null) {
    const text = m[0];
    let kind: TokenKind;
    if (text.startsWith('"')) {
      const rest = line.slice(re.lastIndex);
      kind = /^\s*:/.test(rest) ? "key" : "string";
    } else if (m[1] !== undefined) {
      kind = "number";
    } else if (m[2] !== undefined) {
      kind = "bool";
    } else if (m[3] !== undefined) {
      kind = "plain";
    } else if (/[{}\[\],:]/.test(text)) {
      kind = "punct";
    } else {
      kind = "plain";
    }
    tokens.push({ kind, text });
  }
  return tokens;
}

function fmt2(n: number): string {
  return String(Math.round(n * 100) / 100);
}

function fmtList(vals: number[]): string {
  return vals.map(fmt2).join(",");
}

function asRecord(v: unknown): Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
}

function skeletonBonesOf(payload: Record<string, unknown>): string[] | null {
  const skeleton = payload.skeleton;
  if (typeof skeleton !== "object" || skeleton === null || Array.isArray(skeleton)) return null;
  const bones = (skeleton as Record<string, unknown>).bones;
  if (typeof bones !== "object" || bones === null || Array.isArray(bones)) return null;
  return Object.keys(bones as Record<string, unknown>);
}

function transformOf(v: unknown): { translation: number[]; rotation: number[]; scale: number[] } {
  const rec = asRecord(v);
  const numArr = (x: unknown, len: number): number[] =>
    Array.isArray(x)
      ? x.slice(0, len).filter((n): n is number => typeof n === "number")
      : [];
  return {
    translation: numArr(rec.translation, 3),
    rotation: numArr(rec.rotation, 4),
    scale: numArr(rec.scale, 3),
  };
}

export function JsonBlockingEditor({ value, onChange, testId = "json-editor" }: JsonBlockingEditorProps) {
  const preRef = useRef<HTMLPreElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [flashLine, setFlashLine] = useState<number | null>(null);
  const flashTimer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
    };
  }, []);

  const { issues, parsed } = useMemo(() => validateBlockingPayload(value), [value]);

  const errorLines = useMemo(() => {
    const linesWithErrors = new Set<number>();
    for (const issue of issues) {
      if (issue.line !== null) linesWithErrors.add(issue.line);
    }
    return linesWithErrors;
  }, [issues]);

  const keyposeIssueCounts = useMemo(() => {
    const counts = new Map<number, number>();
    for (const issue of issues) {
      const match = /^keypose (\d+)( |\(|:)/.exec(issue.message);
      if (match) {
        const n = Number(match[1]);
        counts.set(n, (counts.get(n) ?? 0) + 1);
      }
    }
    return counts;
  }, [issues]);

  const lines = useMemo(() => value.split("\n"), [value]);

  const overlayChildren = useMemo(() => {
    const children: ReactNode[] = [];
    lines.forEach((line, i) => {
      const lineNo = i + 1;
      const isError = errorLines.has(lineNo);
      const isFlash = flashLine === lineNo;
      children.push(
        <span
          key={`line-${lineNo}`}
          data-testid={`${testId}-line-${lineNo}`}
          style={
            isError || isFlash ? { backgroundColor: isFlash ? FLASH_LINE_BG : ERROR_LINE_BG } : undefined
          }
        >
          {tokenizeLine(line).map((token, j) => (
            <span key={j} style={{ color: TOKEN_COLORS[token.kind] }}>
              {token.text}
            </span>
          ))}
        </span>,
      );
      if (i < lines.length - 1) children.push("\n");
    });
    return children;
  }, [lines, errorLines, flashLine, testId]);

  function handleScroll(e: UIEvent<HTMLTextAreaElement>) {
    // Keep the colored overlay aligned with the transparent textarea.
    if (preRef.current) {
      preRef.current.scrollTop = e.currentTarget.scrollTop;
      preRef.current.scrollLeft = e.currentTarget.scrollLeft;
    }
  }

  function jumpToLine(line: number | null) {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.focus();
    if (line !== null) {
      const split = textarea.value.split("\n");
      const target = Math.min(Math.max(line, 1), split.length);
      let offset = 0;
      for (let i = 0; i < target - 1; i++) offset += split[i].length + 1;
      textarea.setSelectionRange(offset, offset);
      // Brief visual feedback: flash the offending line in the overlay.
      setFlashLine(target);
      if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
      flashTimer.current = window.setTimeout(() => setFlashLine(null), 600);
    }
  }

  let reviewBody: ReactNode;
  if (!parsed || !Array.isArray(parsed.keyposes)) {
    reviewBody = (
      <div style={{ fontSize: 12, color: "#888" }}>No valid keyposes array to review</div>
    );
  } else {
    const keyposes = parsed.keyposes as unknown[];
    const customBones = skeletonBonesOf(parsed);
    const expectedBones: readonly string[] = customBones ?? NEUTRAL_SKELETON_BONES;
    reviewBody = (
      <div style={{ marginTop: 4 }}>
        <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>
          {customBones
            ? `Skeleton: custom (${customBones.length} bones)`
            : `Skeleton: default neutral (${NEUTRAL_SKELETON_BONES.length} bones)`}
        </div>
        {keyposes.map((kpRaw, i) => {
          const kp = asRecord(kpRaw);
          const frame = typeof kp.frame === "number" ? kp.frame : null;
          const weight = typeof kp.weight === "number" ? kp.weight : 1;
          const pose = asRecord(kp.pose);
          const poseKeys = Object.keys(pose);
          const missing = expectedBones.filter((b) => !poseKeys.includes(b));
          const extra = poseKeys.filter((b) => !expectedBones.includes(b));
          const issueCount = keyposeIssueCounts.get(i + 1) ?? 0;
          return (
            <details key={i} data-testid={`${testId}-keypose-${i}`} style={{ marginBottom: 4 }}>
              <summary style={{ fontSize: 12, cursor: "pointer", color: "#ccc" }}>
                {`Keypose ${i + 1} \u00b7 frame ${frame ?? "?"} \u00b7 weight ${fmt2(weight)}`}{" "}
                {issueCount === 0 ? (
                  <span style={{ color: "#66bb6a" }}>{"\u2713 valid"}</span>
                ) : (
                  <span style={{ color: "#f57c00" }}>
                    {issueCount === 1 ? "! 1 issue" : `! ${issueCount} issues`}
                  </span>
                )}
              </summary>
              <div style={{ paddingLeft: 12 }}>
                {poseKeys.map((bone) => {
                  const tr = transformOf(pose[bone]);
                  const isExtra = extra.includes(bone);
                  return (
                    <div
                      key={bone}
                      style={{
                        fontFamily: "monospace",
                        fontSize: 11,
                        color: isExtra ? "#888" : "#ccc",
                      }}
                    >
                      {`${bone}: t[${fmtList(tr.translation)}] r[${fmtList(tr.rotation)}] s[${fmtList(tr.scale)}]`}
                    </div>
                  );
                })}
                {missing.map((bone) => (
                  <div
                    key={`missing-${bone}`}
                    style={{ fontFamily: "monospace", fontSize: 11, color: "#e57373" }}
                  >
                    {`${bone}: (missing)`}
                  </div>
                ))}
              </div>
            </details>
          );
        })}
      </div>
    );
  }

  return (
    <div data-testid={testId}>
      <div style={{ background: "#1a1a1a", border: "1px solid #444", borderRadius: 4 }}>
        <div style={{ position: "relative" }}>
          <pre
            ref={preRef}
            aria-hidden="true"
            data-testid={`${testId}-overlay`}
            style={{
              ...EDITOR_METRICS,
              position: "absolute",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              margin: 0,
              overflow: "hidden",
              pointerEvents: "none",
              whiteSpace: "pre",
              color: "#ccc",
            }}
          >
            {overlayChildren}
          </pre>
          <textarea
            ref={textareaRef}
            data-testid={`${testId}-textarea`}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onScroll={handleScroll}
            spellCheck={false}
            wrap="off"
            style={{
              ...EDITOR_METRICS,
              position: "relative",
              width: "100%",
              boxSizing: "border-box",
              background: "transparent",
              color: "transparent",
              caretColor: "#ccc",
              border: "none",
              outline: "none",
              resize: "vertical",
              whiteSpace: "pre",
            }}
          />
        </div>
      </div>
      {issues.length > 0 ? (
        <div data-testid={`${testId}-issues`} style={{ marginTop: 4 }}>
          <div style={{ fontSize: 12, color: "#e57373" }}>
            {issues.length === 1 ? "1 issue" : `${issues.length} issues`}
          </div>
          {issues.map((issue, idx) => (
            <button
              key={idx}
              type="button"
              data-testid={`${testId}-issue-${idx}`}
              onClick={() => jumpToLine(issue.line)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                background: "transparent",
                border: "none",
                padding: "2px 0",
                cursor: "pointer",
                fontFamily: "inherit",
                fontSize: 12,
                color: "#e57373",
              }}
            >
              <span style={{ color: "#888", marginRight: 6 }}>
                {issue.line !== null ? `L${issue.line}` : "\u2014"}
              </span>
              {issue.message}
            </button>
          ))}
        </div>
      ) : null}
      <details data-testid={`${testId}-review`} style={{ marginTop: 8 }}>
        <summary style={{ fontSize: 12, color: "#8ab4f8", cursor: "pointer" }}>
          Review keyposes
        </summary>
        {reviewBody}
      </details>
    </div>
  );
}