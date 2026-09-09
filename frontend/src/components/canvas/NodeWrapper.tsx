import { memo, type ReactNode } from "react";
import { Handle, Position, useNodeId } from "@xyflow/react";
import type { DataType } from "../../api/types";
import { getHandleColor } from "../../core/handles";
import { portsCompatible } from "../../core/ports";
import { useFlowStore } from "../../state/useFlowStore";

interface PortInfo {
  name: string;
  data_type: DataType;
}

interface NodeWrapperProps {
  def: { color: string; label: string };
  selected: boolean;
  style?: React.CSSProperties;
  children?: ReactNode;
  inputs?: PortInfo[];
  outputs?: PortInfo[];
}

export const NodeWrapper = memo(function NodeWrapper({
  def,
  selected,
  style,
  children,
  inputs = [],
  outputs = [],
}: NodeWrapperProps) {
  const nodeId = useNodeId();
  const nodes = useFlowStore((s) => s.nodes);
  const selectNode = useFlowStore((s) => s.selectNode);
  const toggleCollapse = useFlowStore((s) => s.toggleCollapse);
  const duplicateNode = useFlowStore((s) => s.duplicateNode);
  const removeNode = useFlowStore((s) => s.removeNode);
  const connectionOrigin = useFlowStore((s) => s.connectionOrigin);

  const self = nodes.find((n) => n.id === nodeId);
  const collapsed = Boolean(self?.data.collapsed);

  /**
   * EC-2 s3: live handle feedback while a connection drag is in flight.
   * A compatible opposite-type handle glows green; an incompatible one dims
   * and refuses the drop cursor. No feedback when nothing is being dragged.
   */
  function handleFeedback(
    portType: "source" | "target",
    dataType: DataType,
  ): { dimmed: boolean; compatible: boolean } {
    if (!connectionOrigin || connectionOrigin.nodeId === nodeId) {
      return { dimmed: false, compatible: false };
    }
    const draggingSource = connectionOrigin.handleType === "source";
    // Only the opposite handle type of the drag is a potential drop target.
    if (draggingSource === (portType === "source")) {
      return { dimmed: false, compatible: false };
    }
    const compatible = draggingSource
      ? portsCompatible(connectionOrigin.dataType, dataType)
      : portsCompatible(dataType, connectionOrigin.dataType);
    return { dimmed: !compatible, compatible };
  }

  const handleCollapse = () => {
    if (!nodeId) return;
    selectNode(nodeId);
    toggleCollapse(nodeId);
  };

  const handleDuplicate = () => {
    if (!nodeId) return;
    selectNode(nodeId);
    duplicateNode(nodeId);
  };

  const handleDelete = () => {
    if (!nodeId) return;
    selectNode(nodeId);
    removeNode(nodeId);
  };

  return (
    <div
      data-testid="schema-node"
      style={{
        background: "#1a1a1a",
        border: selected ? "1px solid #60a5fa" : "1px solid #333",
        borderRadius: 8,
        position: "relative",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        width: 260,
        height: collapsed ? 36 : 320,
        ...style,
      }}
    >
      {/* ── Header ─────────────────────────────────────── */}
      <div
        style={{
          background: def.color,
          padding: "3px 8px",
          fontSize: 10,
          fontWeight: 600,
          display: "flex",
          alignItems: "center",
          gap: 6,
          borderRadius: collapsed ? "8px" : "8px 8px 0 0",
          flexShrink: 0,
          height: 30,
        }}
      >
        <span
          style={{
            flex: 1,
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            color: "#fff",
          }}
        >
          {def.label}
        </span>
        <button
          onClick={(e) => {
            e.stopPropagation();
            handleCollapse();
          }}
          style={{
            background: "rgba(0,0,0,0.2)",
            border: "none",
            borderRadius: 3,
            color: "#fff",
            fontSize: 11,
            lineHeight: 1,
            padding: "2px 5px",
            cursor: "pointer",
            opacity: 0.75,
          }}
          title={collapsed ? "Expand" : "Collapse"}
        >
          {collapsed ? "◻" : "▣"}
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            handleDuplicate();
          }}
          style={{
            background: "rgba(0,0,0,0.2)",
            border: "none",
            borderRadius: 3,
            color: "#fff",
            fontSize: 11,
            lineHeight: 1,
            padding: "2px 5px",
            cursor: "pointer",
            opacity: 0.75,
          }}
          title="Duplicate"
        >
          ⎘
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            handleDelete();
          }}
          style={{
            background: "rgba(220,38,38,0.4)",
            border: "none",
            borderRadius: 3,
            color: "#fff",
            fontSize: 11,
            lineHeight: 1,
            padding: "2px 5px",
            cursor: "pointer",
            opacity: 0.75,
          }}
          title="Delete"
        >
          ✕
        </button>
      </div>

      {!collapsed && (
        <>
          {/* ── Handle row ─────────────────────────────── */}
          {(inputs.length > 0 || outputs.length > 0) && (
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                padding: "4px 8px",
                borderBottom: "1px solid #2a2a2a",
                flexShrink: 0,
                gap: 8,
                background: "#1a1a1a",
              }}
            >
              {/* Inputs (left) */}
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "flex-start",
                  gap: 4,
                }}
              >
                {inputs.map((port) => {
                  const { dimmed, compatible } = handleFeedback(
                    "target",
                    port.data_type,
                  );
                  return (
                    <div
                      key={port.name}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 4,
                        opacity: dimmed ? 0.35 : undefined,
                        transition: "opacity 120ms ease",
                      }}
                    >
                      <Handle
                        type="target"
                        position={Position.Left}
                        id={port.name}
                        data-testid="schema-input-handle"
                        data-valid={compatible ? "true" : undefined}
                        data-invalid={dimmed ? "true" : undefined}
                        style={{
                          position: "static",
                          width: 8,
                          height: 8,
                          background: getHandleColor(port.data_type),
                          border: "none",
                          borderRadius: "50%",
                          transform: "none",
                          flexShrink: 0,
                          cursor: dimmed ? "not-allowed" : undefined,
                          boxShadow: compatible
                            ? "0 0 6px 1px rgba(74, 222, 128, 0.9)"
                            : undefined,
                        }}
                      />
                      <span
                        style={{
                          fontSize: 9,
                          color: "#ccc",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {port.name}
                      </span>
                    </div>
                  );
                })}
              </div>

              {/* Outputs (right) */}
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "flex-end",
                  gap: 4,
                }}
              >
                {outputs.map((port) => {
                  const { dimmed, compatible } = handleFeedback(
                    "source",
                    port.data_type,
                  );
                  return (
                    <div
                      key={port.name}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 4,
                        opacity: dimmed ? 0.35 : undefined,
                        transition: "opacity 120ms ease",
                      }}
                    >
                      <span
                        style={{
                          fontSize: 9,
                          color: "#ccc",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {port.name}
                      </span>
                      <Handle
                        type="source"
                        position={Position.Right}
                        id={port.name}
                        data-testid="schema-output-handle"
                        data-valid={compatible ? "true" : undefined}
                        data-invalid={dimmed ? "true" : undefined}
                        style={{
                          position: "static",
                          width: 8,
                          height: 8,
                          background: getHandleColor(port.data_type),
                          border: "none",
                          borderRadius: "50%",
                          transform: "none",
                          flexShrink: 0,
                          cursor: dimmed ? "not-allowed" : undefined,
                          boxShadow: compatible
                            ? "0 0 6px 1px rgba(74, 222, 128, 0.9)"
                            : undefined,
                        }}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Body (scrollable) ─────────────────────── */}
          <div
            style={{
              flex: 1,
              minHeight: 0,
              overflowY: "auto",
              overflowX: "hidden",
              position: "relative",
              padding: "6px 8px",
            }}
          >
            {children}
          </div>
        </>
      )}
    </div>
  );
});
