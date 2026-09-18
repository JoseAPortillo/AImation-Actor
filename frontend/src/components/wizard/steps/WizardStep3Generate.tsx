/**
 * Step 3: Generate Movement — The generative MVP with 2 sliders.
 *
 * This step:
 * - Shows 2 sliders: Naturalidad + Respetar mis poses
 * - Calls the backend to generate motion between golden poses
 * - Displays the result in MotionViewer (3D preview)
 * - Allows "Otra versión" to regenerate with different params
 * - Optional: Send to Blender/Maya when user is happy with the result
 */

import { useCallback, useState } from "react";
import { ApiClient, DEFAULT_URL } from "../../../api/ApiClient";
import type { NeutralMotionDoc } from "../../../api/types";
import { MotionViewer } from "../../motion/MotionViewer";
import type { WizardState } from "../Wizard";

const api = new ApiClient(DEFAULT_URL);

interface Props {
  state: WizardState;
  onUpdate: (partial: Partial<WizardState>) => void;
  onPrev: () => void;
}

type GenerateStatus = "idle" | "generating" | "done" | "error";

export function WizardStep3Generate({ state, onPrev }: Props) {
  const [naturalidad, setNaturalidad] = useState(50);
  const [respetarPoses, setRespetarPoses] = useState(70);
  const [status, setStatus] = useState<GenerateStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [generatedMotion, setGeneratedMotion] = useState<NeutralMotionDoc | null>(null);

  const handleGenerate = useCallback(async () => {
    if (state.goldenPoses.length === 0) return;

    setStatus("generating");
    setError(null);

    try {
      const motion = await api.generateMotion({
        goldenPoses: state.goldenPoses,
        naturalidad,
        respetarPoses,
      });
      setGeneratedMotion(motion as unknown as NeutralMotionDoc);
      setStatus("done");
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Error al generar movimiento");
    }
  }, [state.goldenPoses, naturalidad, respetarPoses]);

  const handleRegenerate = useCallback(() => {
    setStatus("idle");
    setGeneratedMotion(null);
  }, []);

  return (
    <div style={styles.container}>
      <div style={styles.instructions}>
        <h2 style={styles.stepTitle}>Paso 3: Generar movimiento</h2>
        <p style={styles.stepDesc}>
          Ajusta los parámetros y genera el movimiento entre tus golden poses.
        </p>
      </div>

      {/* Golden poses summary */}
      <div style={styles.summary}>
        <h3 style={styles.summaryTitle}>Golden poses: {state.goldenPoses.map((_, i) => `G${i + 1}`).join(" → ")}</h3>
        <p style={styles.summaryCount}>{state.goldenPoses.length} poses marcadas</p>
      </div>

      {/* Sliders */}
      <div style={styles.slidersSection}>
        <div style={styles.sliderGroup}>
          <label style={styles.sliderLabel}>
            Naturalidad
            <span style={styles.sliderValue}>{naturalidad}%</span>
          </label>
          <p style={styles.sliderDesc}>Cuánto "vive" el movimiento (variación/expresividad)</p>
          <input
            type="range"
            min={0}
            max={100}
            value={naturalidad}
            onChange={(e) => setNaturalidad(Number(e.target.value))}
            style={styles.slider}
          />
          <div style={styles.sliderLabels}>
            <span>Más estable</span>
            <span>Más expresivo</span>
          </div>
        </div>

        <div style={styles.sliderGroup}>
          <label style={styles.sliderLabel}>
            Respetar mis poses
            <span style={styles.sliderValue}>{respetarPoses}%</span>
          </label>
          <p style={styles.sliderDesc}>Cuánto se mantiene fiel a las golden poses editadas</p>
          <input
            type="range"
            min={0}
            max={100}
            value={respetarPoses}
            onChange={(e) => setRespetarPoses(Number(e.target.value))}
            style={styles.slider}
          />
          <div style={styles.sliderLabels}>
            <span>Más libre</span>
            <span>Más fiel</span>
          </div>
        </div>
      </div>

      {/* Generate button */}
      {status === "idle" && (
        <button type="button" onClick={handleGenerate} style={styles.generateButton}>
          ✨ Generar movimiento
        </button>
      )}

      {/* Generating state */}
      {status === "generating" && (
        <div style={styles.generatingState}>
          <div style={styles.spinner} />
          <span>Generando movimiento...</span>
        </div>
      )}

      {/* Error state */}
      {status === "error" && (
        <div style={styles.errorState}>
          <p style={styles.errorText}>{error}</p>
          <button type="button" onClick={handleGenerate} style={styles.retryButton}>
            Reintentar
          </button>
        </div>
      )}

      {/* Result preview */}
      {status === "done" && generatedMotion && (
        <div style={styles.resultSection}>
          <h3 style={styles.resultTitle}>Preview del movimiento</h3>
          <div style={styles.viewerContainer}>
            <MotionViewer motion={generatedMotion} />
          </div>
          <div style={styles.resultActions}>
            <button type="button" onClick={handleRegenerate} style={styles.regenerateButton}>
              ↻ Otra versión
            </button>
            <button type="button" onClick={() => {/* TODO: send to Blender */}} style={styles.sendButton}>
              Enviar a Blender →
            </button>
          </div>
        </div>
      )}

      {/* Navigation */}
      <div style={styles.navigation}>
        <button type="button" onClick={onPrev} style={styles.prevBtn}>
          ← Volver a Golden Poses
        </button>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 24,
    maxWidth: 600,
    margin: "0 auto",
  },
  instructions: {
    textAlign: "center",
  },
  stepTitle: {
    margin: 0,
    fontSize: 24,
    fontWeight: 600,
    color: "#f9fafb",
  },
  stepDesc: {
    margin: "8px 0 0",
    fontSize: 14,
    color: "#9ca3af",
  },
  summary: {
    width: "100%",
    padding: 16,
    background: "#111827",
    border: "1px solid #374151",
    borderRadius: 8,
    textAlign: "center",
  },
  summaryTitle: {
    margin: 0,
    fontSize: 14,
    fontWeight: 500,
    color: "#fbbf24",
  },
  summaryCount: {
    margin: "4px 0 0",
    fontSize: 12,
    color: "#6b7280",
  },
  slidersSection: {
    width: "100%",
    display: "flex",
    flexDirection: "column",
    gap: 24,
  },
  sliderGroup: {
    padding: 16,
    background: "#111827",
    border: "1px solid #374151",
    borderRadius: 8,
  },
  sliderLabel: {
    display: "flex",
    justifyContent: "space-between",
    fontSize: 14,
    fontWeight: 500,
    color: "#e5e7eb",
  },
  sliderValue: {
    color: "#3b82f6",
    fontWeight: 600,
  },
  sliderDesc: {
    margin: "4px 0 12px",
    fontSize: 12,
    color: "#6b7280",
  },
  slider: {
    width: "100%",
    height: 6,
    borderRadius: 3,
    background: "#1f2937",
    outline: "none",
    WebkitAppearance: "none",
    cursor: "pointer",
  },
  sliderLabels: {
    display: "flex",
    justifyContent: "space-between",
    marginTop: 8,
    fontSize: 11,
    color: "#6b7280",
  },
  generateButton: {
    padding: "14px 32px",
    background: "#2563eb",
    border: "none",
    borderRadius: 8,
    color: "#fff",
    fontSize: 16,
    fontWeight: 600,
    cursor: "pointer",
    transition: "background 0.2s",
  },
  generatingState: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 12,
    color: "#93c5fd",
  },
  spinner: {
    width: 32,
    height: 32,
    border: "3px solid #1e3a5f",
    borderTopColor: "#3b82f6",
    borderRadius: "50%",
    animation: "spin 1s linear infinite",
  },
  errorState: {
    textAlign: "center",
  },
  errorText: {
    color: "#fca5a5",
    fontSize: 14,
    marginBottom: 12,
  },
  retryButton: {
    padding: "10px 20px",
    background: "#7f1d1d",
    border: "1px solid #991b1b",
    borderRadius: 8,
    color: "#fca5a5",
    fontSize: 13,
    cursor: "pointer",
  },
  resultSection: {
    width: "100%",
    padding: 16,
    background: "#111827",
    border: "1px solid #374151",
    borderRadius: 8,
  },
  resultTitle: {
    margin: "0 0 12px",
    fontSize: 14,
    fontWeight: 500,
    color: "#4ade80",
  },
  viewerContainer: {
    borderRadius: 8,
    overflow: "hidden",
    background: "#0a0a0a",
  },
  resultActions: {
    display: "flex",
    gap: 12,
    marginTop: 16,
  },
  regenerateButton: {
    flex: 1,
    padding: "10px 16px",
    background: "#1f2937",
    border: "1px solid #374151",
    borderRadius: 8,
    color: "#e5e7eb",
    fontSize: 13,
    cursor: "pointer",
  },
  sendButton: {
    flex: 1,
    padding: "10px 16px",
    background: "#7c3aed",
    border: "none",
    borderRadius: 8,
    color: "#fff",
    fontSize: 13,
    fontWeight: 500,
    cursor: "pointer",
  },
  navigation: {
    marginTop: 8,
  },
  prevBtn: {
    padding: "10px 20px",
    background: "#1f2937",
    border: "1px solid #374151",
    borderRadius: 8,
    color: "#e5e7eb",
    fontSize: 14,
    cursor: "pointer",
  },
};
