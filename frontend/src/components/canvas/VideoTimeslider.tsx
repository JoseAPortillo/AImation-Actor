/**
 * Video timeslider for `video-source` nodes (Phase A golden-poses-ux).
 *
 * Renders frames served by `GET /media/frame` (range sized from the
 * `X-Frame-Count` header), scrub + play controls, golden-pose pins (Phase A:
 * frontend-only, decision D2), a hover frame thumbnail, and a 2D skeleton
 * overlay for the current frame's detection. Pins live in `usePinsStore`
 * (keyed by node id); marking a pin auto-runs single-frame detection through
 * `detectPin` (⏳ → ✓/✗), and dragging a pin re-runs it — the store's D1
 * per-pin in-flight guard swallows any overlapping request.
 *
 * Network access goes through an injectable `ApiClient` (matches
 * useJobStore/usePinsStore) so the component is unit-testable without a live
 * backend.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiClient, DEFAULT_URL } from "../../api/ApiClient";
import { usePinsStore } from "../../state/usePinsStore";
import { drawSkeleton } from "../../core/skeletonOverlay";

/** Frame advance interval while playing (constant: no fps source on the slider). */
const PLAY_INTERVAL_MS = 80;
/** Reduced width for hover thumbnails so hovering stays light. */
const HOVER_THUMB_WIDTH = 160;
/** Main frame fetch width (~node card column width). */
const FRAME_WIDTH = 320;

const defaultApi = new ApiClient(DEFAULT_URL);

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

function statusGlyph(status: string, confidence: number | null): string {
  if (status === "processing") return "⏳";
  if (status === "success") return `✓ ${confidence !== null ? confidence.toFixed(2) : ""}`.trim();
  return "✗";
}

interface VideoTimesliderProps {
  nodeId: string;
  /** `video_path` param of the source node; null hides the slider (placeholder). */
  videoPath: string | null;
  /** Injectable for tests; defaults to a real client over the base URL. */
  api?: ApiClient;
}

export function VideoTimeslider({ nodeId, videoPath, api = defaultApi }: VideoTimesliderProps) {
  const nodePins = usePinsStore((s) => s.pinsByNode[nodeId]) ?? [];

  const [frame, setFrame] = useState(1);
  const [frameCount, setFrameCount] = useState(0);
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [overlayVisible, setOverlayVisible] = useState(true);
  const [hover, setHover] = useState<{ frame: number; url: string } | null>(null);
  const [dragPinId, setDragPinId] = useState<string | null>(null);

  const trackRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const imgUrlRef = useRef<string | null>(null);
  imgUrlRef.current = imgUrl;

  // ── Sync the injected api into the pin store so that detectPin calls
  // (which go through usePinsStore.getState().api) use the same client as
  // the component's frame-loading effects.
  useEffect(() => {
    usePinsStore.setState({ api });
  }, [api]);

  // ── Frame fetching: load `frame` whenever it (or the video) changes. A
  // generation token drops stale responses so a fast scrub never lands an
  // older frame over the newest one.
  useEffect(() => {
    if (!videoPath) return;
    const generation = ++generationCounter.current;
    let cancelled = false;
    let nextUrl: string | null = null;
    void (async () => {
      try {
        const { blob, frameCount: fc } = await api.fetchFrameJpeg(videoPath, frame, FRAME_WIDTH);
        if (cancelled) return;
        nextUrl = URL.createObjectURL(blob);
        setImgUrl((prev) => {
          if (prev) URL.revokeObjectURL(prev);
          return nextUrl;
        });
        setFrameCount(fc);
        setLoadError(null);
      } catch {
        if (!cancelled) setLoadError("failed to load frame");
        void generation;
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [videoPath, frame, api]);

  // ── Object URL lifecycle: revoke whatever is current on unmount.
  useEffect(() => {
    return () => {
      if (imgUrlRef.current) URL.revokeObjectURL(imgUrlRef.current);
    };
  }, []);

  // ── Playback: interval only runs while playing; stops at the last frame.
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

  // ── Hover thumbnail: fetch on hover-frame change, best-effort.
  const hoverFrame = hover?.frame;
  useEffect(() => {
    if (!videoPath || hoverFrame === undefined || hoverFrame === frame) return;
    let cancelled = false;
    let url: string | null = null;
    void (async () => {
      try {
        const { blob } = await api.fetchFrameJpeg(videoPath, hoverFrame, HOVER_THUMB_WIDTH);
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setHover((prev) => (prev && prev.frame === hoverFrame ? { ...prev, url } : prev));
      } catch {
        /* thumbnails are best-effort */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [videoPath, hoverFrame, frame, api]);

  useEffect(() => {
    const url = hover?.url;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [hover?.url]);

  // ── Overlay drawing: map the current frame's detection to display size.
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
    canvas.dataset.segments = String(overlay.segments.length);
    canvas.dataset.points = String(overlay.points.length);
    const ctx = canvas.getContext("2d");
    if (!ctx) return; // jsdom / SSR guard — segments metadata still exposed
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

  // ── Interaction helpers ──────────────────────────────────────────────────

  /** Map a clientX on the track to the nearest 1-based frame. */
  const frameFromClientX = useCallback(
    (clientX: number): number => {
      const track = trackRef.current;
      if (!track) return frame;
      if (frameCount <= 1) return 1;
      const rect = track.getBoundingClientRect();
      const t = clamp((clientX - rect.left) / Math.max(rect.width, 1), 0, 1);
      return 1 + Math.round(t * (frameCount - 1));
    },
    [frame, frameCount],
  );

  const togglePlay = useCallback(() => {
    setPlaying((prev) => {
      if (!prev && frame >= frameCount && frameCount > 0) setFrame(1);
      return !prev;
    });
  }, [frame, frameCount]);

  const handleAddPin = () => {
    if (!videoPath) return;
    usePinsStore.getState().addPin(nodeId, frame);
    // Re-read state after addPin() mutates it so we get the newly created pin.
    const updated = usePinsStore.getState();
    const pins = updated.pinsByNode[nodeId] ?? [];
    const pin = pins[pins.length - 1];
    if (pin) void updated.detectPin(nodeId, pin.id, videoPath);
  };

  const handleDeletePin = (pinId: string) => {
    usePinsStore.getState().removePin(nodeId, pinId);
  };

  const startDrag = (pinId: string) => (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragPinId(pinId);
  };

  const handleTrackMouseMove = (e: React.MouseEvent) => {
    if (dragPinId) return; // dragging — no hover thumbnail
    const nextFrame = frameFromClientX(e.clientX);
    setHover((prev) => (prev && prev.frame === nextFrame ? prev : { frame: nextFrame, url: "" }));
  };

  const endDrag = (e: React.MouseEvent) => {
    if (!dragPinId || !videoPath) {
      setDragPinId(null);
      return;
    }
    const pin = nodePins.find((p) => p.id === dragPinId);
    const targetFrame = frameFromClientX(e.clientX);
    if (pin && targetFrame !== pin.frame) {
      usePinsStore.getState().movePin(nodeId, dragPinId, targetFrame);
      // Stale detection: re-run at the new frame. The D1 per-pin guard in the
      // store swallows this call while the previous request is still in flight.
      void usePinsStore.getState().detectPin(nodeId, dragPinId, videoPath);
    }
    setDragPinId(null);
  };

  // ── Render ───────────────────────────────────────────────────────────────

  if (!videoPath) {
    return (
      <div data-testid="timeslider" style={{ marginBottom: 4 }}>
        <div
          data-testid="timeslider-placeholder"
          style={{
            fontSize: 10,
            color: "#9ca3af",
            textAlign: "center",
            padding: 12,
            border: "1px dashed #333",
            borderRadius: 6,
          }}
        >
          No video selected
        </div>
      </div>
    );
  }

  return (
    <div data-testid="timeslider" style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 4 }}>
      {/* Frame + overlay + hover thumbnail */}
      <div style={{ position: "relative", background: "#121212", border: "1px solid #333", borderRadius: 6, overflow: "hidden" }}>
        {imgUrl && (
          <img
            ref={imgRef}
            data-testid="timeslider-frame"
            src={imgUrl}
            alt="video frame"
            style={{ width: "100%", display: "block" }}
          />
        )}
        {overlayVisible && currentDetection !== null && (
          <canvas
            ref={overlayRef}
            data-testid="timeslider-overlay"
            style={{
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              pointerEvents: "none",
            }}
          />
        )}
        {hover?.url && (
          <img
            data-testid="timeslider-hover-thumb"
            src={hover.url}
            alt="frame thumbnail"
            style={{ position: "absolute", right: 4, bottom: 4, width: 84, border: "1px solid #555", borderRadius: 4 }}
          />
        )}
        {loadError && (
          <div data-testid="timeslider-error" role="alert" style={{ fontSize: 9, color: "#f87171", padding: 4 }}>
            {loadError}
          </div>
        )}
      </div>

      {/* Track: scrub input + golden pins */}
      <div
        data-testid="timeslider-track"
        ref={trackRef}
        onMouseMove={handleTrackMouseMove}
        onMouseUp={endDrag}
        onMouseLeave={() => {
          setHover(null);
          setDragPinId(null);
        }}
        style={{ position: "relative", height: 18 }}
      >
        <input
          data-testid="timeslider-scrub"
          type="range"
          min={1}
          max={Math.max(frameCount, 1)}
          value={frame}
          onChange={(e) => setFrame(Number(e.target.value))}
          style={{ width: "100%", margin: 0 }}
        />
        {nodePins.map((pin) => {
          const left = frameCount > 1 ? ((pin.frame - 1) / (frameCount - 1)) * 100 : 0;
          return (
            <div
              key={pin.id}
              data-testid="timeslider-pin"
              data-label={pin.label}
              data-status={pin.status}
              data-frame={pin.frame}
              onMouseDown={startDrag(pin.id)}
              title={`${pin.label}: frame ${pin.frame}, ${pin.status}`}
              aria-label={`${pin.label} frame ${pin.frame} ${pin.status}`}
              style={{
                position: "absolute",
                left: `${left}%`,
                top: 0,
                transform: "translateX(-50%)",
                display: "flex",
                alignItems: "center",
                gap: 2,
                background: "#1f2937",
                border: "1px solid #4b5563",
                borderRadius: 4,
                padding: "0 3px",
                fontSize: 9,
                color: "#e5e7eb",
                cursor: "grab",
                whiteSpace: "nowrap",
              }}
            >
              <span>{pin.label}</span>
              <span>{statusGlyph(pin.status, pin.confidence)}</span>
              <button
                type="button"
                data-testid="timeslider-delete-pin"
                aria-label={`Delete ${pin.label}`}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => handleDeletePin(pin.id)}
                style={{
                  background: "none",
                  border: "none",
                  color: "#f87171",
                  cursor: "pointer",
                  fontSize: 9,
                  padding: 0,
                  lineHeight: 1,
                }}
              >
                ✕
              </button>
            </div>
          );
        })}
      </div>

      {/* Controls */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10, color: "#e0e0e0" }}>
        <button
          type="button"
          data-testid="timeslider-play"
          onClick={togglePlay}
          style={{
            background: "#1a1a1a",
            border: "1px solid #333",
            borderRadius: 4,
            color: "#e0e0e0",
            padding: "2px 8px",
            cursor: "pointer",
            fontSize: 10,
          }}
        >
          {playing ? "Pause" : "Play"}
        </button>
        <span data-testid="timeslider-frame-label">
          {frame} / {frameCount}
        </span>
        <button
          type="button"
          data-testid="timeslider-add-pin"
          onClick={handleAddPin}
          style={{
            background: "#1a1a1a",
            border: "1px solid #333",
            borderRadius: 4,
            color: "#e0e0e0",
            padding: "2px 8px",
            cursor: "pointer",
            fontSize: 10,
          }}
        >
          Mark pin
        </button>
        <button
          type="button"
          data-testid="timeslider-overlay-toggle"
          onClick={() => setOverlayVisible((v) => !v)}
          style={{
            background: "#1a1a1a",
            border: "1px solid #333",
            borderRadius: 4,
            color: "#e0e0e0",
            padding: "2px 8px",
            cursor: "pointer",
            fontSize: 10,
          }}
        >
          {overlayVisible ? "Hide overlay" : "Show overlay"}
        </button>
      </div>
    </div>
  );
}

/** Module-level generation counter so every frame fetch has a unique token. */
const generationCounter = { current: 0 };