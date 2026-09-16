/**
 * Step 2: Golden Poses — Simplified timeslider for marking key poses.
 *
 * This is a stripped-down version of VideoTimeslider focused on the
 * animator's workflow: scrub, mark poses, see skeleton overlay.
 *
 * No node concepts, no complex parameters — just the essentials.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiClient, DEFAULT_URL } from "../../../api/ApiClient";
import { usePinsStore } from "../../../state/usePinsStore";
import { drawSkeleton } from "../../../core/skeletonOverlay";
import type { WizardState } from "../Wizard";

const api = new ApiClient(DEFAULT_URL);
const PLAY_INTERVAL_MS = 80;
const FRAME_WIDTH = 400;

interface Props {
  state: WizardState;
  onUpdate: (partial: Partial<WizardState>) => void;
  onNext: () => void;
  onPrev: () => void;
}

export function WizardStep2Poses({ state, onUpdate, onNext, onPrev }: Props) {
  const [frame, setFrame] = useState(1);
  const [frameCount, setFrameCount] = useState(0);
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [overlayVisible, setOverlayVisible] = useState(true);

  const trackRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const imgUrlRef = useRef<string | null>(null);
  imgUrlRef.current = imgUrl;

  // Use a fixed nodeId for the wizard
  const nodeId = "wizard-video";
  const nodePins = usePinsStore((s) => s.pinsByNode[nodeId]) ?? [];

  // Sync api into pin store
  useEffect(() => {
    usePinsStore.setState({ api });
  }, [api]);

  // Frame fetching
  useEffect(() => {
    if (!state.videoPath) return;
    const videoPath = state.videoPath;
    let cancelled = false;
    console.log(`[WizardStep2] Fetching frame ${frame} for ${videoPath}`);
    void (async () => {
      try {
        const { blob, frameCount: fc } = await api.fetchFrameJpeg(videoPath, frame, FRAME_WIDTH);
        if (cancelled) return;
        console.log(`[WizardStep2] Got frame ${frame}, size=${blob.size}, frameCount=${fc}`);
        const url = URL.createObjectURL(blob);
        setImgUrl((prev) => {
          if (prev) URL.revokeObjectURL(prev);
          return url;
        });
        setFrameCount(fc);
      } catch (err) {
        console.error(`[WizardStep2] Error fetching frame ${frame}:`, err);
      }
    })();
    return () => { cancelled = true; };
  }, [state.videoPath, frame]);

  // Cleanup
  useEffect(() => {
    return () => {
      if (imgUrlRef.current) URL.revokeObjectURL(imgUrlRef.current);
    };
  }, []);

  // Playback
  useEffect(() => {
    if (!playing || frameCount <= 0) {
      if (timerRef.current != null) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }
    timerRef.current = setInterval(() => {
      setFrame((prev) => {
        if (prev >= frameCount) {
          setPlaying(false);
          return frameCount;
        }
        return prev + 1;
      });
    }, PLAY_INTERVAL_MS);
    return () => {
      if (timerRef.current != null) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [playing, frameCount]);

  // Overlay drawing
  const currentDetection = useMemo(() => {
    if (!overlayVisible) return null;
    const pin = nodePins.find(
      (p) => p.status === "success" && p.frame === frame && p.detection !== null,
    );
    return pin?.detection ?? null;
  }, [nodePins, frame, overlayVisible]);

  useEffect(() => {
    const canvas = overlayRef.current;
    if (!canvas || !currentDetection) return;
    const displayWidth = imgRef.current?.clientWidth ?? 0;
    const displayHeight = imgRef.current?.clientHeight ?? 0;
    const overlay = drawSkeleton(currentDetection, displayWidth, displayHeight);
    canvas.width = displayWidth;
    canvas.height = displayHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, displayWidth, displayHeight);
    for (const segment of overlay.segments) {
      ctx.beginPath();
      ctx.moveTo(segment.from.x, segment.from.y);
      ctx.lineTo(segment.to.x, segment.to.y);
      ctx.strokeStyle = "#4ade80";
      ctx.lineWidth = 2;
      ctx.stroke();
    }
    for (const point of overlay.points) {
      ctx.beginPath();
      ctx.arc(point.x, point.y, 2, 0, Math.PI * 2);
      ctx.fillStyle = "#fbbf24";
      ctx.fill();
    }
  }, [currentDetection]);

  // Handlers
  const togglePlay = useCallback(() => {
    setPlaying((prev) => {
      if (!prev && frame >= frameCount && frameCount > 0) setFrame(1);
      return !prev;
    });
  }, [frame, frameCount]);

  const handleAddPin = useCallback(() => {
    console.log(`[WizardStep2] handleAddPin called, videoPath=${state.videoPath}, frame=${frame}`);
    if (!state.videoPath) return;
    usePinsStore.getState().addPin(nodeId, frame);
    const updated = usePinsStore.getState();
    const pins = updated.pinsByNode[nodeId] ?? [];
    const pin = pins[pins.length - 1];
    console.log(`[WizardStep2] Pin created:`, pin);
    if (pin) void updated.detectPin(nodeId, pin.id, state.videoPath);
  }, [state.videoPath, frame, nodeId]);

  const handleDeletePin = useCallback(
    (pinId: string) => {
      usePinsStore.getState().removePin(nodeId, pinId);
    },
    [nodeId],
  );

  const handleContinue = useCallback(() => {
    // Extract golden poses from pins
    const poses = nodePins
      .filter((p) => p.status === "success")
      .map((p) => ({
        frame: p.frame,
        label: p.label,
        confidence: p.confidence,
      }));
    onUpdate({ goldenPoses: poses });
    onNext();
  }, [nodePins, onUpdate, onNext]);

  return (
    <div style={styles.container}>
      <div style={styles.instructions}>
        <h2 style={styles.stepTitle}>Paso 2: Marca las poses clave</h2>
        <p style={styles.stepDesc}>
          Navega por el video y marca las poses importantes que quieres editar en Blender.
          Haz doble clic sobre el video o usa el botón "Marcar pose".
        </p>
      </div>

      {/* Video preview */}
      <div
        style={styles.videoContainer}
        onDoubleClick={(e) => {
          console.log(`[WizardStep2] Double-click detected at frame ${frame}`);
          handleAddPin();
        }}
      >
        {imgUrl && (
          <img
            ref={imgRef}
            src={imgUrl}
            alt="video frame"
            style={styles.videoFrame}
          />
        )}
        {overlayVisible && currentDetection !== null && (
          <canvas
            ref={overlayRef}
            style={styles.overlay}
          />
        )}
      </div>

      {/* Timeslider */}
      <div style={styles.timeslider}>
        <div ref={trackRef} style={styles.track}>
          <input
            type="range"
            min={1}
            max={Math.max(frameCount, 1)}
            value={frame}
            onChange={(e) => {
              const newFrame = Number(e.target.value);
              console.log(`[WizardStep2] Slider changed to frame ${newFrame}`);
              setFrame(newFrame);
            }}
            style={styles.slider}
          />
          {nodePins.map((pin) => {
            const left = frameCount > 1 ? ((pin.frame - 1) / (frameCount - 1)) * 100 : 0;
            return (
              <div
                key={pin.id}
                title={`${pin.label}: frame ${pin.frame}`}
                style={{
                  ...styles.pin,
                  left: `${left}%`,
                }}
              >
                <span>{pin.label}</span>
                <button
                  type="button"
                  onClick={() => handleDeletePin(pin.id)}
                  style={styles.deletePin}
                >
                  ✕
                </button>
              </div>
            );
          })}
        </div>
        <div style={styles.frameLabel}>
          Frame {frame} / {frameCount}
        </div>
      </div>

      {/* Controls */}
      <div style={styles.controls}>
        <button type="button" onClick={togglePlay} style={styles.playBtn}>
          {playing ? "⏸ Pausa" : "▶ Reproducir"}
        </button>
        <button type="button" onClick={handleAddPin} style={styles.markBtn}>
          ✏️ Marcar pose
        </button>
        <button
          type="button"
          onClick={() => setOverlayVisible((v) => !v)}
          style={styles.overlayBtn}
        >
          {overlayVisible ? "👁 Ocultar esqueleto" : "👁 Mostrar esqueleto"}
        </button>
      </div>

      {/* Poses summary */}
      {nodePins.length > 0 && (
        <div style={styles.summary}>
          <span style={styles.summaryTitle}>Poses marcadas: {nodePins.length}</span>
          <div style={styles.summaryList}>
            {nodePins.map((pin) => (
              <span key={pin.id} style={styles.summaryItem}>
                {pin.label} (frame {pin.frame})
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Navigation */}
      <div style={styles.navigation}>
        <button type="button" onClick={onPrev} style={styles.prevBtn}>
          ← Volver
        </button>
        <button
          type="button"
          onClick={handleContinue}
          disabled={nodePins.length === 0}
          style={{
            ...styles.nextBtn,
            ...(nodePins.length === 0 ? styles.nextBtnDisabled : {}),
          }}
        >
          Siguiente: Blender →
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
    gap: 16,
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
  videoContainer: {
    position: "relative",
    width: "100%",
    background: "#121212",
    border: "1px solid #333",
    borderRadius: 8,
    overflow: "hidden",
  },
  videoFrame: {
    width: "100%",
    display: "block",
  },
  overlay: {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    pointerEvents: "none",
  },
  timeslider: {
    width: "100%",
  },
  track: {
    position: "relative",
    height: 24,
  },
  slider: {
    width: "100%",
    margin: 0,
  },
  frameLabel: {
    textAlign: "center",
    fontSize: 12,
    color: "#6b7280",
    marginTop: 4,
  },
  pin: {
    position: "absolute",
    top: -4,
    transform: "translateX(-50%)",
    display: "flex",
    alignItems: "center",
    gap: 4,
    background: "#fbbf24",
    color: "#000",
    borderRadius: 4,
    padding: "2px 6px",
    fontSize: 10,
    fontWeight: 600,
    cursor: "grab",
    whiteSpace: "nowrap",
  },
  deletePin: {
    background: "none",
    border: "none",
    color: "#7f1d1d",
    cursor: "pointer",
    fontSize: 10,
    padding: 0,
    lineHeight: 1,
  },
  controls: {
    display: "flex",
    gap: 8,
    flexWrap: "wrap",
    justifyContent: "center",
  },
  playBtn: {
    padding: "8px 16px",
    background: "#1f2937",
    border: "1px solid #374151",
    borderRadius: 6,
    color: "#e5e7eb",
    fontSize: 13,
    cursor: "pointer",
  },
  markBtn: {
    padding: "8px 16px",
    background: "#854d0e",
    border: "1px solid #a16207",
    borderRadius: 6,
    color: "#fbbf24",
    fontSize: 13,
    fontWeight: 500,
    cursor: "pointer",
  },
  overlayBtn: {
    padding: "8px 16px",
    background: "#1f2937",
    border: "1px solid #374151",
    borderRadius: 6,
    color: "#e5e7eb",
    fontSize: 13,
    cursor: "pointer",
  },
  summary: {
    width: "100%",
    padding: 12,
    background: "#111827",
    border: "1px solid #374151",
    borderRadius: 8,
  },
  summaryTitle: {
    fontSize: 13,
    fontWeight: 500,
    color: "#fbbf24",
  },
  summaryList: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 8,
  },
  summaryItem: {
    padding: "4px 8px",
    background: "#1f2937",
    borderRadius: 4,
    fontSize: 11,
    color: "#d1d5db",
  },
  navigation: {
    display: "flex",
    gap: 12,
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
  nextBtn: {
    padding: "10px 20px",
    background: "#2563eb",
    border: "none",
    borderRadius: 8,
    color: "#fff",
    fontSize: 14,
    fontWeight: 500,
    cursor: "pointer",
  },
  nextBtnDisabled: {
    background: "#1e3a5f",
    color: "#6b7280",
    cursor: "not-allowed",
  },
};
