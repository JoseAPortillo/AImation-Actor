/**
 * Step 3: Blender — Send poses to Blender and receive edits.
 *
 * This step:
 * - Shows the marked golden poses
 * - Sends them to Blender via the session API
 * - Waits for the animator to edit in Blender
 * - Receives the edited poses back
 */

import { useCallback, useState } from "react";
import { ApiClient, DEFAULT_URL } from "../../../api/ApiClient";
import type { WizardState } from "../Wizard";

const api = new ApiClient(DEFAULT_URL);

interface Props {
  state: WizardState;
  onUpdate: (partial: Partial<WizardState>) => void;
  onPrev: () => void;
  onNext: () => void;
}

type BlenderStatus = "idle" | "sending" | "waiting" | "received" | "error";

export function WizardStep3Blender({ state, onUpdate, onPrev, onNext }: Props) {
  const [status, setStatus] = useState<BlenderStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  const handleSendToBlender = useCallback(async () => {
    if (!state.sessionId || state.goldenPoses.length === 0) return;

    setStatus("sending");
    setError(null);

    try {
      // Build a minimal NeutralMotion from golden poses
      const motion = {
        meta: { version: "0.2", fps: 24.0, units: "cm", up_axis: "Y", source_type: "wizard" },
        skeleton: { bones: [] },
        frames: state.goldenPoses.map((pose) => ({
          frame: pose.frame,
          time: (pose.frame - 1) / 24.0,
          pose: { transforms: {} },
          confidence: pose.confidence ?? 1.0,
        })),
        keyposes: state.goldenPoses.map((pose) => ({ frame: pose.frame, weight: 1.0 })),
      };

      await api.pushPosesToBlender(state.sessionId, motion);
      setStatus("waiting");
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Error al enviar a Blender");
    }
  }, [state.sessionId, state.goldenPoses]);

  const handlePollPoses = useCallback(async () => {
    if (!state.sessionId) return;

    try {
      const editedMotion = await api.requestEditedPoses(state.sessionId);
      if (editedMotion) {
        onUpdate({ editedMotion });
        setStatus("received");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al recibir poses");
    }
  }, [state.sessionId, onUpdate]);

  return (
    <div style={styles.container}>
      <div style={styles.instructions}>
        <h2 style={styles.stepTitle}>Paso 3: Editar en Blender</h2>
        <p style={styles.stepDesc}>
          Envía las poses a Blender, edítalas en pose mode, y vuelve cuando estés listo.
        </p>
      </div>

      {/* Poses summary */}
      <div style={styles.summary}>
        <h3 style={styles.summaryTitle}>Poses marcadas</h3>
        <div style={styles.poseList}>
          {state.goldenPoses.map((pose, idx) => (
            <div key={idx} style={styles.poseItem}>
              <span style={styles.poseLabel}>{pose.label}</span>
              <span style={styles.poseFrame}>Frame {pose.frame}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Blender status */}
      <div style={styles.blenderSection}>
        {status === "idle" && (
          <div style={styles.idleState}>
            <p style={styles.idleText}>
              ¿Listo para editar en Blender? Envía las poses y abre Blender para modificarlas.
            </p>
            <button
              type="button"
              onClick={handleSendToBlender}
              style={styles.sendButton}
            >
              📤 Enviar a Blender
            </button>
          </div>
        )}

        {status === "sending" && (
          <div style={styles.sendingState}>
            <div style={styles.spinner} />
            <span>Enviando poses a Blender...</span>
          </div>
        )}

        {status === "waiting" && (
          <div style={styles.waitingState}>
            <div style={styles.waitingIcon}>⏳</div>
            <h3 style={styles.waitingTitle}>Esperando en Blender</h3>
            <p style={styles.waitingText}>
              Abre Blender, carga el addon de AImation Actor, y edita las poses en pose mode.
            </p>
            <p style={styles.waitingText}>
              Cuando termines, haz clic en "Volver a la app" en Blender.
            </p>
            <button
              type="button"
              onClick={handlePollPoses}
              style={styles.pollButton}
            >
              🔄 Verificar si hay poses editadas
            </button>
          </div>
        )}

        {status === "received" && (
          <div style={styles.receivedState}>
            <div style={styles.receivedIcon}>✅</div>
            <h3 style={styles.receivedTitle}>Poses recibidas</h3>
            <p style={styles.receivedText}>
              Las poses editadas han sido recibidas correctamente.
            </p>
            <button
              type="button"
              onClick={onNext}
              style={styles.generateButton}
            >
              ✨ Generar movimiento
            </button>
          </div>
        )}

        {status === "error" && (
          <div style={styles.errorState}>
            <div style={styles.errorIcon}>❌</div>
            <h3 style={styles.errorTitle}>Error</h3>
            <p style={styles.errorText}>{error}</p>
            <button
              type="button"
              onClick={() => setStatus("idle")}
              style={styles.retryButton}
            >
              Reintentar
            </button>
          </div>
        )}
      </div>

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
    maxWidth: 500,
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
  },
  summaryTitle: {
    margin: 0,
    fontSize: 14,
    fontWeight: 500,
    color: "#fbbf24",
  },
  poseList: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    marginTop: 12,
  },
  poseItem: {
    display: "flex",
    justifyContent: "space-between",
    padding: "8px 12px",
    background: "#1f2937",
    borderRadius: 6,
  },
  poseLabel: {
    color: "#e5e7eb",
    fontSize: 13,
  },
  poseFrame: {
    color: "#6b7280",
    fontSize: 13,
  },
  blenderSection: {
    width: "100%",
    minHeight: 200,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  idleState: {
    textAlign: "center",
  },
  idleText: {
    color: "#9ca3af",
    fontSize: 14,
    marginBottom: 16,
  },
  sendButton: {
    padding: "12px 24px",
    background: "#7c3aed",
    border: "none",
    borderRadius: 8,
    color: "#fff",
    fontSize: 14,
    fontWeight: 500,
    cursor: "pointer",
  },
  sendingState: {
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
  waitingState: {
    textAlign: "center",
  },
  waitingIcon: {
    fontSize: 48,
    marginBottom: 12,
  },
  waitingTitle: {
    margin: 0,
    fontSize: 18,
    color: "#f9fafb",
  },
  waitingText: {
    color: "#9ca3af",
    fontSize: 13,
    lineHeight: 1.5,
    marginTop: 8,
  },
  pollButton: {
    marginTop: 16,
    padding: "10px 20px",
    background: "#1f2937",
    border: "1px solid #374151",
    borderRadius: 8,
    color: "#e5e7eb",
    fontSize: 13,
    cursor: "pointer",
  },
  receivedState: {
    textAlign: "center",
  },
  receivedIcon: {
    fontSize: 48,
    marginBottom: 12,
  },
  receivedTitle: {
    margin: 0,
    fontSize: 18,
    color: "#4ade80",
  },
  receivedText: {
    color: "#9ca3af",
    fontSize: 13,
    marginTop: 8,
  },
  generateButton: {
    marginTop: 16,
    padding: "12px 24px",
    background: "#2563eb",
    border: "none",
    borderRadius: 8,
    color: "#fff",
    fontSize: 14,
    fontWeight: 500,
    cursor: "pointer",
  },
  errorState: {
    textAlign: "center",
  },
  errorIcon: {
    fontSize: 48,
    marginBottom: 12,
  },
  errorTitle: {
    margin: 0,
    fontSize: 18,
    color: "#fca5a5",
  },
  errorText: {
    color: "#9ca3af",
    fontSize: 13,
    marginTop: 8,
  },
  retryButton: {
    marginTop: 16,
    padding: "10px 20px",
    background: "#7f1d1d",
    border: "1px solid #991b1b",
    borderRadius: 8,
    color: "#fca5a5",
    fontSize: 13,
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
