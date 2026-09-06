import { useCallback, type DragEvent } from "react";
import {
  ReactFlow,
  Background,
  useReactFlow,
  type Edge,
  type IsValidConnection,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useFlowStore } from "../../state/useFlowStore";
import { usePaletteStore } from "../../state/usePaletteStore";
import { portsCompatible } from "../../core/ports";
import { findOutputPort, findInputPort } from "../../core/schema";
import { SchemaNode } from "./SchemaNode";

const nodeTypes: NodeTypes = { schema: SchemaNode };

/**
 * Schema-driven editor canvas (EC-1, EC-2).
 *
 * Renders the store's nodes/edges through React Flow using the custom
 * `SchemaNode`. Connection validity is gated by `portsCompatible` on the two
 * port schemas (source output vs. target input) — an incompatible drop is
 * rejected by React Flow before `onConnect`, and no edge is formed (EC-2).
 * Incompatible attempts also surface an inline hint (EC-2 s2).
 */
export function FlowCanvas() {
  const nodes = useFlowStore((s) => s.nodes);
  const edges = useFlowStore((s) => s.edges);
  const connectionHint = useFlowStore((s) => s.connectionHint);
  const onNodesChange = useFlowStore((s) => s.onNodesChange);
  const onEdgesChange = useFlowStore((s) => s.onEdgesChange);
  const onConnect = useFlowStore((s) => s.onConnect);
  const selectNode = useFlowStore((s) => s.selectNode);
  const setConnectionHint = useFlowStore((s) => s.setConnectionHint);
  const { screenToFlowPosition } = useReactFlow();

  const onDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback((e: DragEvent) => {
    e.preventDefault();
    const type = e.dataTransfer.getData("application/reactflow");
    if (!type) return;
    const catalog = usePaletteStore.getState().catalog;
    const schema = catalog.find((n) => n.type === type);
    if (!schema) return;
    const position = screenToFlowPosition({ x: e.clientX, y: e.clientY });
    useFlowStore.getState().addNode(schema, position);
  }, [screenToFlowPosition]);

  const isValidConnection: IsValidConnection<Edge> = useCallback((connection) => {
      if (!connection.source || !connection.target) return false;
      const srcHandle = connection.sourceHandle;
      const tgtHandle = connection.targetHandle;
      const flowNodes = useFlowStore.getState().nodes;
      const sourceNode = flowNodes.find((n) => n.id === connection.source);
      const targetNode = flowNodes.find((n) => n.id === connection.target);
      if (!sourceNode || !targetNode) return false;
      const srcPort = srcHandle
        ? findOutputPort(sourceNode.data.schema, srcHandle)
        : undefined;
      const tgtPort = tgtHandle
        ? findInputPort(targetNode.data.schema, tgtHandle)
        : undefined;
      if (!srcPort || !tgtPort) return false;
      const compatible = portsCompatible(srcPort.data_type, tgtPort.data_type);
      // EC-2 s2: rejected incompatible drop gets an inline hint, no edge.
      if (!compatible && srcPort && tgtPort) {
        useFlowStore
          .getState()
          .setConnectionHint(
            `Cannot connect ${srcPort.data_type} → ${tgtPort.data_type}: incompatible port types.`,
          );
      }
      return compatible;
    },
    [],
  );

  return (
    <div data-testid="flow-canvas" style={{ width: "100%", height: "100%" }}>
      {connectionHint ? (
        <div
          data-testid="connection-hint"
          role="status"
          style={{
            position: "absolute",
            top: "8px",
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 10,
            background: "#3d2f00",
            border: "1px solid #a16207",
            color: "#fbbf24",
            borderRadius: "4px",
            padding: "4px 12px",
            fontSize: "12px",
          }}
        >
          {connectionHint}
        </div>
      ) : null}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        isValidConnection={isValidConnection}
        onNodeClick={(_, node) => {
          selectNode(node.id);
          setConnectionHint(null);
        }}
        onPaneClick={() => {
          selectNode(null);
          setConnectionHint(null);
        }}
        onDrop={onDrop}
        onDragOver={onDragOver}
        fitView
      >
        <Background gap={16} color="#333" />
      </ReactFlow>
    </div>
  );
}
