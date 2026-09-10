"""Tests for the pure-domain quality metrics (plan §21 Phase 1).

Deterministic motions only: static frames score zero jitter/drift, a foot that
slides while in contact raises foot_sliding_score, motions without contact or
foot data score zero, and the report aggregates the right shape.
"""

from __future__ import annotations

from aimation_actor_core.domain.animation import (
    ContactFeed,
    FootContact,
    Frame,
    NeutralMeta,
    NeutralMotion,
    Pose,
    Transform3D,
)
from aimation_actor_core.domain.animation.metrics import (
    QualityReport,
    compute_metrics,
    foot_sliding_score,
    jitter_score,
    root_drift,
)


def _frame(
    number: int,
    root: tuple[float, float, float],
    left_foot: tuple[float, float, float] | None = None,
) -> Frame:
    """Build a frame with Root (and optionally LeftFoot) transforms."""
    transforms: dict[str, Transform3D] = {"Root": Transform3D(translation=root)}
    if left_foot is not None:
        transforms["LeftFoot"] = Transform3D(translation=left_foot)
    return Frame(frame=number, pose=Pose(transforms=transforms))


def _motion(
    frames: list[Frame],
    *,
    duration_frames: int,
    contacts: dict[str, ContactFeed] | None = None,
) -> NeutralMotion:
    return NeutralMotion(
        meta=NeutralMeta(duration_frames=duration_frames),
        frames=frames,
        contacts=contacts or {},
    )


def test_static_motion_scores_zero_jitter_and_drift() -> None:
    """Identical frames → jitter 0.0 and root_drift 0.0."""
    static = _motion(
        [
            _frame(1, (0.0, 0.0, 0.0)),
            _frame(2, (0.0, 0.0, 0.0)),
            _frame(3, (0.0, 0.0, 0.0)),
        ],
        duration_frames=3,
    )
    assert jitter_score(static) == 0.0
    assert root_drift(static) == 0.0


def test_single_frame_scores_zero() -> None:
    """Fewer than 2 frames → all temporal metrics are 0.0."""
    single = _motion([_frame(1, (5.0, 0.0, 0.0))], duration_frames=1)
    assert jitter_score(single) == 0.0
    assert foot_sliding_score(single) == 0.0
    assert root_drift(single) == 0.0


def test_jitter_detects_translation_delta() -> None:
    """A Root moving 2 units/frame yields jitter == 2.0."""
    moving = _motion(
        [
            _frame(1, (0.0, 0.0, 0.0)),
            _frame(2, (2.0, 0.0, 0.0)),
        ],
        duration_frames=2,
    )
    assert jitter_score(moving) == 2.0


def test_root_drift_measures_first_to_last() -> None:
    """root_drift is the distance between Root at frame[0] and frame[-1]."""
    drifting = _motion(
        [
            _frame(1, (0.0, 0.0, 0.0)),
            _frame(2, (0.0, 0.0, 0.0)),
            _frame(3, (3.0, 4.0, 0.0)),
        ],
        duration_frames=3,
    )
    assert root_drift(drifting) == 5.0


def test_root_drift_zero_without_root_bone() -> None:
    """A motion without a Root bone measures no drift."""
    anonymous = NeutralMotion(
        meta=NeutralMeta(duration_frames=2),
        frames=[Frame(frame=1, pose=Pose(transforms={})), Frame(frame=2, pose=Pose())],
    )
    assert root_drift(anonymous) == 0.0


def test_foot_sliding_detected_during_contact() -> None:
    """A planted foot sliding 2 units/frame horizontally scores > 0."""
    sliding = _motion(
        [
            _frame(1, (0.0, 0.0, 0.0), left_foot=(0.0, -42.0, 0.0)),
            _frame(2, (0.0, 0.0, 0.0), left_foot=(2.0, -42.0, 0.0)),
            _frame(3, (0.0, 0.0, 0.0), left_foot=(4.0, -42.0, 0.0)),
        ],
        duration_frames=3,
        contacts={"left_foot": ContactFeed(samples=[FootContact(frame=1, contact=True)])},
    )
    assert foot_sliding_score(sliding) == 2.0


def test_foot_sliding_ignores_non_contact_frames() -> None:
    """Horizontal motion outside contact frames does not add to the score."""
    moving_out_of_contact = _motion(
        [
            _frame(1, (0.0, 0.0, 0.0), left_foot=(0.0, -42.0, 0.0)),
            _frame(2, (0.0, 0.0, 0.0), left_foot=(100.0, -42.0, 0.0)),
        ],
        duration_frames=2,
        contacts={"left_foot": ContactFeed(samples=[FootContact(frame=1, contact=False)])},
    )
    assert foot_sliding_score(moving_out_of_contact) == 0.0


def test_foot_sliding_zero_without_data() -> None:
    """No contact frames and no foot bones → 0.0."""
    bare = _motion(
        [
            _frame(1, (0.0, 0.0, 0.0)),
            _frame(2, (0.0, 0.0, 0.0)),
        ],
        duration_frames=2,
    )
    assert foot_sliding_score(bare) == 0.0


def test_compute_metrics_report_shape() -> None:
    """compute_metrics aggregates all fields into a frozen QualityReport."""
    motion = _motion(
        [
            _frame(1, (0.0, 0.0, 0.0)),
            _frame(2, (1.0, 0.0, 0.0)),
        ],
        duration_frames=2,
    )
    report = compute_metrics(motion)

    assert isinstance(report, QualityReport)
    assert report.frames == 2
    assert report.duration_frames == 2
    assert report.jitter_score == 1.0
    assert report.root_drift == 1.0
    assert report.foot_sliding_score == 0.0
    # Frozen model: assignments must raise at runtime.
    try:
        report.frames = 99
    except ValueError:
        pass
    else:
        raise AssertionError("QualityReport must be frozen")