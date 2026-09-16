/**
 * Wizard — Linear step-by-step interface for animators.
 *
 * Replaces the node-based FlowCanvas with a simple 3-step wizard:
 *   1. Cargar Video
 *   2. Golden Poses
 *   3. Blender
 *
 * The backend (React Flow nodes) remains unchanged — this is purely a
 * frontend presentation layer that calls the same API endpoints.
 */

import { useState, useCallback } from "react";
import { WizardStep1Video } from "./steps/WizardStep1Video";
import { WizardStep2Poses } from "./steps/WizardStep2Poses";
import { WizardStep3Blender } from "./steps/WizardStep3Blender";

export type WizardStep = 1 | 2 | 3;

export interface WizardState {
  videoPath: string | null;
  videoRef: string | null; // media reference after upload
  frameCount: number;
  goldenPoses: Array<{ frame: number; label: string; confidence: number | null }>;
  sessionId: string | null;
}

const STEPS = [
  { num: 1, label: "Cargar Video", icon: "🎬" },
  { num: 2, label: "Golden Poses", icon: "✏️" },
  { num: 3, label: "Blender", icon: "🔮" },
] as const;

export function Wizard() {
  const [currentStep, setCurrentStep] = useState<WizardStep>(1);
  const [state, setState] = useState<WizardState>({
    videoPath: null,
    videoRef: null,
    frameCount: 0,
    goldenPoses: [],
    sessionId: null,
  });

  const updateState = useCallback((partial: Partial<WizardState>) => {
    setState((prev) => ({ ...prev, ...partial }));
  }, []);

  const goNext = useCallback(() => {
    setCurrentStep((prev) => Math.min(prev + 1, 3) as WizardStep);
  }, []);

  const goPrev = useCallback(() => {
    setCurrentStep((prev) => Math.max(prev - 1, 1) as WizardStep);
  }, []);

  const goToStep = useCallback((step: WizardStep) => {
    setCurrentStep(step);
  }, []);

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <h1 style={styles.title}>AImation Actor</h1>
        <p style={styles.subtitle}>Asistente de animación con IA</p>
      </div>

      {/* Step indicators */}
      <div style={styles.stepper}>
        {STEPS.map((step, idx) => (
          <div key={step.num} style={styles.stepWrapper}>
            <button
              type="button"
              onClick={() => goToStep(step.num)}
              style={{
                ...styles.stepCircle,
                ...(currentStep === step.num ? styles.stepCircleActive : {}),
                ...(currentStep > step.num ? styles.stepCircleDone : {}),
              }}
            >
              {currentStep > step.num ? "✓" : step.icon}
            </button>
            <span
              style={{
                ...styles.stepLabel,
                ...(currentStep === step.num ? styles.stepLabelActive : {}),
              }}
            >
              {step.label}
            </span>
            {idx < STEPS.length - 1 && (
              <div
                style={{
                  ...styles.stepLine,
                  ...(currentStep > step.num ? styles.stepLineDone : {}),
                }}
              />
            )}
          </div>
        ))}
      </div>

      {/* Step content */}
      <div style={styles.content}>
        {currentStep === 1 && (
          <WizardStep1Video
            state={state}
            onUpdate={updateState}
            onNext={goNext}
          />
        )}
        {currentStep === 2 && (
          <WizardStep2Poses
            state={state}
            onUpdate={updateState}
            onNext={goNext}
            onPrev={goPrev}
          />
        )}
        {currentStep === 3 && (
          <WizardStep3Blender
            state={state}
            onUpdate={updateState}
            onPrev={goPrev}
          />
        )}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: "flex",
    flexDirection: "column",
    height: "100vh",
    background: "#0a0a0a",
    color: "#e5e7eb",
    fontFamily: "'Inter', -apple-system, sans-serif",
    overflow: "hidden",
  },
  header: {
    padding: "16px 24px 8px",
    borderBottom: "1px solid #1f2937",
  },
  title: {
    margin: 0,
    fontSize: 20,
    fontWeight: 600,
    color: "#f9fafb",
  },
  subtitle: {
    margin: "2px 0 0",
    fontSize: 12,
    color: "#6b7280",
  },
  stepper: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 0,
    padding: "16px 24px",
  },
  stepWrapper: {
    display: "flex",
    alignItems: "center",
    gap: 0,
  },
  stepCircle: {
    width: 36,
    height: 36,
    borderRadius: "50%",
    border: "2px solid #374151",
    background: "#111827",
    color: "#6b7280",
    fontSize: 14,
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    transition: "all 0.2s",
  },
  stepCircleActive: {
    borderColor: "#3b82f6",
    background: "#1e3a5f",
    color: "#93c5fd",
  },
  stepCircleDone: {
    borderColor: "#22c55e",
    background: "#14532d",
    color: "#4ade80",
  },
  stepLabel: {
    marginLeft: 8,
    fontSize: 12,
    color: "#6b7280",
    whiteSpace: "nowrap",
  },
  stepLabelActive: {
    color: "#93c5fd",
    fontWeight: 500,
  },
  stepLine: {
    width: 40,
    height: 2,
    background: "#374151",
    margin: "0 12px",
  },
  stepLineDone: {
    background: "#22c55e",
  },
  content: {
    flex: 1,
    overflow: "auto",
    padding: "0 24px 24px",
  },
};
