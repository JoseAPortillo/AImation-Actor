import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { FlowNode } from "../../state/useFlowStore";

type Props = NodeProps<FlowNode>;

/**
 * Schema-driven custom node (EC-1).
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
  data,
  selected,
}: Props) {
  const { schema, params } = data;
  return (
    <div
      data-testid="schema-node"
      style={{
        border: "1px solid #888",
        borderRadius: "8px",
        padding: "8px 12px",
        background: selected ? "#e8f0fe" : "#fff",
        minWidth: "140px",
      }}
    >
      {schema.inputs.map((port) => (
        <Handle
          key={port.name}
          id={port.name}
          type="target"
          position={Position.Left}
          data-testid="schema-input-handle"
        />
      ))}
      <div style={{ fontSize: "12px", fontWeight: 600 }}>{schema.title}</div>
      <div style={{ fontSize: "10px", color: "#666", marginTop: "2px" }}>
        {Object.keys(params).length > 0
          ? Object.entries(params)
              .map(([k, v]) => `${k}=${String(v)}`)
              .join(" · ")
          : ""
        }
      </div>
      {schema.outputs.map((port) => (
        <Handle
          key={port.name}
          id={port.name}
          type="source"
          position={Position.Right}
          data-testid="schema-output-handle"
        />
      ))}
    </div>
  );
});

export default SchemaNode;
