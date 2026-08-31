import { useFlowStore } from "../../state/useFlowStore";
import { getDefaultedParams } from "../../core/schema";
import { validateVideoPath } from "../../core/videoPath";

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

  const node = nodes.find((n) => n.id === selectedNodeId);
  if (!node) return null;

  const schema = node.data.schema;
  const params = getDefaultedParams(schema, node.data.params);
  const nodeId = node.id;
  const nodeParams = node.data.params;

  function setParam(name: string, value: unknown) {
    updateParams(nodeId, { ...nodeParams, [name]: value });
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
            {param.data_type === "boolean" ? (
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
