import { create } from "zustand";
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
} from "@xyflow/react";
import type { NodeSchema } from "../api/types";
import { portsCompatible } from "../core/ports";

export interface FlowNodeData {
  schema: NodeSchema;
  params: Record<string, unknown>;
}

export type FlowNode = Node<FlowNodeData>;

/** Build a unique node id prefixed by the node type (e.g. `video-source_ab12…`). */
export function newNodeId(type: string): string {
  const suffix = crypto.randomUUID().replace(/-/g, "").slice(0, 8);
  return `${type}_${suffix}`;
}

interface FlowState {
  nodes: FlowNode[];
  edges: Edge[];
  selectedNodeId: string | null;
  addNode: (schema: NodeSchema) => void;
  updateParams: (nodeId: string, params: Record<string, unknown>) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  selectNode: (id: string | null) => void;
  clear: () => void;
  setLoaded: (nodes: FlowNode[], edges: Edge[]) => void;
}

/**
 * Flow store holding the React Flow canvas state (in-memory node/edge graph).
 * `addNode` and `onConnect` enforce the schema-driven port contract (NP-2,
 * EC-2); nothing here persists to storage.
 */
export const useFlowStore = create<FlowState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,

  addNode: (schema) => {
    const node: FlowNode = {
      id: newNodeId(schema.type),
      type: "schema",
      position: { x: 80 + get().nodes.length * 20, y: 80 + get().nodes.length * 20 },
      data: { schema, params: {} },
    };
    set((state) => ({ nodes: [...state.nodes, node] }));
  },

  updateParams: (nodeId, params) => {
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === nodeId ? { ...n, data: { ...n.data, params } } : n,
      ),
    }));
  },

  onNodesChange: (changes) => {
    set({ nodes: applyNodeChanges(changes, get().nodes) as FlowNode[] });
  },

  onEdgesChange: (changes) => {
    set({ edges: applyEdgeChanges(changes, get().edges) });
  },

  onConnect: (connection) => {
    if (!connection.source || !connection.target) return;
    const { nodes } = get();
    const source = nodes.find((n) => n.id === connection.source);
    const target = nodes.find((n) => n.id === connection.target);
    if (!source || !target) return;
    const srcPort = source.data.schema.outputs.find((p) => p.name === connection.sourceHandle);
    const dstPort = target.data.schema.inputs.find((p) => p.name === connection.targetHandle);
    if (!srcPort || !dstPort) return;
    if (!portsCompatible(srcPort.data_type, dstPort.data_type)) return;
    const edge: Edge = {
      id: `${connection.source}-${connection.sourceHandle}-${connection.target}-${connection.targetHandle}`,
      source: connection.source,
      sourceHandle: connection.sourceHandle,
      target: connection.target,
      targetHandle: connection.targetHandle,
    };
    set({ edges: addEdge(edge, get().edges) });
  },

  selectNode: (id) => set({ selectedNodeId: id }),

  clear: () => set({ nodes: [], edges: [], selectedNodeId: null }),

  setLoaded: (nodes, edges) => set({ nodes, edges }),
}));

export function getSchemaForPorts(
  nodes: FlowNode[],
  nodeId: string | undefined,
): NodeSchema | undefined {
  if (!nodeId) return undefined;
  return nodes.find((n) => n.id === nodeId)?.data.schema;
}
