import { describe, it, expect } from "vitest";
import { validateBlockingPayload } from "./blockingValidation";
import { buildBlockingTemplate } from "./blockingTemplate";

interface Template {
  keyposes: Array<{
    frame: number;
    pose: Record<string, unknown>;
    weight?: number;
  }>;
  skeleton?: { bones: Record<string, unknown> };
}

const identity = { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] };

function template(): Template {
  return JSON.parse(buildBlockingTemplate()) as Template;
}

function validate(payload: unknown) {
  return validateBlockingPayload(JSON.stringify(payload));
}

describe("core/blockingValidation (blocking-input contract)", () => {
  it("accepts the generated template with all 22 neutral bones", () => {
    const result = validateBlockingPayload(buildBlockingTemplate());
    expect(result.issues).toHaveLength(0);
    expect(result.parsed).not.toBeNull();
    const keyposes = (result.parsed as { keyposes: unknown[] }).keyposes;
    expect(keyposes).toHaveLength(2);
  });

  it("flags a missing bone with missing=[...] on the keypose line", () => {
    const t = template();
    delete t.keyposes[0].pose["LeftArm"];
    const result = validate(t);
    expect(result.issues).toHaveLength(1);
    expect(result.issues[0].message).toContain(
      "keypose 1: pose must name exactly the resolved skeleton bones",
    );
    expect(result.issues[0].message).toContain("missing=[LeftArm]");
    expect(result.issues[0].message).toContain("extra=[]");
    expect(result.issues[0].line).not.toBeNull();
  });

  it("flags an extra bone with extra=[...]", () => {
    const t = template();
    t.keyposes[0].pose["ExtraBone"] = identity;
    const result = validate(t);
    expect(result.issues[0].message).toContain("missing=[]");
    expect(result.issues[0].message).toContain("extra=[ExtraBone]");
  });

  it("flags a duplicate frame across keyposes", () => {
    const t = template();
    t.keyposes[1].frame = 1;
    const result = validate(t);
    const issue = result.issues.find((i) => i.message.includes("frame must be unique"));
    expect(issue).toBeDefined();
    expect(issue!.message).toBe("keypose 2: frame must be unique");
  });

  it("flags a weight outside [0, 1]", () => {
    const t = template();
    t.keyposes[0].weight = 2;
    const result = validate(t);
    expect(result.issues.some((i) => i.message.includes("weight must be a number in [0, 1]"))).toBe(
      true,
    );
  });

  it("reports invalid JSON with a best-effort line number", () => {
    const result = validateBlockingPayload('{\n  "keyposes": [}');
    expect(result.parsed).toBeNull();
    expect(result.issues).toHaveLength(1);
    expect(result.issues[0].message).toMatch(/^invalid JSON:/);
    expect(result.issues[0].line).toBe(2);
  });

  it("reports empty input on line 1", () => {
    for (const text of ["", "   ", "\n \t "]) {
      const result = validateBlockingPayload(text);
      expect(result.issues).toEqual([{ line: 1, message: "blocking JSON is empty" }]);
      expect(result.parsed).toBeNull();
    }
  });

  it("collects several issues in a single pass", () => {
    const t = template();
    delete t.keyposes[0].pose["LeftArm"];
    delete t.keyposes[0].pose["LeftFoot"];
    t.keyposes[0].pose["ExtraBone"] = identity;
    t.keyposes[0].weight = 2;
    (t.keyposes[0].pose["Root"] as { rotation: number[] }).rotation = [2, 0, 0, 0];
    t.keyposes[1].frame = 1;
    const result = validate(t);
    expect(result.issues).toHaveLength(4);
    expect(
      result.issues.some((i) => i.message.includes("missing=[LeftArm, LeftFoot]")),
    ).toBe(true);
    expect(result.issues.some((i) => i.message.includes("extra=[ExtraBone]"))).toBe(true);
    expect(result.issues.some((i) => i.message.includes("keypose 2: frame must be unique"))).toBe(
      true,
    );
    expect(
      result.issues.some((i) => i.message.includes("keypose 1: weight must be a number in [0, 1]")),
    ).toBe(true);
    expect(
      result.issues.some((i) =>
        i.message.includes("keypose 1 (Root): rotation must be a unit quaternion"),
      ),
    ).toBe(true);
  });

  it("uses a custom skeleton's bones as the expected set", () => {
    const payload = {
      skeleton: { bones: { A: {}, B: {} } },
      keyposes: [{ frame: 1, pose: { A: identity, B: identity }, weight: 1 }],
    };
    expect(validate(payload).issues).toHaveLength(0);

    const missingOne = {
      skeleton: { bones: { A: {}, B: {} } },
      keyposes: [{ frame: 1, pose: { A: identity }, weight: 1 }],
    };
    const result = validate(missingOne);
    expect(result.issues[0].message).toContain("missing=[B]");
    expect(result.issues[0].message).not.toContain("LeftArm");
  });

  it("flags unknown top-level fields (extra forbid)", () => {
    const t = template() as unknown as Record<string, unknown>;
    t["surprise"] = 1;
    const result = validate(t);
    const issue = result.issues.find((i) => i.message.startsWith("unknown top-level field"));
    expect(issue).toBeDefined();
    expect(issue!.message).toBe("unknown top-level field: surprise");
    expect(issue!.line).toBe(1);
  });
});