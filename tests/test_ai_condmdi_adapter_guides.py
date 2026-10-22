"""The CondMDI adapter's guide-frame mapping (M6 T7, S6).

Guide poses (captured frames between the keys, produced by the controller)
map into each gap's engine request: one wire-pose entry per guide at the
gap's own engine sample clock. The contract:

- only frames strictly inside the gap and not keyed are mapped (keys win);
- a guide whose engine sample rounds onto the keyed endpoints (0/span) is
  dropped for the gap instead of poisoning the request;
- the payload is sample-sorted and stable.
"""

from __future__ import annotations

from aimation_actor.adapters.ai import condmdi_adapter as C
from aimation_actor.core.models import JointPose, Quaternion


def _pose() -> dict[str, JointPose]:
    return {"Pelvis": JointPose(rotation=Quaternion.identity())}


def test_guides_map_into_the_gap_clock() -> None:
    payload, anchors = C._guides_for_gap(
        {13: _pose()},
        left=10,
        right=20,
        timeline_fps=24.0,
        motion_fps=20.0,
        keyed={10, 20},
    )
    assert anchors == ({13: _pose()})
    assert [entry["sample"] for entry in payload] == [2]
    assert payload[0]["pose"]["Pelvis"]["quat"] == [1.0, 0.0, 0.0, 0.0]


def test_guides_on_keyed_frames_or_endpoints_are_dropped() -> None:
    payload, anchors = C._guides_for_gap(
        {10: _pose(), 19: _pose(), 20: _pose()},
        left=10,
        right=20,
        timeline_fps=24.0,
        motion_fps=10.0,
        keyed={10, 20},
    )
    # 10/20 are keyed; at 10 fps the gap spans round(10*10/24) = 4 samples
    # and frame 19 rounds onto sample 4 — the right key's own sample.
    assert payload == [] and anchors == {}


def test_guides_on_an_inner_key_are_dropped() -> None:
    payload, anchors = C._guides_for_gap(
        {15: _pose()},
        left=10,
        right=20,
        timeline_fps=24.0,
        motion_fps=24.0,
        keyed={10, 15, 20},
    )
    assert payload == [] and anchors == {}


def test_no_guides_constructs_an_empty_payload() -> None:
    payload, anchors = C._guides_for_gap(
        {},
        left=10,
        right=20,
        timeline_fps=24.0,
        motion_fps=20.0,
        keyed={10, 20},
    )
    assert payload == [] and anchors == {}
