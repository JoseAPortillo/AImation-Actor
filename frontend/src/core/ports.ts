/**
 * Port-type compatibility mirror of `graph.py` `ports_compatible` (D6).
 * Two ports connect when their data types are equal OR either side is `any`
 * (a universal relay). The core remains the enforcement boundary; this is the
 * UI mirror used to gate edge formation.
 */
import type { DataType } from "../api/types";

export function portsCompatible(source: DataType, target: DataType): boolean {
  return source === target || source === "any" || target === "any";
}
