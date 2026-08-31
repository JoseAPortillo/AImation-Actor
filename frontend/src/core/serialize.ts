/**
 * Canonical `.aimgraph` v1.0 serializer (AR-1, AR-2).
 *
 * Emits the EXACT core contract with a stable key order mirroring
 * `cli.py::_save_pretty_json` (json.dumps indent=2 + trailing newline):
 *   graph : version → nodes → edges
 *   node  : id → type → params
 *   edge  : id → source → target
 *   PortRef: node → port
 * Layout rides ONLY as whitelisted extras (`position` on nodes, `viewport` on
 * the graph). React Flow internals (`measured`, `__rf`) are stripped so they
 * never leak into the canonical bytes (AR-2 golden).
 */

import type { AimEdge, AimGraph, AimNode, PortRef } from "./graph";
import type { FlowNode } from "../state/useFlowStore";
import { useFlowStore } from "../state/useFlowStore";
import type { NodeSchema } from "../api/types";

const LAYOUT_GRAPH_EXTRAS = ["viewport"] as const;
const LAYOUT_NODE_EXTRAS = ["position"] as const;
const RF_INTERNAL_KEY = /^(__rf|measured)$/;

/** Whitelisted layout extras that survive canonicalization. */
function isExtAllowed(key: string, kind: "graph" | "node"): boolean {
  const allowed = kind === "graph" ? LAYOUT_GRAPH_EXTRAS : LAYOUT_NODE_EXTRAS;
  return (allowed as readonly string[]).includes(key);
}

function canonicalizeNode(node: AimNode): AimNode {
  const out: AimNode = { id: node.id, type: node.type, params: node.params };
  for (const key of Object.keys(node)) {
    if (isExtAllowed(key, "node")) {
      (out as Record<string, unknown>)[key] = node[key];
    }
  }
  return out;
}

function canonicalizeEdge(edge: AimEdge): AimEdge {
  return { id: edge.id, source: edge.source, target: edge.target };
}

/**
 * Produce the structural canonical graph: RF internals stripped, layout extras
 * kept, canonical node/edge shape enforced. Used before serialization (AR-1).
 */
export function toCanonicalAimGraph(graph: AimGraph): AimGraph {
  const canonical: AimGraph = {
    version: "1.0",
    nodes: graph.nodes.map(canonicalizeNode),
    edges: graph.edges.map(canonicalizeEdge),
  };
  for (const key of Object.keys(graph)) {
    if (key === "version" || key === "nodes" || key === "edges") continue;
    if (RF_INTERNAL_KEY.test(key)) continue;
    if (isExtAllowed(key, "graph")) {
      (canonical as Record<string, unknown>)[key] = graph[key];
    }
  }
  return canonical;
}

/** Build a canonical PortRef. */
function portRef(p: PortRef): PortRef {
  return { node: p.node, port: p.port };
}

/**
 * Serialize an AimGraph to canonical JSON bytes: 2-space indent + trailing
 * newline, exact key order (AR-1, AR-2). Layout extras may ride as whitelisted
 * extras; RF internals are stripped.
 */
export function serializeGraph(graph: AimGraph): string {
  const c = toCanonicalAimGraph(graph);
  const serialized: Record<string, unknown> = {
    version: c.version,
    nodes: c.nodes.map((n) => {
      const node: Record<string, unknown> = { id: n.id, type: n.type, params: n.params };
      for (const key of Object.keys(n)) {
        if (!["id", "type", "params"].includes(key)) {
          node[key] = n[key as keyof AimNode];
        }
      }
      return node;
    }),
    edges: c.edges.map((e) => ({
      id: e.id,
      source: portRef(e.source),
      target: portRef(e.target),
    })),
  };
  for (const key of Object.keys(c)) {
    if (["version", "nodes", "edges"].includes(key)) continue;
    serialized[key] = c[key as keyof AimGraph];
  }
  return JSON.stringify(serialized, null, 2) + "\n";
}

export interface ParseResult {
  ok: boolean;
  graph?: AimGraph;
  error?: string;
}

/**
 * Parse canonical `.aimgraph` JSON. Rejects malformed JSON and unsupported
 * versions (e.g. stale v0.1) — the loaded graph is never mutated on rejection
 * (AR-2 s3). Structural validation is minimal: version must be "1.0".
 */
export function parseGraph(text: string): ParseResult {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return { ok: false, error: "invalid JSON" };
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return { ok: false, error: "graph must be a JSON object" };
  }
  const version = (raw as { version?: unknown }).version;
  if (version !== "1.0") {
    return { ok: false, error: `unsupported version: ${String(version)}` };
  }
  const graph = raw as AimGraph;
  if (!Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) {
    return { ok: false, error: "graph must contain nodes and edges arrays" };
  }
  return { ok: true, graph };
}

/**
 * Convert the React Flow store (nodes/edges) into an AimGraph (AR-1).
 * Node `data.type` maps to the AimNode `type`; `params` come from
 * `data.params`; `position` rides as a whitelisted layout extra. RF edges map
 * to PortRef source/target using their handle ids as port names.
 */
export function fromFlow(
  nodes: FlowNode[],
  edges: { id: string; source: string; sourceHandle?: string | null; target: string; targetHandle?: string | null }[],
): AimGraph {
  const aimNodes: AimNode[] = nodes.map((n) => {
    const node: AimNode = { id: n.id, type: n.data.schema.type, params: n.data.params };
    if (n.position) node.position = { x: n.position.x, y: n.position.y };
    return node;
  });
  const aimEdges: AimEdge[] = edges.map((e) => ({
    id: e.id,
    source: { node: e.source, port: String(e.sourceHandle) },
    target: { node: e.target, port: String(e.targetHandle) },
  }));
  return { version: "1.0", nodes: aimNodes, edges: aimEdges };
}

/** Look up a NodeSchema by its `type` from the catalog. */
function findSchemaByType(catalog: NodeSchema[], type: string): NodeSchema | undefined {
  return catalog.find((s) => s.type === type);
}

/**
 * Convert a canonical AimGraph into React Flow nodes/edges (load path).
 * Each AimNode becomes a `schema` node with its schema and params; port refs on
 * edges recover the RF source/sourceHandle/target/targetHandle shape.
 */
export function toFlow(
  graph: AimGraph,
  catalog: NodeSchema[],
  getPosition?: (index: number, node: AimNode) => { x: number; y: number },
): { nodes: FlowNode[]; edges: { id: string; source: string; sourceHandle: string; target: string; targetHandle: string }[] } {
  const nodes: FlowNode[] = graph.nodes.map((n, index) => {
    const known = findSchemaByType(catalog, n.type);
    const schema: NodeSchema = known ?? {
      type: n.type,
      category: "unknown" as NodeSchema["category"],
      title: n.type,
      description: "",
      inputs: [],
      outputs: [],
      params: [],
    };
    const pos = n.position;
    const position: { x: number; y: number } =
      pos && typeof pos === "object" && "x" in pos && "y" in pos
        ? (pos as { x: number; y: number })
        : getPosition?.(index, n) ?? { x: 0, y: 0 };
    return {
      id: n.id,
      type: "schema",
      position,
      data: { schema, params: n.params ?? {} },
    };
  });
  const edges = graph.edges.map((e) => ({
    id: e.id,
    source: e.source.node,
    sourceHandle: e.source.port,
    target: e.target.node,
    targetHandle: e.target.port,
  }));
  return { nodes, edges };
}

/**
 * Load an AimGraph into the flow store, MERGING by node id (AR-2 s3): existing
 * nodes keep their extras/params; new nodes are appended; edges are rebuilt.
 * Never mutates the store when called with invalid content (caller gates with
 * `parseGraph` before invoking).
 */
export function mergeGraphIntoFlow(graph: AimGraph, catalog: NodeSchema[]): void {
  const { nodes: currentNodes, edges: _currentEdges } = useFlowStore.getState();
  const flow = toFlow(graph, catalog, (index) => {
    return { x: 80 + index * 30, y: 80 + index * 30 };
  });
  // Merge by id: keep existing node for ids already present, but apply the
  // incoming layout (position) extra while preserving runtime params.
  const merged: FlowNode[] = flow.nodes.map((incoming) => {
    const existing = currentNodes.find((n) => n.id === incoming.id);
    if (!existing) return incoming;
    return {
      ...existing,
      position: incoming.position ?? existing.position,
      data: { ...incoming.data, params: existing.data.params },
    };
  });
  useFlowStore.setState({ nodes: merged, edges: flow.edges });
}
