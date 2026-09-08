/**
 * Blocking-input JSON template generator (blocking-input UX).
 *
 * A blocking payload is a JSON object `{ keyposes: [...] }` where each keypose
 * names EVERY bone of the neutral skeleton (SDD §20.5 / REQ-01). Authoring that
 * by hand is error-prone, so we hand the user a ready-made template with the
 * exact bone set — they fill in their poses and load the file. Keeping the
 * template here means the frontend can prefill the correct skeleton without
 * guessing, mirroring `DEFAULT_NEUTRAL_SKELETON` in the core.
 */

/** Default neutral skeleton bones (Root + 21), mirroring the core preset. */
export const NEUTRAL_SKELETON_BONES: readonly string[] = [
  "Root",
  "Hips",
  "Spine",
  "Chest",
  "Neck",
  "Head",
  "LeftShoulder",
  "LeftArm",
  "LeftForeArm",
  "LeftHand",
  "RightShoulder",
  "RightArm",
  "RightForeArm",
  "RightHand",
  "LeftUpLeg",
  "LeftLeg",
  "LeftFoot",
  "LeftToeBase",
  "RightUpLeg",
  "RightLeg",
  "RightFoot",
  "RightToeBase",
];

interface BlockingTransform {
  translation: [number, number, number];
  rotation: [number, number, number, number];
  scale: [number, number, number];
}

interface BlockingKeypose {
  frame: number;
  pose: Record<string, BlockingTransform>;
  weight: number;
}

/**
 * Build a blocking payload template for the neutral skeleton.
 *
 * Produces a two-keypose example (default relative pose at frames 1 and 30)
 * with every bone present — the user replaces the transform values with their
 * authored poses. Returns formatted JSON for download / prefill.
 *
 * @param keyposes - explicit keyposes; defaults to the standard 2-pose sample.
 * @returns A JSON string ready to save as a `.json` blocking file.
 */
export function buildBlockingTemplate(
  keyposes: BlockingKeypose[] = defaultBlockingKeyposes(),
): string {
  return JSON.stringify({ keyposes }, null, 2);
}

function defaultBlockingKeyposes(): BlockingKeypose[] {
  const neutralPose = (): Record<string, BlockingTransform> => {
    const pose: Record<string, BlockingTransform> = {};
    for (const bone of NEUTRAL_SKELETON_BONES) {
      // Identity transform: no translation/rotation offset, unitary scale.
      pose[bone] = {
        translation: [0, 0, 0],
        rotation: [1, 0, 0, 0],
        scale: [1, 1, 1],
      };
    }
    return pose;
  };

  return [
    { frame: 1, pose: neutralPose(), weight: 1.0 },
    { frame: 30, pose: neutralPose(), weight: 1.0 },
  ];
}

/**
 * Trigger a browser download of the blocking template as a `.json` file.
 */
export function downloadBlockingTemplate(): void {
  const payload = buildBlockingTemplate();
  const blob = new Blob([payload], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "blocking-template.json";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
