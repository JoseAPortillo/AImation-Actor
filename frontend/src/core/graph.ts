/**
 * The canonical `.aimgraph` v1.0 graph contract (AR-1, AR-2).
 *
 * Mirrors the core's Graph/GraphNode/Edge models (`graph.py`) where `extra =
 * "allow"`: the canonical executable shape is exactly
 *   graph {version, nodes, edges}
 *   node  {id, type, params}
 *   edge  {id, source: {node, port}, target: {node, port}}
 * Unknown/extra keys (e.g. React Flow layout position/viewport) MAY ride on the
 * graph/node as extras and are preserved; they never alter the canonical shape.
 */

export interface PortRef {
  node: string;
  port: string;
}

export interface AimNode {
  id: string;
  type: string;
  params: Record<string, unknown>;
  // Layout extras may ride along (whitelisted: position) — kept as-is.
  [extra: string]: unknown;
}

export interface AimEdge {
  id: string;
  source: PortRef;
  target: PortRef;
}

export interface AimGraph {
  version: "1.0";
  nodes: AimNode[];
  edges: AimEdge[];
  // Whitelisted layout extras.
  viewport?: { x: number; y: number; zoom: number };
  [extra: string]: unknown;
}
