import { useRef, useState } from "react";
import { useFlowStore } from "../../state/useFlowStore";
import { getDefaultedParams } from "../../core/schema";
import { validateVideoPath } from "../../core/videoPath";
import { buildBlockingTemplate } from "../../core/blockingTemplate";
import { neutralMotionToBlockingJson } from "../../core/neutralMotionToBlocking";
import { JsonBlockingEditor } from "./JsonBlockingEditor";

/**
 * Schema-driven properties panel (PP-1, PP-2).
 *
 * Renders the selected node's `params` from the live schema — never a
 * hardcoded field list. Param type maps to an input widget:
 *   number   → number input
 *   boolean  → checkbox
 *   string/video_path → text input
 * Defaults from the schema are applied when a value is unset. Edits write back
 * to the node's params via `useFlowStore.updateParams`. `video_path` values
 * that are absolute or contain `..` show a NON-BLOCKING warning (PP-2 s1) —
 * the core remains the enforcement boundary.
 */
export function PropertiesPanel() {
  const selectedNodeId = useFlowStore((s) => s.selectedNodeId);
  const nodes = useFlowStore((s) => s.nodes);
  const updateParams = useFlowStore((s) => s.updateParams);
  const fileInputs = useRef(new Map<string, HTMLInputElement>());
  const [convertNote, setConvertNote] = useState<string | null>(null);

  const node = nodes.find((n) => n.id === selectedNodeId);
  if (!node) return null;

  const schema = node.data.schema;
  const params = getDefaultedParams(schema, node.data.params);
  const nodeId = node.id;
  const nodeParams = node.data.params;

  function setParam(name: string, value: unknown) {
    updateParams(nodeId, { ...nodeParams, [name]: value });
  }

  async function loadJsonFile(name: string, file: File | undefined) {
    if (!file) return;
    let text: string;
    try {
      text = await file.text();
    } catch {
      return;
    }
    const conversion = neutralMotionToBlockingJson(text);
    if (conversion.json !== null) {
      setParam(name, conversion.json);
      setConvertNote(conversion.note);
    } else if (conversion.note !== null) {
      setConvertNote(conversion.note);
      // doc detected but unconvertible: do NOT clobber the current param value
    } else {
      setParam(name, text);
      setConvertNote(null);
    }
    const input = fileInputs.current.get(name);
    if (input) input.value = "";
  }

  function openFilePicker(name: string) {
    fileInputs.current.get(name)?.click();
  }

  function downloadTemplate() {
    const text = buildBlockingTemplate();
    const blob = new Blob([text], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "blocking-template.json";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  return (
    <div data-testid="properties-panel">
      <h3 style={{ fontSize: "14px", margin: "0 0 8px" }}>{schema.title}</h3>
      {schema.params.length === 0 && (
        <p style={{ color: "#888", fontSize: "12px" }}>No parameters</p>
      )}
      {schema.params.map((param) => {
        const value = params[param.name];
        const warn =
          param.data_type === "video_path"
            ? validateVideoPath(String(value ?? ""))
            : null;
        return (
          <div key={param.name} style={{ marginBottom: "8px" }}>
            <label
              htmlFor={`${node.id}-${param.name}`}
              style={{ display: "block", fontSize: "12px", marginBottom: "2px" }}
            >
              {param.name}
              {param.required ? <span style={{ color: "#c33" }}> *</span> : null}
            </label>
            {param.widget === "json" ? (
              <>
                <JsonBlockingEditor
                  testId={`param-${param.name}`}
                  value={value === undefined || value === null ? "" : String(value)}
                  onChange={(v) => {
                    setConvertNote(null);
                    setParam(param.name, v);
                  }}
                />
                {convertNote ? (
                  <span
                    data-testid="blocking-convert-note"
                    role="status"
                    style={{ display: "block", color: "#7cb342", fontSize: "11px", marginTop: "2px" }}
                  >
                    {convertNote}
                  </span>
                ) : null}
                <button
                  type="button"
                  data-testid={`param-load-${param.name}`}
                  onClick={() => openFilePicker(param.name)}
                  style={{
                    marginTop: 4,
                    fontSize: 12,
                    padding: "4px 10px",
                    cursor: "pointer",
                    background: "#2a2a2a",
                    color: "#ccc",
                    border: "1px solid #444",
                    borderRadius: 4,
                  }}
                >
                  Load JSON file
                </button>
                <button
                  type="button"
                  data-testid={`param-download-template-${param.name}`}
                  onClick={() => downloadTemplate()}
                  style={{
                    marginTop: 4,
                    marginLeft: 4,
                    fontSize: 12,
                    padding: "4px 10px",
                    cursor: "pointer",
                    background: "#2a2a2a",
                    color: "#8ab4f8",
                    border: "1px solid #555",
                    borderRadius: 4,
                  }}
                >
                  Download template
                </button>
                <input
                  ref={(el) => {
                    if (el) fileInputs.current.set(param.name, el);
                    else fileInputs.current.delete(param.name);
                  }}
                  data-testid={`param-file-${param.name}`}
                  type="file"
                  accept=".json,application/json,.txt"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    void loadJsonFile(param.name, e.target.files?.[0]);
                  }}
                />
              </>
            ) : param.data_type === "boolean" ? (
              <input
                id={`${node.id}-${param.name}`}
                data-testid={`param-${param.name}`}
                type="checkbox"
                checked={Boolean(value)}
                onChange={(e) => setParam(param.name, e.target.checked)}
                aria-label={param.name}
              />
            ) : param.data_type === "number" ? (
              <input
                id={`${node.id}-${param.name}`}
                data-testid={`param-${param.name}`}
                type="number"
                value={value === undefined || value === null ? "" : String(value)}
                onChange={(e) => {
                  const v = e.target.value;
                  setParam(param.name, v === "" ? undefined : Number(v));
                }}
                aria-label={param.name}
              />
            ) : (
              <input
                id={`${node.id}-${param.name}`}
                data-testid={`param-${param.name}`}
                type="text"
                value={value === undefined || value === null ? "" : String(value)}
                onChange={(e) => setParam(param.name, e.target.value)}
                aria-label={param.name}
              />
            )}
            {warn && !warn.valid ? (
              <span
                data-testid="video-path-warning"
                role="status"
                style={{ display: "block", color: "#b26a00", fontSize: "11px", marginTop: "2px" }}
              >
                {warn.warning}
              </span>
            ) : null}
            {param.description ? (
              <span style={{ display: "block", color: "#888", fontSize: "11px" }}>
                {param.description}
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
