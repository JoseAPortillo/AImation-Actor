import { memo } from "react";
import type { NodeProps } from "@xyflow/react";
import type { FlowNode } from "../../state/useFlowStore";
import { useFlowStore } from "../../state/useFlowStore";
import { getCategoryColor } from "../../core/handles";
import { NodeWrapper } from "./NodeWrapper";
import { CollapsibleSection } from "./CollapsibleSection";

type Props = NodeProps<FlowNode>;

/**
 * Schema-driven custom node — AImation dark-theme variant.
 *
 * Renders EXACTLY one Handle per schema port: inputs use `target` handles and
 * outputs use `source` handles, with `id` = the port name (used by
 * `onConnect`/`isValidConnection` to resolve the port). There are NO ghost
 * ports — the handles come straight from `/nodes/types` schema, never a
 * hardcoded list. RF-internal `data-testid` classes are hidden behind the
 * semantic `data-testid="schema-input-handle|schema-output-handle"` attributes
 * so tests can assert behavior, not CSS.
 */
export const SchemaNode = memo(function SchemaNode({
  id,
  data,
  selected,
}: Props) {
  const { schema, params } = data;
  const updateParams = useFlowStore((s) => s.updateParams);

  const handleParamChange = (paramName: string, value: unknown) => {
    updateParams(id, { ...params, [paramName]: value });
  };

  return (
    <NodeWrapper
      def={{ color: getCategoryColor(schema.category), label: schema.title }}
      selected={selected}
      inputs={schema.inputs.map((p) => ({
        name: p.name,
        data_type: p.data_type,
      }))}
      outputs={schema.outputs.map((p) => ({
        name: p.name,
        data_type: p.data_type,
      }))}
    >
      {/* Description */}
      {schema.description && (
        <div style={{ fontSize: 10, color: "#888", marginBottom: 4 }}>
          {schema.description}
        </div>
      )}

      {/* Parameters section */}
      {schema.params.length > 0 ? (
        <CollapsibleSection title="Parámetros" defaultOpen={true}>
          {schema.params.map((param) => {
            const currentValue = (params[param.name] ?? param.default ?? "") as
              | string
              | number;
            return (
              <div
                key={param.name}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 1,
                  marginBottom: 4,
                }}
              >
                <label
                  style={{
                    fontSize: 9,
                    color: "#999",
                    textTransform: "capitalize",
                  }}
                >
                  {param.name}
                </label>
              {param.data_type === "video_path" || param.data_type === "image" ? (
                <FileParam
                  paramName={param.name}
                  dataType={param.data_type}
                  value={currentValue}
                  onChange={(v) => handleParamChange(param.name, v)}
                />
              ) : param.data_type === "boolean" ? (
                  <input
                    type="checkbox"
                    checked={Boolean(currentValue)}
                    onChange={(e) =>
                      handleParamChange(param.name, e.target.checked)
                    }
                    style={{
                      background: "#2a2a2a",
                      border: "1px solid #444",
                      borderRadius: 3,
                      color: "#ccc",
                      fontSize: 10,
                      width: "fit-content",
                    }}
                  />
                ) : (
                  <input
                    type={param.data_type === "number" ? "number" : "text"}
                    value={currentValue}
                    onChange={(e) => {
                      const val =
                        param.data_type === "number"
                          ? parseFloat(e.target.value) || 0
                          : e.target.value;
                      handleParamChange(param.name, val);
                    }}
                    style={{
                      background: "#2a2a2a",
                      border: "1px solid #444",
                      borderRadius: 3,
                      color: "#ccc",
                      fontSize: 10,
                      padding: "2px 4px",
                      width: "100%",
                      boxSizing: "border-box",
                    }}
                  />
                )}
              </div>
            );
          })}
        </CollapsibleSection>
      ) : (
        <div style={{ fontSize: 9, color: "#666", marginTop: 4 }}>
          Sin parámetros
        </div>
      )}
    </NodeWrapper>
  );
});

export default SchemaNode;

function FileParam({
  paramName,
  dataType,
  value,
  onChange,
}: {
  paramName: string;
  dataType: "video_path" | "image";
  value: unknown;
  onChange: (next: string) => void;
}) {
  const src = typeof value === "string" && value ? value : undefined;
  const isVideo = dataType === "video_path";
  const accept = isVideo ? "video/*,image/*" : "image/*";

  const handleFile = (file: File | undefined) => {
    if (!file) return;
    onChange(URL.createObjectURL(file));
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {src && (
        <div data-testid="schema-node-preview">
          {isVideo ? (
            <video
              data-testid="schema-video-preview"
              src={src}
              controls
              style={{ width: "100%", maxHeight: 120 }}
            />
          ) : (
            <img
              data-testid="schema-image-preview"
              src={src}
              alt={paramName}
              style={{ width: "100%" }}
            />
          )}
        </div>
      )}
      <label
        data-testid="schema-video-input"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 2,
          alignItems: "stretch",
        }}
      >
        <span
          style={{
            fontSize: 9,
            color: "#60a5fa",
            cursor: "pointer",
            border: "1px dashed #444",
            borderRadius: 3,
            padding: "3px 4px",
            textAlign: "center",
          }}
        >
          {src ? "Re-select file" : "Select file"}
        </span>
        <input
          type="file"
          accept={accept}
          style={{ display: "none" }}
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
      </label>
    </div>
  );
}
