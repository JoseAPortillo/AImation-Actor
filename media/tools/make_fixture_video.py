"""Generate the deterministic walk-cycle fixture video.

Writes ``media/videos/fixture_walk.mp4``: a 256x256, 24 fps, ~2 s clip of a
simple rectangular figure (head + torso + arms + legs) walking in place with a
slight sinusoidal lateral drift on a dark background. Deterministic — a fixed
numpy seed plus procedural sinusoids — so downstream video→motion tests always
see the same input.

Requires the ``ai`` extras (``opencv-python-headless`` + ``numpy``).
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

SEED = 42
WIDTH = 256
HEIGHT = 256
FPS = 24
FRAMES = 48
BACKGROUND = (24, 24, 32)
FIGURE = (210, 210, 215)
OUTPUT = Path(__file__).resolve().parent.parent / "videos" / "fixture_walk.mp4"


def _rect(canvas: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> None:
    """Fill an axis-aligned rectangle on ``canvas``, clamped to bounds."""
    left, right = min(x1, x2), max(x1, x2)
    top, bottom = min(y1, y2), max(y1, y2)
    cv2.rectangle(
        canvas,
        (max(0, left), max(0, top)),
        (min(WIDTH - 1, right), min(HEIGHT - 1, bottom)),
        FIGURE,
        thickness=-1,
    )


def _draw_frame(index: int, rng: np.random.Generator) -> np.ndarray:
    """Render one 256x256 frame of the walk cycle."""
    canvas = np.full((HEIGHT, WIDTH, 3), BACKGROUND, dtype=np.uint8)
    phase = 2.0 * math.pi * index / FRAMES
    drift = round(6.0 * math.sin(phase))  # slight sinusoidal lateral drift
    bob = round(3.0 * math.sin(2.0 * phase) + float(rng.uniform(-1.0, 1.0)))
    center_x = WIDTH // 2 + drift
    hip_y = 138 + bob

    leg_swing_left = 16 * math.sin(phase)
    leg_swing_right = 16 * math.sin(phase + math.pi)
    arm_swing_left = 10 * math.sin(phase + math.pi)
    arm_swing_right = 10 * math.sin(phase)

    # Torso.
    _rect(canvas, center_x - 12, hip_y - 52, center_x + 12, hip_y)
    # Head.
    _rect(canvas, center_x - 13, hip_y - 88, center_x + 13, hip_y - 62)
    # Legs (alternating forward/back swing).
    _rect(
        canvas,
        center_x - 24 + round(leg_swing_left),
        hip_y,
        center_x - 8 + round(leg_swing_left),
        hip_y + 74,
    )
    _rect(
        canvas,
        center_x + 8 + round(leg_swing_right),
        hip_y,
        center_x + 24 + round(leg_swing_right),
        hip_y + 74,
    )
    # Arms (counter-swinging relative to the same-side leg).
    _rect(
        canvas,
        center_x - 34 + round(arm_swing_left),
        hip_y - 52,
        center_x - 18 + round(arm_swing_left),
        hip_y - 26,
    )
    _rect(
        canvas,
        center_x + 18 + round(arm_swing_right),
        hip_y - 52,
        center_x + 34 + round(arm_swing_right),
        hip_y - 26,
    )
    return canvas


def main() -> Path:
    """Render the clip and write it to ``OUTPUT``; return the output path.

    Raises:
        RuntimeError: If OpenCV cannot open the video writer.
    """
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(OUTPUT), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError(f"cv2.VideoWriter could not open {OUTPUT}")
    try:
        rng = np.random.default_rng(SEED)
        for index in range(FRAMES):
            writer.write(_draw_frame(index, rng))
    finally:
        writer.release()
    return OUTPUT


if __name__ == "__main__":
    print(f"wrote {main()}")