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
import type { NodeSchema, DataType } from "../api/types";
import { portsCompatible } from "../core/ports";

export type FlowNodeData = {
  schema: NodeSchema;
  params: Record<string, unknown>;
  collapsed?: boolean;
};

export type FlowNode = Node<FlowNodeData, "schema">;

/** Build a unique node id prefixed by the node type (e.g. `video-source_ab12…`). */
export function newNodeId(type: string): string {
  const suffix = crypto.randomUUID().replace(/-/g, "").slice(0, 8);
  return `${type}_${suffix}`;
}

type Snapshot = { nodes: FlowNode[]; edges: Edge[] };

/** Active connection drag origin, used to give handles live validity feedback. */
export interface ConnectionOrigin {
  nodeId: string;
  handleId: string;
  handleType: "source" | "target";
  dataType: DataType;
}

const HISTORY_CAP = 50;

interface FlowState {
  nodes: FlowNode[];
  edges: Edge[];
  selectedNodeId: string | null;
  /** Transient inline hint shown in the canvas when a connection is rejected (EC-2). */
  connectionHint: string | null;
  /** Origin of an in-flight connection drag, or null when no drag is active (EC-2 s3). */
  connectionOrigin: ConnectionOrigin | null;
  historyPast: Snapshot[];
  historyFuture: Snapshot[];
  addNode: (schema: NodeSchema, position?: { x: number; y: number }) => void;
  updateParams: (nodeId: string, params: Record<string, unknown>) => void;
  removeNode: (id: string) => void;
  duplicateNode: (id: string) => void;
  toggleCollapse: (id: string) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  selectNode: (id: string | null) => void;
  clear: () => void;
  setLoaded: (nodes: FlowNode[], edges: Edge[]) => void;
  setConnectionHint: (hint: string | null) => void;
  setConnectionOrigin: (origin: ConnectionOrigin | null) => void;
  /** Record a pre-drag snapshot. Called once per drag start, NOT per position change. */
  commitHistory: () => void;
  undo: () => void;
  redo: () => void;
}

function snapshot(s: { nodes: FlowNode[]; edges: Edge[] }): Snapshot {
  return structuredClone({ nodes: s.nodes, edges: s.edges });
}

function pushPast(past: Snapshot[], snap: Snapshot): Snapshot[] {
  const next = [...past, snap];
  return next.length > HISTORY_CAP ? next.slice(next.length - HISTORY_CAP) : next;
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
  connectionHint: null,
  connectionOrigin: null,
  historyPast: [],
  historyFuture: [],

  addNode: (schema, position) => {
    const prev = snapshot(get());
    const fallback = { x: 80 + get().nodes.length * 20, y: 80 + get().nodes.length * 20 };
    const node: FlowNode = {
      id: newNodeId(schema.type),
      type: "schema",
      position: position ?? fallback,
      data: { schema, params: {} },
    };
    set((state) => ({
      nodes: [...state.nodes, node],
      historyPast: pushPast(state.historyPast, prev),
      historyFuture: [],
    }));
  },

  updateParams: (nodeId, params) => {
    const prev = snapshot(get());
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === nodeId ? { ...n, data: { ...n.data, params } } : n,
      ),
      historyPast: pushPast(state.historyPast, prev),
      historyFuture: [],
    }));
  },

  removeNode: (id) => {
    const prev = snapshot(get());
    set((state) => ({
      nodes: state.nodes.filter((n) => n.id !== id),
      edges: state.edges.filter((e) => e.source !== id && e.target !== id),
      historyPast: pushPast(state.historyPast, prev),
      historyFuture: [],
    }));
  },

  duplicateNode: (id) => {
    const { nodes } = get();
    const original = nodes.find((n) => n.id === id);
    if (!original) return;
    const prev = snapshot(get());
    const dup: FlowNode = {
      ...original,
      id: newNodeId(original.data.schema.type),
      position: { x: original.position.x + 40, y: original.position.y + 40 },
      data: { ...original.data, params: { ...original.data.params } },
    };
    set((state) => ({
      nodes: [...state.nodes, dup],
      historyPast: pushPast(state.historyPast, prev),
      historyFuture: [],
    }));
  },

  toggleCollapse: (id) => {
    const prev = snapshot(get());
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === id
          ? { ...n, data: { ...n.data, collapsed: !n.data.collapsed } }
          : n,
      ),
      historyPast: pushPast(state.historyPast, prev),
      historyFuture: [],
    }));
  },

  onNodesChange: (changes) => {
    const updated = applyNodeChanges(changes, get().nodes);
    set({ nodes: updated as unknown as FlowNode[] });
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
    const prev = snapshot(get());
    const edge: Edge = {
      id: `${connection.source}-${connection.sourceHandle}-${connection.target}-${connection.targetHandle}`,
      source: connection.source,
      sourceHandle: connection.sourceHandle,
      target: connection.target,
      targetHandle: connection.targetHandle,
    };
    set((state) => ({
      edges: addEdge(edge, state.edges),
      historyPast: pushPast(state.historyPast, prev),
      historyFuture: [],
    }));
  },

  selectNode: (id) => set({ selectedNodeId: id }),

  setConnectionHint: (hint) => set({ connectionHint: hint }),

  setConnectionOrigin: (origin) => set({ connectionOrigin: origin }),

  clear: () => {
    const prev = snapshot(get());
    set({
      nodes: [],
      edges: [],
      selectedNodeId: null,
      connectionHint: null,
      historyPast: pushPast(get().historyPast, prev),
      historyFuture: [],
    });
  },

  setLoaded: (nodes, edges) => {
    const prev = snapshot(get());
    set({
      nodes,
      edges,
      historyPast: pushPast(get().historyPast, prev),
      historyFuture: [],
    });
  },

  commitHistory: () => {
    const snap = snapshot(get());
    set((state) => ({
      historyPast: pushPast(state.historyPast, snap),
      historyFuture: [],
    }));
  },

  undo: () => {
    const { historyPast } = get();
    if (historyPast.length === 0) return;
    const past = [...historyPast];
    const restored = past.pop()!;
    const current = snapshot(get());
    set({
      nodes: structuredClone(restored.nodes),
      edges: structuredClone(restored.edges),
      historyPast: past,
      historyFuture: [...get().historyFuture, current],
    });
  },

  redo: () => {
    const { historyFuture } = get();
    if (historyFuture.length === 0) return;
    const future = [...historyFuture];
    const restored = future.pop()!;
    const current = snapshot(get());
    set({
      nodes: structuredClone(restored.nodes),
      edges: structuredClone(restored.edges),
      historyFuture: future,
      historyPast: pushPast(get().historyPast, current),
    });
  },
}));

export function getSchemaForPorts(
  nodes: FlowNode[],
  nodeId: string | undefined,
): NodeSchema | undefined {
  if (!nodeId) return undefined;
  return nodes.find((n) => n.id === nodeId)?.data.schema;
}
