/**
 * Step 1: Video Upload — Simple video selection.
 *
 * The user can:
 * - Drag & drop a video file
 * - Click to browse files
 * - See a preview once selected
 *
 * After upload, the media reference is stored for the next step.
 */

import { useCallback, useRef, useState } from "react";
import { ApiClient, DEFAULT_URL } from "../../../api/ApiClient";
import type { WizardState } from "../Wizard";

const api = new ApiClient(DEFAULT_URL);

interface Props {
  state: WizardState;
  onUpdate: (partial: Partial<WizardState>) => void;
  onNext: () => void;
}

export function WizardStep1Video({ state, onUpdate, onNext }: Props) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    async (file: File) => {
      if (!file.type.startsWith("video/")) {
        setError("Selecciona un archivo de video (MP4, MOV, AVI)");
        return;
      }

      setUploading(true);
      setError(null);

      try {
        const reference = await api.uploadVideo(file);
        onUpdate({
          videoRef: reference,
          videoPath: reference,
        });
        // Auto-advance after upload
        setTimeout(() => onNext(), 500);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error al subir video");
      } finally {
        setUploading(false);
      }
    },
    [onUpdate, onNext],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  const handleClick = useCallback(() => {
    fileRef.current?.click();
  }, []);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  return (
    <div style={styles.container}>
      <div style={styles.instructions}>
        <h2 style={styles.stepTitle}>Paso 1: Carga tu video</h2>
        <p style={styles.stepDesc}>
          Selecciona el video del que quieres extraer el movimiento.
        </p>
      </div>

      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={handleClick}
        style={{
          ...styles.dropZone,
          ...(dragOver ? styles.dropZoneActive : {}),
          ...(state.videoRef ? styles.dropZoneSuccess : {}),
        }}
      >
        <input
          ref={fileRef}
          type="file"
          accept="video/*"
          onChange={handleChange}
          style={{ display: "none" }}
        />

        {uploading ? (
          <div style={styles.uploading}>
            <div style={styles.spinner} />
            <span>Subiendo video...</span>
          </div>
        ) : state.videoRef ? (
          <div style={styles.success}>
            <span style={styles.checkIcon}>✓</span>
            <span>Video cargado correctamente</span>
            <span style={styles.fileName}>{state.videoRef}</span>
          </div>
        ) : (
          <div style={styles.dropContent}>
            <span style={styles.dropIcon}>🎬</span>
            <span style={styles.dropText}>
              Arrastra tu video aquí
            </span>
            <span style={styles.dropSubtext}>
              o haz clic para seleccionar
            </span>
            <span style={styles.dropFormats}>
              MP4, MOV, AVI
            </span>
          </div>
        )}
      </div>

      {error && <div style={styles.error}>{error}</div>}

      {state.videoRef && (
        <button type="button" onClick={onNext} style={styles.nextButton}>
          Siguiente: Golden Poses →
        </button>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 24,
    paddingTop: 40,
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
  dropZone: {
    width: "100%",
    maxWidth: 480,
    height: 200,
    border: "2px dashed #374151",
    borderRadius: 12,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
    transition: "all 0.2s",
    background: "#111827",
  },
  dropZoneActive: {
    borderColor: "#3b82f6",
    background: "#1e3a5f",
  },
  dropZoneSuccess: {
    borderColor: "#22c55e",
    background: "#14532d",
  },
  dropContent: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 8,
  },
  dropIcon: {
    fontSize: 48,
  },
  dropText: {
    fontSize: 16,
    color: "#e5e7eb",
    fontWeight: 500,
  },
  dropSubtext: {
    fontSize: 12,
    color: "#6b7280",
  },
  dropFormats: {
    fontSize: 10,
    color: "#4b5563",
    marginTop: 4,
  },
  uploading: {
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
  success: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 8,
    color: "#4ade80",
  },
  checkIcon: {
    fontSize: 32,
  },
  fileName: {
    fontSize: 10,
    color: "#6b7280",
    wordBreak: "break-all",
    textAlign: "center",
    maxWidth: 300,
  },
  error: {
    padding: "8px 16px",
    background: "#450a0a",
    border: "1px solid #7f1d1d",
    borderRadius: 8,
    color: "#fca5a5",
    fontSize: 13,
  },
  nextButton: {
    padding: "12px 24px",
    background: "#2563eb",
    border: "none",
    borderRadius: 8,
    color: "#fff",
    fontSize: 14,
    fontWeight: 500,
    cursor: "pointer",
    transition: "background 0.2s",
  },
};
