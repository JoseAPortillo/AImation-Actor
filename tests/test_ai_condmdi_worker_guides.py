"""The CondMDI request contract for guide frames (M6 T6, S6).

The capture between two human keys exists in the video, not in the timeline.
The fill request therefore accepts optional ``guide_frames`` - per-frame
captured poses between the keys - and the worker conditions the diffusion on
them exactly like the keys (the ``random_joints`` checkpoint was trained on
an observation at a random number of frames, so any frame count is
in-distribution). The worker contract pinned here:

- guide samples must stay inside ``0..span_frames`` and be unique;
- a guide colliding with a keyed sample is refused (keys win, explicitly);
- the returned obs sample plan is the sorted set of guide samples.
"""

from __future__ import annotations

import pytest

from aimation_actor.adapters.ai import condmdi_worker as W


def _guide(sample: int) -> dict:
    return {"sample": sample, "pose": {}}


def test_guides_extend_the_observed_samples_sorted() -> None:
    engine = W._CondMDIEngine.__new__(W._CondMDIEngine)
    samples = engine._guide_samples(
        span=30,
        keys=[{"sample": 0}, {"sample": 30}],
        guides=[_guide(20), _guide(7)],
    )
    assert samples == ([0, 7, 20, 30])


def test_no_guides_plans_only_the_keys() -> None:
    engine = W._CondMDIEngine.__new__(W._CondMDIEngine)
    samples = engine._guide_samples(
        span=30,
        keys=[{"sample": 0}, {"sample": 30}],
        guides=[],
    )
    assert samples == ([0, 30])


def test_a_guide_outside_the_span_is_refused() -> None:
    engine = W._CondMDIEngine.__new__(W._CondMDIEngine)
    with pytest.raises(W._RequestError, match="outside"):
        engine._guide_samples(
            span=30,
            keys=[{"sample": 0}, {"sample": 30}],
            guides=[_guide(31)],
        )
    with pytest.raises(W._RequestError, match="outside"):
        engine._guide_samples(
            span=30,
            keys=[{"sample": 0}, {"sample": 30}],
            guides=[_guide(-1)],
        )


def test_a_guide_on_a_keyed_sample_is_refused() -> None:
    """Keys win - and the contract says so instead of silently dropping."""
    engine = W._CondMDIEngine.__new__(W._CondMDIEngine)
    with pytest.raises(W._RequestError, match="keyed"):
        engine._guide_samples(
            span=30,
            keys=[{"sample": 0}, {"sample": 30}],
            guides=[_guide(30)],
        )


def test_duplicate_guides_are_refused() -> None:
    engine = W._CondMDIEngine.__new__(W._CondMDIEngine)
    with pytest.raises(W._RequestError, match="duplicate"):
        engine._guide_samples(
            span=30,
            keys=[{"sample": 0}, {"sample": 30}],
            guides=[_guide(10), _guide(10)],
        )
