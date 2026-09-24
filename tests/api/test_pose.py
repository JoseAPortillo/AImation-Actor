"""API tests for the pose router: bulk 2D→3D lifting (REQ-2)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aimation_actor_core.main import create_app
from aimation_actor_core.shared.config import Settings

TEST_TOKEN = "test-instance-token-0123456789abcdef"


def _client(tmp_path: Path | None = None) -> TestClient:
    media_root = tmp_path / "media" if tmp_path else Path("media")
    if tmp_path:
        media_root.mkdir(exist_ok=True)
    app = create_app(settings=Settings(session_token=TEST_TOKEN, media_root=media_root))
    return TestClient(app)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


def _frames() -> list[list[dict[str, object]]]:
    """Two COCO frames with distinct labels, geometry and depth priors."""
    return [
        [
            {"label": "nose", "x": 0.5, "y": 0.25, "confidence": 0.98},
            {"label": "left_shoulder", "x": 0.45, "y": 0.4, "confidence": 0.95},
            {"label": "right_shoulder", "x": 0.55, "y": 0.4, "confidence": 0.95},
        ],
        [
            {"label": "nose", "x": 0.5, "y": 0.3, "confidence": 0.97},
            {"label": "left_wrist", "x": 0.3, "y": 0.5, "confidence": 0.9},
        ],
    ]


class TestLiftPose3D:
    """POST /pose/lift — bulk deterministic 2D→3D lift."""

    def test_lift_preserves_frame_shape_and_label_order(self) -> None:
        c = _client()
        source = _frames()
        r = c.post("/pose/lift", json={"frames": source}, headers=_auth())
        assert r.status_code == 200
        lifted = r.json()["frames"]
        assert len(lifted) == len(source)
        for lifted_frame, source_frame in zip(lifted, source, strict=True):
            assert len(lifted_frame) == len(source_frame)
            assert [kp["label"] for kp in lifted_frame] == [
                kp["label"] for kp in source_frame
            ]

    def test_lift_z_is_float_within_normalized_range(self) -> None:
        c = _client()
        r = c.post("/pose/lift", json={"frames": _frames()}, headers=_auth())
        assert r.status_code == 200
        z_values = [kp["z"] for frame in r.json()["frames"] for kp in frame]
        assert z_values
        for z in z_values:
            assert isinstance(z, float)
            assert 0.0 <= z <= 1.0

    def test_lift_passes_geometry_and_confidence_through(self) -> None:
        c = _client()
        source = _frames()
        r = c.post("/pose/lift", json={"frames": source}, headers=_auth())
        assert r.status_code == 200
        for lifted_frame, source_frame in zip(r.json()["frames"], source, strict=True):
            for lifted_kp, source_kp in zip(lifted_frame, source_frame, strict=True):
                assert lifted_kp["x"] == source_kp["x"]
                assert lifted_kp["y"] == source_kp["y"]
                assert lifted_kp["confidence"] == source_kp["confidence"]

    def test_lift_is_deterministic(self) -> None:
        c = _client()
        payload = {"frames": _frames()}
        first = c.post("/pose/lift", json=payload, headers=_auth())
        second = c.post("/pose/lift", json=payload, headers=_auth())
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()

    def test_lift_depth_varies_with_frame_geometry(self) -> None:
        c = _client()
        r = c.post("/pose/lift", json={"frames": _frames()}, headers=_auth())
        assert r.status_code == 200
        nose_z = [
            kp["z"]
            for frame in r.json()["frames"]
            for kp in frame
            if kp["label"] == "nose"
        ]
        assert len(nose_z) == 2
        assert nose_z[0] != nose_z[1]

    def test_lift_empty_frames_returns_empty_list(self) -> None:
        c = _client()
        r = c.post("/pose/lift", json={"frames": []}, headers=_auth())
        assert r.status_code == 200
        assert r.json() == {"frames": []}

    def test_lift_empty_inner_frame_returns_empty_inner_list(self) -> None:
        c = _client()
        frames = _frames()
        frames.insert(1, [])
        r = c.post("/pose/lift", json={"frames": frames}, headers=_auth())
        assert r.status_code == 200
        lifted = r.json()["frames"]
        assert len(lifted) == 3
        assert lifted[1] == []
        assert [kp["label"] for kp in lifted[0]] == [
            "nose",
            "left_shoulder",
            "right_shoulder",
        ]
        assert [kp["label"] for kp in lifted[2]] == ["nose", "left_wrist"]
