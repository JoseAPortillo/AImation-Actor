/**
 * BVH export for NeutralMotionDoc.
 *
 * Pure functions, DOM-free, unit-testable. Converts quaternion rotations
 * to Tait-Bryan XYZ Euler angles and generates standard BVH text.
 */

import type { NeutralMotionDoc, Vec4 } from "../api/types";

/**
 * Format a number for BVH output: 6 decimal places, strip trailing zeros,
 * handle negative zero.
 */
function fmt(n: number): string {
  // Handle negative zero
  if (Math.abs(n) < 1e-9) n = 0;
  return n.toFixed(6).replace(/\.?0+$/, "") || "0";
}

/**
 * Convert a quaternion to Tait-Bryan XYZ Euler angles (radians).
 *
 * The quaternion is w-FIRST (w, x, y, z) as stored in Transform3D.rotation.
 * Returns { zRot: yaw, xRot: roll, yRot: pitch }.
 */
export function quatToEulerZXY(q: Vec4): {
  zRot: number;
  xRot: number;
  yRot: number;
} {
  const [w, x, y, z] = q;

  // Clamp for numerical stability
  const sinp = 2 * (w * y - z * x);
  const pitch = Math.asin(Math.max(-1, Math.min(1, sinp)));

  const sinr = 2 * (w * x + y * z);
  const cosr = 1 - 2 * (x * x + y * y);
  const roll = Math.atan2(sinr, cosr);

  const siny = 2 * (w * z + x * y);
  const cosy = 1 - 2 * (y * y + z * z);
  const yaw = Math.atan2(siny, cosy);

  return { zRot: yaw, xRot: roll, yRot: pitch };
}

/**
 * Build depth-first traversal order of bones, starting from Root.
 *
 * Children are emitted in the iteration order of Object.values(bones).
 */
function buildHierarchyOrder(bones: Record<string, { parent: string | null; name: string }>): string[] {
  const root = Object.values(bones).find((b) => b.parent === null);
  if (!root) return [];

  const order: string[] = [];
  const childrenMap: Record<string, string[]> = {};

  for (const bone of Object.values(bones)) {
    if (bone.parent) {
      if (!childrenMap[bone.parent]) childrenMap[bone.parent] = [];
      childrenMap[bone.parent].push(bone.name);
    }
  }

  function visit(name: string) {
    order.push(name);
    const children = childrenMap[name] || [];
    for (const child of children) {
      visit(child);
    }
  }

  visit(root.name);
  return order;
}

/**
 * Emit a joint block with proper indentation.
 */
function emitJoint(
  name: string,
  isRoot: boolean,
  offset: [number, number, number],
  childBlocks: string[],
  indent: string
): string {
  const lines: string[] = [];
  lines.push(`${indent}${isRoot ? "ROOT" : "JOINT"} ${name}`);
  lines.push(`${indent}{`);
  lines.push(`${indent}\tOFFSET ${fmt(offset[0])} ${fmt(offset[1])} ${fmt(offset[2])}`);
  if (isRoot) {
    lines.push(`${indent}\tCHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation`);
  } else {
    lines.push(`${indent}\tCHANNELS 3 Zrotation Xrotation Yrotation`);
  }
  for (const child of childBlocks) {
    lines.push(child);
  }
  lines.push(`${indent}}`);
  return lines.join("\n");
}

/**
 * Recursively build BVH hierarchy blocks.
 */
function buildJointBlock(
  name: string,
  bones: Record<string, { parent: string | null; name: string; rest_position: [number, number, number] }>,
  indent: string
): string {
  const bone = bones[name];
  const isRoot = bone.parent === null;

  // Find children in iteration order
  const children: string[] = [];
  for (const b of Object.values(bones)) {
    if (b.parent === name) {
      children.push(buildJointBlock(b.name, bones, indent + "\t"));
    }
  }

  return emitJoint(name, isRoot, bone.rest_position, children, indent);
}

/**
 * Convert a NeutralMotionDoc to BVH text.
 *
 * @param motion - The motion document to export
 * @returns Complete BVH text string
 */
export function neutralToBvh(motion: NeutralMotionDoc): string {
  const { bones } = motion.skeleton;
  const order = buildHierarchyOrder(bones);
  const fps = motion.meta?.fps ?? 24;
  const frameTime = 1 / fps;

  // Build hierarchy
  const hierarchyLines: string[] = ["HIERARCHY"];
  const rootBlock = buildJointBlock("Root", bones, "");
  hierarchyLines.push(rootBlock);

  // Build motion
  const motionLines: string[] = ["MOTION", `Frames: ${motion.frames.length}`, `Frame Time: ${fmt(frameTime)}`];

  // Emit frame data in the same order as hierarchy
  for (const frame of motion.frames) {
    const transforms = frame.pose.transforms;
    const values: string[] = [];

    for (const boneName of order) {
      const t = transforms[boneName];
      const bone = bones[boneName];

      // Position: for root use transforms, for others omit position
      if (bone.parent === null) {
        const translation = t?.translation ?? bone.rest_position;
        values.push(fmt(translation[0]), fmt(translation[1]), fmt(translation[2]));
      }

      // Rotation: convert quaternion to Euler
      const rot = t?.rotation ?? ([1, 0, 0, 0] as Vec4);
      const euler = quatToEulerZXY(rot);
      values.push(fmt(euler.zRot), fmt(euler.xRot), fmt(euler.yRot));
    }

    motionLines.push(values.join(" "));
  }

  return [...hierarchyLines, ...motionLines].join("\n");
}
