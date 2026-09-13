"""Pure-domain animation quality metrics (plan §21 Phase 1 validation).

Belongs to ``domain/animation`` (SDD §2.2): pydantic + domain types only, no
I/O, no infrastructure imports. These scores feed the Phase 1 validation gates:

- :func:`jitter_score` — temporal stability (per-bone translation deltas).
- :func:`foot_sliding_score` — foot sliding during contact windows.
- :func:`root_drift` — global locomotion drift of the root.

All translations are local (per-bone) in document units (typically ``cm``);
velocities are expressed per frame step (``units/frame``).
"""

from __future__ import annotations

import math
from itertools import pairwise

from pydantic import BaseModel, ConfigDict

from aimation_actor_core.domain.animation import NeutralMotion

#: Contact tracks and the neutral skeleton foot bones they map to.
FOOT_TRACKS = ("left_foot", "right_foot")
FOOT_BONES = ("LeftFoot", "RightFoot")


class QualityReport(BaseModel):
    """Aggregated quality metrics for one motion (plan §21 Phase 1).

    Attributes:
        jitter_score: Mean per-bone translation delta between consecutive
            frames (units/frame); 0.0 for <2 frames.
        foot_sliding_score: Mean horizontal (x,z) foot displacement per frame
            step during contact windows (units/frame); 0.0 with no data.
        root_drift: Euclidean distance between the Root bone at the first and
            last frame, in document units; 0.0 when not measurable.
        frames: Number of frames in the document (``frames`` list).
        duration_frames: Declared timeline duration (``meta.duration_frames``).
    """

    model_config = ConfigDict(frozen=True)

    jitter_score: float
    foot_sliding_score: float
    root_drift: float
    frames: int
    duration_frames: int


def _euclidean(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Euclidean distance between two 3D points: ``sqrt(sum((a_i - b_i)^2))``."""
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _horizontal_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Horizontal (x, z) distance between two 3D points, ignoring y: ``sqrt((dx)^2 + (dz)^2)``."""
    return math.sqrt((a[0] - b[0]) ** 2 + (a[2] - b[2]) ** 2)


def _contact_frames_by_height(motion: NeutralMotion) -> set[int]:
    """Frames whose foot bones sit at or below 20% of the global minimum foot height.

    Uses local translations (up-Y): a foot near the document's lowest point is
    considered planted. Returns an empty set when no foot bone exists.
    """
    min_y: float | None = None
    for frame in motion.frames:
        for bone in FOOT_BONES:
            transform = frame.pose.transforms.get(bone)
            if transform is not None:
                y = transform.translation[1]
                min_y = y if min_y is None else min(min_y, y)
    if min_y is None:
        return set()
    threshold = 0.2 * min_y
    planted: set[int] = set()
    for frame in motion.frames:
        for bone in FOOT_BONES:
            transform = frame.pose.transforms.get(bone)
            if transform is not None and transform.translation[1] <= threshold:
                planted.add(frame.frame)
    return planted


def _contact_frames(motion: NeutralMotion) -> set[int]:
    """Frames in contact, from ``motion.contacts`` or the height fallback.

    Contact tracks use ``left_foot``/``right_foot``; a track that carries any
    samples is authoritative (only ``contact=True`` frames count, so an
    explicit ``contact=False`` label is never treated as planted). When no
    track carries any samples, falls back to :func:`_contact_frames_by_height`
    (≤20% of the global minimum foot height).
    """
    contact: set[int] = set()
    has_samples = False
    for track in FOOT_TRACKS:
        feed = motion.contacts.get(track)
        if feed is not None and feed.samples:
            has_samples = True
            contact.update(sample.frame for sample in feed.samples if sample.contact)
    if has_samples:
        return contact
    return _contact_frames_by_height(motion)


def jitter_score(motion: NeutralMotion) -> float:
    """Mean per-bone translation delta between consecutive frames.

    Formula: ``mean(||translation(bone, f+1) - translation(bone, f)||_2)`` over
    every bone present in both consecutive frames. Measures temporal stability
    of the pose (plan §21 Phase 1: "Temporal stability"). Returns 0.0 when the
    motion has fewer than 2 frames or no shared-bone deltas exist.

    Args:
        motion: The motion to score.

    Returns:
        Mean per-bone translation delta in units/frame, or 0.0.
    """
    frames = motion.frames
    if len(frames) < 2:
        return 0.0
    deltas: list[float] = []
    for previous, current in pairwise(frames):
        shared = previous.pose.transforms.keys() & current.pose.transforms.keys()
        for bone in shared:
            deltas.append(
                _euclidean(
                    previous.pose.transforms[bone].translation,
                    current.pose.transforms[bone].translation,
                )
            )
    if not deltas:
        return 0.0
    return sum(deltas) / len(deltas)


def foot_sliding_score(motion: NeutralMotion) -> float:
    """Mean horizontal velocity of foot bones while they are in contact.

    Formula: ``mean(||(x, z)(foot, f+1) - (x, z)(foot, f)||_2)`` over foot bones
    whose frame ``f`` is a contact frame. Contact frames come from
    ``motion.contacts`` (``left_foot``/``right_foot`` tracks; a track with
    samples is authoritative, only ``contact=True`` frames count). When no
    track carries samples, the height fallback flags frames whose foot bones
    sit at or below 20% of the global minimum foot height. A planted foot
    should keep this near zero. Returns 0.0 with fewer than 2 frames, no
    contact frames, or no foot data.

    Args:
        motion: The motion to score.

    Returns:
        Mean horizontal foot displacement per frame step in units/frame.
    """
    frames = motion.frames
    if len(frames) < 2:
        return 0.0
    contact = _contact_frames(motion)
    if not contact:
        return 0.0
    speeds: list[float] = []
    for previous, current in pairwise(frames):
        if previous.frame not in contact:
            continue
        for bone in FOOT_BONES:
            prev_transform = previous.pose.transforms.get(bone)
            curr_transform = current.pose.transforms.get(bone)
            if prev_transform is not None and curr_transform is not None:
                speeds.append(
                    _horizontal_distance(prev_transform.translation, curr_transform.translation)
                )
    if not speeds:
        return 0.0
    return sum(speeds) / len(speeds)


def root_drift(motion: NeutralMotion) -> float:
    """Distance between the Root bone at the first and last frame.

    Formula: ``||translation(Root, frame[-1]) - translation(Root, frame[0])||_2``
    in document units (typically cm). Global locomotion drift of the character;
    a walk-in-place clip should keep this small. Returns 0.0 with fewer than 2
    frames or when the Root bone is missing from either endpoint.

    Args:
        motion: The motion to score.

    Returns:
        Root displacement in document units, or 0.0.
    """
    frames = motion.frames
    if len(frames) < 2:
        return 0.0
    first = frames[0].pose.transforms.get("Root")
    last = frames[-1].pose.transforms.get("Root")
    if first is None or last is None:
        return 0.0
    return _euclidean(first.translation, last.translation)


def compute_metrics(motion: NeutralMotion) -> QualityReport:
    """Compute the full :class:`QualityReport` for ``motion``.

    Args:
        motion: The motion to score.

    Returns:
        A frozen :class:`QualityReport` with the three scores plus frame counts.
    """
    return QualityReport(
        jitter_score=jitter_score(motion),
        foot_sliding_score=foot_sliding_score(motion),
        root_drift=root_drift(motion),
        frames=len(motion.frames),
        duration_frames=motion.meta.duration_frames,
    )