/**
 * Schema helpers mirroring the core's frozen Pydantic models (`schema.py`).
 *
 * The core `NodeSchema`/`PortSpec` are `frozen=True`. We keep the TS mirrors
 * read-only by convention and expose pure lookup/derivation helpers so the
 * editor consumes the live `/nodes/types` contract without hardcoding ports
 * (EC-1) and the properties panel derives defaults from it (PP-1).
 */

import type { NodeSchema, PortSpec } from "../api/types";

export function findInputPort(schema: NodeSchema, name: string): PortSpec | undefined {
  return schema.inputs.find((p) => p.name === name);
}

export function findOutputPort(schema: NodeSchema, name: string): PortSpec | undefined {
  return schema.outputs.find((p) => p.name === name);
}

export function findParam(schema: NodeSchema, name: string): PortSpec | undefined {
  return schema.params.find((p) => p.name === name);
}

/**
 * Derive the effective params for a node: apply each schema param's default
 * when it is non-null and the key is unset. Params whose default is `null`
 * (i.e. no default) stay unset so required-param validation (GE-3) can still
 * catch them. A user-provided value is never overwritten (PP-1).
 */
export function getDefaultedParams(
  schema: NodeSchema,
  current: Record<string, unknown>,
): Record<string, unknown> {
  const result: Record<string, unknown> = { ...current };
  for (const param of schema.params) {
    if (param.default !== null && result[param.name] === undefined) {
      result[param.name] = param.default;
    }
  }
  return result;
}

export interface SchemaShapeResult {
  valid: boolean;
  errors: string[];
}

/**
 * Lightweight structural validation mirroring the Pydantic field constraints:
 * a schema needs a non-empty type and title, and every port a non-empty name.
 * Used to guard node rendering from malformed catalog entries (EC-1).
 */
export function validateSchemaShape(schema: NodeSchema): SchemaShapeResult {
  const errors: string[] = [];
  if (!schema.type || schema.type.length === 0) {
    errors.push("schema.type must be non-empty");
  }
  if (!schema.title || schema.title.length === 0) {
    errors.push("schema.title must be non-empty");
  }
  for (const port of [...schema.inputs, ...schema.outputs, ...schema.params]) {
    if (!port.name || port.name.length === 0) {
      errors.push(`${schema.type} has a port with an empty name`);
    }
  }
  return { valid: errors.length === 0, errors };
}
