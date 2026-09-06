"""Unit tests for the temporal cleanup domain math (§12.4 / temporal-cleanup).

Covers the five sub-stage deterministic stateless chain in
:mod:`aimation_actor_core.domain.animation.cleanup`: one-euro jitter
smoothing, foot-contact detection (with hysteresis), translation-only foot
locking, ground clamping, and root drift normalization. All fixtures build
``NeutralMotion`` documents in LOCAL coordinate space (child-parent offsets,
matching ``VideoToMotionNode`` in ``only_local`` mode) so every real
assertion exercises production math.
"""

from __future__ import annotations

import statistics

import pytest

from aimation_actor_core.domain.animation.cleanup import CleanupParams, cleanup_motion
from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.neutral_motion import NeutralMotion
from aimation_actor_core.domain.animation.skeleton import Bone, Skeleton

#: A foot in local space that, with Hips at world Y=95, sits at world Y=5
#: (below the default height_threshold=10 -> contact-eligible).
_HIPS_Y = 95.0
_LFOOT_Y = -42.0
_RFOOT_Y = -42.0


def _bone(name: str, parent: str | None) -> Bone:
    return Bone(name=name, parent=parent, rest_position=(0.0, 0.0, 0.0))


def _leg_skeleton() -> Skeleton:
    """A minimal single-rooted leg skeleton (Root + hips + two leg chains)."""
    return Skeleton(
        bones={
            "Root": _bone("Root", None),
            "Hips": _bone("Hips", "Root"),
            "LeftUpLeg": _bone("LeftUpLeg", "Hips"),
            "LeftLeg": _bone("LeftLeg", "LeftUpLeg"),
            "LeftFoot": _bone("LeftFoot", "LeftLeg"),
            "RightUpLeg": _bone("RightUpLeg", "Hips"),
            "RightLeg": _bone("RightLeg", "RightUpLeg"),
            "RightFoot": _bone("RightFoot", "RightLeg"),
        }
    )


def _f(motion: NeutralMotion, frame_idx: int, bone: str) -> Transform3D:
    """Return the transform of ``bone`` in frame ``frame_idx``."""
    return motion.frames[frame_idx].pose.transforms[bone]


def _world_y(motion: NeutralMotion, frame_idx: int, bone: str) -> float:
    """Accumulate ``bone``'s world Y by walking local offsets up to the root."""
    name = bone
    acc = 0.0
    while True:
        b = motion.skeleton.bones[name]
        t = motion.frames[frame_idx].pose.transforms.get(name)
        acc += t.translation[1] if t is not None else b.rest_position[1]
        if b.parent is None:
            return acc
        name = b.parent


def _traj(motion: NeutralMotion, bone: str, axis: int) -> list[float]:
    """Extract one translation axis track for ``bone`` across all frames."""
    return [_f(motion, i, bone).translation[axis] for i in range(len(motion.frames))]


def _make_motion(per_frame: list[list[tuple[str, tuple[float, float, float]]]]) -> NeutralMotion:
    """Build a NeutralMotion from per-frame bone translation entries.

    Each element of ``per_frame`` is a list of ``(bone, (x, y, z))`` LOCAL
    translation entries; ``rotation`` stays identity unless overridden.
    """
    frames = [
        Frame(
            frame=i + 1,
            time=(i + 1) / 24.0,
            pose=Pose(
                transforms={
                    name: Transform3D(translation=xform, rotation=rot)
                    for name, xform, rot in [
                        (*entry, (1.0, 0.0, 0.0, 0.0)) for entry in frame_entries
                    ]
                }
            ),
        )
        for i, frame_entries in enumerate(per_frame)
    ]
    motion = NeutralMotion(skeleton=_leg_skeleton(), frames=frames)
    motion.validate_invariants()
    return motion


class TestOneEuro:
    """One-Euro jitter smoothing."""

    def test_one_euro_reduces_jitter(self) -> None:
        """High-frequency translation jitter must be smoothed (variance drops)."""
        # LeftFoot high above ground (non-contact) so only smoothing applies.
        noise = [0.1 if i % 2 else -0.1 for i in range(24)]
        per_frame = []
        for i in range(24):
            per_frame.append(
                [
                    ("Root", (0.0, 0.0, 0.0)),
                    ("Hips", (0.0, _HIPS_Y, 0.0)),
                    ("LeftUpLeg", (0.0, -8.0, 0.0)),
                    ("LeftLeg", (0.0, -40.0, 0.0)),
                    ("LeftFoot", (0.0, -20.0 + 0.0 * _HIPS_Y, 0.0)),  # world Y=27, non-contact
                    ("RightUpLeg", (0.0, -8.0, 0.0)),
                    ("RightLeg", (0.0, -40.0, 0.0)),
                    ("RightFoot", (noise[i], -20.0, 0.0)),
                ]
            )
        inp = _make_motion(per_frame)
        out = cleanup_motion(inp)
        v_in = statistics.variance(_traj(inp, "RightFoot", 0))
        v_out = statistics.variance(_traj(out, "RightFoot", 0))
        assert v_out < v_in

    def test_one_euro_determinism(self) -> None:
        """Running cleanup twice on the same input yields byte-identical output."""
        per_frame = []
        for i in range(12):
            per_frame.append(
                [
                    ("Root", (0.0, 0.0, 0.0)),
                    ("Hips", (0.0, _HIPS_Y, 0.0)),
                    ("LeftUpLeg", (0.0, -8.0, 0.0)),
                    ("LeftLeg", (0.0, -40.0, 0.0)),
                    ("LeftFoot", ((0.15 if i % 2 else -0.15), -42.0, 0.0)),
                    ("RightUpLeg", (0.0, -8.0, 0.0)),
                    ("RightLeg", (0.0, -40.0, 0.0)),
                    ("RightFoot", (0.0, -42.0, 0.0)),
                ]
            )
        inp = _make_motion(per_frame)
        a = cleanup_motion(inp)
        b = cleanup_motion(inp)
        assert a.model_dump() == b.model_dump()

    def test_one_euro_passthrough(self) -> None:
        """Already-smooth trajectories must be materially unchanged (no artifacts)."""
        per_frame = []
        for i in range(12):
            per_frame.append(
                [
                    ("Root", (0.0, 0.0, 0.0)),
                    ("Hips", (0.0, _HIPS_Y, 0.0)),
                    ("LeftUpLeg", (0.0, -8.0, 0.0)),
                    ("LeftLeg", (0.0, -40.0, 0.0)),
                    ("LeftFoot", (i * 0.05, -20.0, 0.0)),  # world Y=27, non-contact
                    ("RightUpLeg", (0.0, -8.0, 0.0)),
                    ("RightLeg", (0.0, -40.0, 0.0)),
                    ("RightFoot", (0.0, -42.0, 0.0)),
                ]
            )
        inp = _make_motion(per_frame)
        out = cleanup_motion(inp)
        in_x = _traj(inp, "LeftFoot", 0)
        out_x = _traj(out, "LeftFoot", 0)
        # A gentle ramp is preserved to within a small bound (no added artifacts).
        assert all(abs(o - v) < 0.5 for o, v in zip(out_x, in_x, strict=True))


class TestContactDetection:
    """Foot-contact detection with hysteresis."""

    def test_contact_detection_marks_frames(self) -> None:
        """A stationary foot near the ground is marked as contact on every frame."""
        per_frame = []
        for _ in range(5):
            per_frame.append(
                [
                    ("Root", (0.0, 0.0, 0.0)),
                    ("Hips", (0.0, _HIPS_Y, 0.0)),
                    ("LeftUpLeg", (0.0, -8.0, 0.0)),
                    ("LeftLeg", (0.0, -40.0, 0.0)),
                    ("LeftFoot", (0.0, _LFOOT_Y, 0.0)),  # world Y=5, velocity 0
                    ("RightUpLeg", (0.0, -8.0, 0.0)),
                    ("RightLeg", (0.0, -40.0, 0.0)),
                    ("RightFoot", (0.0, _RFOOT_Y, 0.0)),
                ]
            )
        out = cleanup_motion(_make_motion(per_frame))
        left = out.contacts["left_foot"].samples
        right = out.contacts["right_foot"].samples
        assert len(left) == 5
        assert all(s.contact for s in left)
        assert all(s.contact for s in right)
        # Samples carry the 1-based frame numbers.
        assert [s.frame for s in left] == [1, 2, 3, 4, 5]

    def test_hysteresis_prevents_flicker(self) -> None:
        """A one-frame non-contact blip must not flip the held contact state."""
        per_frame = []
        for i in range(9):
            # Frames 0-4 and 6-8: foot on ground. Frame 5: foot lifted (non-contact).
            lfoot_y = -20.0 if i == 5 else _LFOOT_Y
            # world Y for lifted foot = 95-8-40-20 = 27 > 10 -> non-contact.
            per_frame.append(
                [
                    ("Root", (0.0, 0.0, 0.0)),
                    ("Hips", (0.0, _HIPS_Y, 0.0)),
                    ("LeftUpLeg", (0.0, -8.0, 0.0)),
                    ("LeftLeg", (0.0, -40.0, 0.0)),
                    ("LeftFoot", (0.0, lfoot_y, 0.0)),
                    ("RightUpLeg", (0.0, -8.0, 0.0)),
                    ("RightLeg", (0.0, -40.0, 0.0)),
                    ("RightFoot", (0.0, _RFOOT_Y, 0.0)),
                ]
            )
        out = cleanup_motion(_make_motion(per_frame), CleanupParams(hysteresis_frames=4))
        left = out.contacts["left_foot"].samples
        # With hysteresis the brief non-contact frame is held as contact (no flicker).
        assert left[5].contact is True
        assert all(s.contact for s in left)

    def test_param_override_lower_hysteresis_tracks_blip(self) -> None:
        """Small hysteresis lets a sustained non-contact blip break the hold."""
        per_frame = []
        for i in range(5):
            # A 2-frame non-contact blip at frames 3 and 4 (1-based frame 3,4).
            lfoot_y = -20.0 if i in (2, 3) else _LFOOT_Y
            per_frame.append(
                [
                    ("Root", (0.0, 0.0, 0.0)),
                    ("Hips", (0.0, _HIPS_Y, 0.0)),
                    ("LeftUpLeg", (0.0, -8.0, 0.0)),
                    ("LeftLeg", (0.0, -40.0, 0.0)),
                    ("LeftFoot", (0.0, lfoot_y, 0.0)),
                    ("RightUpLeg", (0.0, -8.0, 0.0)),
                    ("RightLeg", (0.0, -40.0, 0.0)),
                    ("RightFoot", (0.0, _RFOOT_Y, 0.0)),
                ]
            )
        out = cleanup_motion(_make_motion(per_frame), CleanupParams(hysteresis_frames=1))
        left = out.contacts["left_foot"].samples
        # hysteresis_frames=1 -> the first blip frame is still held, the second
        # breaks contact, distinguishing real detection from a guardrail that
        # never breaks contact.
        assert left[2].contact is True
        assert left[3].contact is False


class TestFootLock:
    """Translation-only foot locking."""

    def test_foot_lock_xz_clamp(self) -> None:
        """A contact foot is pinned to its contact-frame XZ; rotation is untouched."""
        per_frame = []
        for i in range(6):
            # LeftFoot: static height (contact), drifts in X -> gets clamped.
            # RightFoot: high velocity in X -> non-contact -> stays free.
            per_frame.append(
                [
                    ("Root", (0.0, 0.0, 0.0)),
                    ("Hips", (0.0, _HIPS_Y, 0.0)),
                    ("LeftUpLeg", (0.0, -8.0, 0.0)),
                    ("LeftLeg", (0.0, -40.0, 0.0)),
                    ("LeftFoot", (i * 0.4, _LFOOT_Y, 0.0)),
                    ("RightUpLeg", (0.0, -8.0, 0.0)),
                    ("RightLeg", (0.0, -40.0, 0.0)),
                    ("RightFoot", (i * 8.0, _RFOOT_Y, 0.0)),  # velocity 8 > threshold
                ]
            )
        # Give LeftFoot a real (non-identity) rotation to prove it survives.
        per_frame[0][-4 + 4] = ("LeftFoot", (0.0, _LFOOT_Y, 0.0))
        inp = _make_motion(per_frame)
        inp = inp.model_copy(
            update={
                "frames": [
                    f.model_copy(
                        update={
                            "pose": f.pose.model_copy(
                                update={
                                    "transforms": {
                                        **f.pose.transforms,
                                        "LeftFoot": f.pose.transforms["LeftFoot"].model_copy(
                                            update={"rotation": (0.70710678, 0.70710678, 0.0, 0.0)}
                                        ),
                                    }
                                }
                            )
                        }
                    )
                    for f in inp.frames
                ]
            }
        )
        out = cleanup_motion(inp)
        lx = _traj(out, "LeftFoot", 0)
        # All contact (locked) frames pinned to the contact-frame XZ (zero drift).
        assert all(abs(x) < 1e-9 for x in lx)
        # Rotation is NOT modified by the lock.
        for i in range(len(out.frames)):
            assert out.frames[i].pose.transforms["LeftFoot"].rotation == pytest.approx(
                (0.70710678, 0.70710678, 0.0, 0.0)
            )

    def test_non_contact_foot_free(self) -> None:
        """A non-contact foot is not clamped (its X track still varies)."""
        per_frame = []
        for i in range(6):
            per_frame.append(
                [
                    ("Root", (0.0, 0.0, 0.0)),
                    ("Hips", (0.0, _HIPS_Y, 0.0)),
                    ("LeftUpLeg", (0.0, -8.0, 0.0)),
                    ("LeftLeg", (0.0, -40.0, 0.0)),
                    ("LeftFoot", (0.0, _LFOOT_Y, 0.0)),  # contact
                    ("RightUpLeg", (0.0, -8.0, 0.0)),
                    ("RightLeg", (0.0, -40.0, 0.0)),
                    ("RightFoot", (i * 8.0, _RFOOT_Y, 0.0)),  # non-contact
                ]
            )
        out = cleanup_motion(_make_motion(per_frame))
        rx = _traj(out, "RightFoot", 0)
        # Not clamped -> the X track is not a single pinned value.
        assert len(set(rx)) > 1


class TestGroundClamp:
    """Ground clamping (Y >= 0, hips raised by penetration delta)."""

    def test_ground_clamp_y_gte_zero(self) -> None:
        """Penetrating feet are raised to Y>=0 and hips rise by the delta."""
        per_frame = []
        for _ in range(3):
            per_frame.append(
                [
                    ("Root", (0.0, 0.0, 0.0)),
                    ("Hips", (0.0, _HIPS_Y, 0.0)),
                    ("LeftUpLeg", (0.0, -8.0, 0.0)),
                    ("LeftLeg", (0.0, -40.0, 0.0)),
                    ("LeftFoot", (0.0, -50.0, 0.0)),  # world Y=95-8-40-50=-3 -> penetrates
                    ("RightUpLeg", (0.0, -8.0, 0.0)),
                    ("RightLeg", (0.0, -40.0, 0.0)),
                    ("RightFoot", (0.0, _RFOOT_Y, 0.0)),  # world Y=5
                ]
            )
        inp = _make_motion(per_frame)
        out = cleanup_motion(inp)
        # No foot may sit below the floor in the output.
        for i in range(len(out.frames)):
            assert _world_y(out, i, "LeftFoot") >= -1e-9
            assert _world_y(out, i, "RightFoot") >= -1e-9
        # Hips raised by the penetration delta (3.0): 95 -> 98.
        assert _traj(out, "Hips", 1) == pytest.approx([98.0] * 3)

    def test_above_floor_unchanged(self) -> None:
        """A motion already above the floor is unchanged by the clamp."""
        per_frame = []
        for _ in range(3):
            per_frame.append(
                [
                    ("Root", (0.0, 0.0, 0.0)),
                    ("Hips", (0.0, _HIPS_Y, 0.0)),
                    ("LeftUpLeg", (0.0, -8.0, 0.0)),
                    ("LeftLeg", (0.0, -40.0, 0.0)),
                    ("LeftFoot", (0.0, -20.0, 0.0)),  # world Y=27
                    ("RightUpLeg", (0.0, -8.0, 0.0)),
                    ("RightLeg", (0.0, -40.0, 0.0)),
                    ("RightFoot", (0.0, _RFOOT_Y, 0.0)),
                ]
            )
        inp = _make_motion(per_frame)
        out = cleanup_motion(inp)
        # Hips stays at its original height (no penetration -> no raise).
        assert _traj(out, "Hips", 1) == pytest.approx([_HIPS_Y] * 3)


class TestRootNormalization:
    """Root drift normalization."""

    def test_root_normalization_removes_drift(self) -> None:
        """Cumulative root drift is removed while child offsets are preserved."""
        n = 10
        per_frame = []
        for i in range(n):
            per_frame.append(
                [
                    ("Root", (0.0, 0.0, 0.0)),
                    ("Hips", (i * 0.5, _HIPS_Y, 0.0)),  # linear drift in X
                    ("LeftUpLeg", (0.0, -8.0, 0.0)),
                    ("LeftLeg", (0.0, -40.0, 0.0)),
                    ("LeftFoot", (0.0, -20.0, 0.0)),  # world Y=27, non-contact
                    ("RightUpLeg", (0.0, -8.0, 0.0)),
                    ("RightLeg", (0.0, -40.0, 0.0)),
                    ("RightFoot", (0.0, -20.0, 0.0)),
                ]
            )
        inp = _make_motion(per_frame)
        out = cleanup_motion(inp)
        hx = _traj(out, "Hips", 0)
        # Linear drift removed -> the root returns to its starting X (drift == 0).
        assert hx[-1] == pytest.approx(hx[0], abs=1e-9)
        assert hx[0] == pytest.approx(0.0, abs=1e-9)
        # Child local offset (relative motion) is preserved unchanged.
        assert _traj(out, "LeftFoot", 0) == pytest.approx([0.0] * n, abs=1e-9)

    def test_root_normalization_preserves_relative_motion(self) -> None:
        """Per-frame oscillation is preserved once the net drift is removed."""
        n = 10
        per_frame = []
        for i in range(n):
            osc = 0.3 if i % 2 else -0.3
            per_frame.append(
                [
                    ("Root", (0.0, 0.0, 0.0)),
                    ("Hips", (i * 0.5 + osc, _HIPS_Y, 0.0)),
                    ("LeftUpLeg", (0.0, -8.0, 0.0)),
                    ("LeftLeg", (0.0, -40.0, 0.0)),
                    ("LeftFoot", (0.0, -20.0, 0.0)),
                    ("RightUpLeg", (0.0, -8.0, 0.0)),
                    ("RightLeg", (0.0, -40.0, 0.0)),
                    ("RightFoot", (0.0, -20.0, 0.0)),
                ]
            )
        inp = _make_motion(per_frame)
        out = cleanup_motion(inp)
        hx = _traj(out, "Hips", 0)
        # Net drift removed ...
        assert hx[-1] == pytest.approx(hx[0], abs=1e-9)
        # ... but the per-frame oscillation (relative motion) is still present.
        assert len(set(hx)) > 1
        # Child offset preserved too.
        assert _traj(out, "LeftFoot", 0) == pytest.approx([0.0] * n, abs=1e-9)

    def test_zero_drift_passthrough(self) -> None:
        """No drift -> root translation is left unchanged."""
        per_frame = []
        for _ in range(4):
            per_frame.append(
                [
                    ("Root", (0.0, 0.0, 0.0)),
                    ("Hips", (5.0, _HIPS_Y, 3.0)),  # constant, no drift
                    ("LeftUpLeg", (0.0, -8.0, 0.0)),
                    ("LeftLeg", (0.0, -40.0, 0.0)),
                    ("LeftFoot", (0.0, -20.0, 0.0)),
                    ("RightUpLeg", (0.0, -8.0, 0.0)),
                    ("RightLeg", (0.0, -40.0, 0.0)),
                    ("RightFoot", (0.0, -20.0, 0.0)),
                ]
            )
        inp = _make_motion(per_frame)
        out = cleanup_motion(inp)
        assert _traj(out, "Hips", 0) == pytest.approx([5.0] * 4)
        assert _traj(out, "Hips", 2) == pytest.approx([3.0] * 4)


class TestPipeline:
    """Processing order and end-to-end determinism."""

    def test_processing_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The five sub-stages run sequentially in the fixed order."""
        import aimation_actor_core.domain.animation.cleanup as cleanup

        order: list[str] = []
        names = [
            "_one_euro_smooth",
            "_detect_contacts",
            "_apply_foot_lock",
            "_apply_ground_clamp",
            "_normalize_root",
        ]

        real = {n: getattr(cleanup, n) for n in names}
        for n in names:

            def make(name: str) -> object:
                def patched(motion: NeutralMotion, params: CleanupParams) -> NeutralMotion:
                    order.append(name)
                    return real[name](motion, params)

                return patched

            monkeypatch.setattr(cleanup, n, make(n))

        per_frame = [
            [
                ("Root", (0.0, 0.0, 0.0)),
                ("Hips", (0.0, _HIPS_Y, 0.0)),
                ("LeftUpLeg", (0.0, -8.0, 0.0)),
                ("LeftLeg", (0.0, -40.0, 0.0)),
                ("LeftFoot", (0.0, _LFOOT_Y, 0.0)),
                ("RightUpLeg", (0.0, -8.0, 0.0)),
                ("RightLeg", (0.0, -40.0, 0.0)),
                ("RightFoot", (0.0, _RFOOT_Y, 0.0)),
            ]
        ]
        cleanup_motion(_make_motion(per_frame))
        assert order == names

    def test_full_cleanup_determinism(self) -> None:
        """Identical inputs yield byte-identical output across the whole chain."""
        per_frame = []
        for i in range(8):
            per_frame.append(
                [
                    ("Root", (0.0, 0.0, 0.0)),
                    ("Hips", (i * 0.3, _HIPS_Y, 0.0)),
                    ("LeftUpLeg", (0.0, -8.0, 0.0)),
                    ("LeftLeg", (0.0, -40.0, 0.0)),
                    ("LeftFoot", (0.0, _LFOOT_Y, 0.0)),
                    ("RightUpLeg", (0.0, -8.0, 0.0)),
                    ("RightLeg", (0.0, -40.0, 0.0)),
                    ("RightFoot", (0.0, _RFOOT_Y, 0.0)),
                ]
            )
        # LeftFoot world Y = 5 and velocity 0 -> contact; Hips drifts.
        inp = _make_motion(per_frame)
        a = cleanup_motion(inp)
        b = cleanup_motion(inp)
        assert a.model_dump() == b.model_dump()
