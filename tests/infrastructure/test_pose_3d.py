"""Tests for Pose3DNode (REQ-3)."""

from typing import Any

import pytest

from aimation_actor_core.domain.animation.keypoints import Keypoint, Keypoints2D
from aimation_actor_core.domain.animation.keypoints3d import Keypoints3D
from aimation_actor_core.domain.pipeline.node import ExecutionContext
from aimation_actor_core.domain.pipeline.schema import DataType, NodeCategory
from aimation_actor_core.infrastructure.ai_models.pose_3d import Pose3DNode

# A raw job-store-style serialized frame: plain dicts, exactly as the
# persisted job payload deserializes before hitting the node.
RAW_FRAMES: list[dict[str, Any]] = [
    {
        "frame_index": 0,
        "keypoints": [
            {"label": "nose", "x": 0.5, "y": 0.2, "confidence": 0.95},
            {"label": "left_shoulder", "x": 0.4, "y": 0.35, "confidence": 0.95},
            {"label": "right_shoulder", "x": 0.6, "y": 0.35, "confidence": 0.95},
            {"label": "left_wrist", "x": 0.3, "y": 0.65, "confidence": 0.95},
            {"label": "left_ankle", "x": 0.45, "y": 0.9, "confidence": 0.95},
        ],
    },
    {
        "frame_index": 1,
        "keypoints": [
            {"label": "nose", "x": 0.5, "y": 0.2, "confidence": 0.95},
            {"label": "left_wrist", "x": 0.3, "y": 0.65, "confidence": 0.95},
        ],
    },
]


def _model_frames() -> list[Keypoints2D]:
    """Build the same frames as :data:`RAW_FRAMES` as Keypoints2D models."""
    return [Keypoints2D.model_validate(frame) for frame in RAW_FRAMES]


class TestPose3DNodeSchema:
    """Test Pose3DNode catalog schema."""

    def test_schema_type(self) -> None:
        """Should declare type 'pose-3d'."""
        schema = Pose3DNode.get_schema()
        assert schema.type == "pose-3d"

    def test_schema_category(self) -> None:
        """Should be an AI node."""
        schema = Pose3DNode.get_schema()
        assert schema.category == NodeCategory.AI

    def test_schema_title(self) -> None:
        """Should have title 'Pose 3D'."""
        schema = Pose3DNode.get_schema()
        assert schema.title == "Pose 3D"

    def test_schema_inputs(self) -> None:
        """Should declare keypoints: KEYPOINTS_2D input port."""
        schema = Pose3DNode.get_schema()
        assert len(schema.inputs) == 1
        assert schema.inputs[0].name == "keypoints"
        assert schema.inputs[0].data_type == DataType.KEYPOINTS_2D

    def test_schema_outputs(self) -> None:
        """Should declare keypoints_3d: POSE_3D output port."""
        schema = Pose3DNode.get_schema()
        assert len(schema.outputs) == 1
        assert schema.outputs[0].name == "keypoints_3d"
        assert schema.outputs[0].data_type == DataType.POSE_3D

    def test_schema_params(self) -> None:
        """Should declare model/depth_mode/confidence params with defaults."""
        schema = Pose3DNode.get_schema()
        param_names = [p.name for p in schema.params]
        assert param_names == ["model", "depth_mode", "confidence"]

        model_param = next(p for p in schema.params if p.name == "model")
        assert model_param.data_type == DataType.STRING
        assert not model_param.required
        assert model_param.default == "synthetic"

        depth_param = next(p for p in schema.params if p.name == "depth_mode")
        assert depth_param.data_type == DataType.STRING
        assert not depth_param.required
        assert depth_param.default == "proportional"

        confidence_param = next(p for p in schema.params if p.name == "confidence")
        assert confidence_param.data_type == DataType.NUMBER
        assert not confidence_param.required
        assert confidence_param.default == 0.0


class TestPose3DNodeExecute:
    """Test Pose3DNode execution."""

    @pytest.fixture
    def context(self) -> ExecutionContext:
        """Create an execution context."""
        return ExecutionContext(trace_id="test-trace")

    @pytest.mark.asyncio
    async def test_execute_synthetic_backend(self, context: ExecutionContext) -> None:
        """Should lift via the synthetic backend into list[Keypoints3D]."""
        node = Pose3DNode()
        result = await node.execute(
            inputs={"keypoints": _model_frames()},
            params={"model": "synthetic"},
            context=context,
        )
        lifted = result.values["keypoints_3d"]
        assert isinstance(lifted, list)
        assert len(lifted) == 2
        assert all(isinstance(seq, Keypoints3D) for seq in lifted)
        assert [seq.frame_index for seq in lifted] == [0, 1]
        # Synthetic table: wrist deviates from the camera plane.
        assert lifted[0].keypoints[3].label == "left_wrist"
        assert lifted[0].keypoints[3].z > 0.5

    @pytest.mark.asyncio
    async def test_execute_heuristic_backend(self, context: ExecutionContext) -> None:
        """Should lift via the heuristic backend (z varies with geometry)."""
        node = Pose3DNode()
        result = await node.execute(
            inputs={"keypoints": _model_frames()},
            params={"model": "heuristic"},
            context=context,
        )
        lifted = result.values["keypoints_3d"]
        assert len(lifted) == 2
        z_by_label = {kp.label: kp.z for kp in lifted[0].keypoints}
        # Ankle lower in the frame drifts farther from the camera plane.
        assert z_by_label["left_ankle"] > z_by_label["nose"]

    @pytest.mark.asyncio
    async def test_execute_unknown_model_falls_back_to_synthetic(
        self, context: ExecutionContext
    ) -> None:
        """Should fall back to the synthetic backend for unknown models."""
        node = Pose3DNode()
        result = await node.execute(
            inputs={"keypoints": _model_frames()},
            params={"model": "does-not-exist"},
            context=context,
        )
        lifted = result.values["keypoints_3d"]
        assert len(lifted) == 2
        # Synthetic z-table signature: torso on the plane, wrist deviated.
        z_by_label = {kp.label: kp.z for kp in lifted[0].keypoints}
        assert z_by_label["nose"] == 0.5
        assert z_by_label["left_wrist"] > 0.5

    @pytest.mark.asyncio
    async def test_execute_dict_inputs_coerce_to_keypoints2d(
        self, context: ExecutionContext
    ) -> None:
        """Should coerce raw dict frames (job-store serialized path) into Keypoints2D."""
        node = Pose3DNode()
        result = await node.execute(
            inputs={"keypoints": RAW_FRAMES},
            params={"model": "synthetic"},
            context=context,
        )
        lifted = result.values["keypoints_3d"]
        assert len(lifted) == 2
        assert lifted[0].keypoints[0].label == "nose"
        assert lifted[0].keypoints[0].x == 0.5
        # Frame with a single joint still lifts without error.
        assert len(lifted[1].keypoints) == 2

    @pytest.mark.asyncio
    async def test_execute_mixed_dict_and_model_inputs(self, context: ExecutionContext) -> None:
        """Should accept a mixture of dicts and Keypoints2D models."""
        node = Pose3DNode()
        mixed = [RAW_FRAMES[0], _model_frames()[1]]
        result = await node.execute(
            inputs={"keypoints": mixed},
            params={"model": "synthetic"},
            context=context,
        )
        lifted = result.values["keypoints_3d"]
        assert [seq.frame_index for seq in lifted] == [0, 1]

    @pytest.mark.asyncio
    async def test_uses_asyncio_to_thread(self, context: ExecutionContext) -> None:
        """Should offload lifting to a worker thread via asyncio.to_thread."""
        import asyncio

        node = Pose3DNode()
        original_to_thread = asyncio.to_thread
        calls: list[tuple[Any, tuple[Any, ...]]] = []

        async def mock_to_thread(func: Any, *args: Any) -> Any:  # noqa: ANN401
            calls.append((func, args))
            return await original_to_thread(func, *args)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(asyncio, "to_thread", mock_to_thread)
        try:
            result = await node.execute(
                inputs={"keypoints": _model_frames()},
                params={"model": "synthetic"},
                context=context,
            )
            assert len(calls) > 0
            assert calls[0][0].__name__ == "lift"
            assert len(result.values["keypoints_3d"]) == 2
        finally:
            monkeypatch.undo()


class TestPose3DNodeConfidenceFilter:
    """Test the output-only confidence filter (D5)."""

    @pytest.fixture
    def context(self) -> ExecutionContext:
        """Create an execution context."""
        return ExecutionContext(trace_id="test-trace")

    @pytest.mark.asyncio
    async def test_filter_keeps_only_joints_at_or_above_threshold(
        self, context: ExecutionContext
    ) -> None:
        """Should drop output joints below the threshold, keeping geometry of the rest."""
        node = Pose3DNode()
        frames = [
            Keypoints2D(
                frame_index=0,
                keypoints=[
                    Keypoint(label="nose", x=0.5, y=0.2, confidence=0.95),
                    Keypoint(label="left_wrist", x=0.3, y=0.65, confidence=0.4),
                    Keypoint(label="left_ankle", x=0.45, y=0.9, confidence=0.7),
                ],
            )
        ]
        unfiltered = await node.execute(
            inputs={"keypoints": frames},
            params={"model": "heuristic", "confidence": 0.0},
            context=context,
        )
        filtered = await node.execute(
            inputs={"keypoints": frames},
            params={"model": "heuristic", "confidence": 0.5},
            context=context,
        )
        kept = filtered.values["keypoints_3d"][0]
        labels = [kp.label for kp in kept.keypoints]
        assert labels == ["nose", "left_ankle"]
        # Geometry of the surviving joints is preserved (same x/y/z as unfiltered).
        unfiltered_by_label = {
            kp.label: (kp.x, kp.y, kp.z) for kp in unfiltered.values["keypoints_3d"][0].keypoints
        }
        for kp in kept.keypoints:
            assert (kp.x, kp.y, kp.z) == unfiltered_by_label[kp.label]

    @pytest.mark.asyncio
    async def test_filter_threshold_above_all_drops_to_empty_frames(
        self, context: ExecutionContext
    ) -> None:
        """Should keep frame structure (frame_index) even when every joint is dropped."""
        node = Pose3DNode()
        result = await node.execute(
            inputs={"keypoints": _model_frames()},
            params={"model": "synthetic", "confidence": 0.96},
            context=context,
        )
        lifted = result.values["keypoints_3d"]
        assert len(lifted) == 2
        assert all(seq.keypoints == [] for seq in lifted)
        assert [seq.frame_index for seq in lifted] == [0, 1]


class TestPose3DNodeValidate:
    """Test Pose3DNode parameter validation (mirrors finalized pose-2d).

    ``model``/``depth_mode`` — when provided — must be non-empty strings
    (rejects empty / whitespace-only / non-string). Unknown *values* are
    accepted because ``execute()`` falls back safely (REQ-3).
    """

    @pytest.mark.asyncio
    async def test_validate_empty_params(self) -> None:
        """Should accept empty params (all params are optional)."""
        node = Pose3DNode()
        result = await node.validate({})
        assert result.valid
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_known_and_unknown_model_values(self) -> None:
        """Should accept known and unknown model values (fallback handles them)."""
        node = Pose3DNode()
        for model in ("synthetic", "heuristic", "onnx", "unknown_model"):
            result = await node.validate({"model": model})
            assert result.valid, model
            assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_rejects_empty_model_string(self) -> None:
        """Should reject an empty model string when provided."""
        node = Pose3DNode()
        result = await node.validate({"model": ""})
        assert not result.valid
        assert result.errors

    @pytest.mark.asyncio
    async def test_validate_rejects_whitespace_only_model_string(self) -> None:
        """Should reject a whitespace-only model string when provided."""
        node = Pose3DNode()
        result = await node.validate({"model": "   "})
        assert not result.valid
        assert result.errors

    @pytest.mark.asyncio
    async def test_validate_rejects_non_string_model_value(self) -> None:
        """Should reject a non-string model value when provided."""
        node = Pose3DNode()
        result = await node.validate({"model": None})
        assert not result.valid
        assert result.errors

    @pytest.mark.asyncio
    async def test_validate_known_and_unknown_depth_mode_values(self) -> None:
        """Should accept known and unknown depth_mode values (defaults applied)."""
        node = Pose3DNode()
        for depth_mode in ("proportional", "flat", "some_future_mode"):
            result = await node.validate({"depth_mode": depth_mode})
            assert result.valid, depth_mode
            assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_rejects_empty_depth_mode_string(self) -> None:
        """Should reject an empty depth_mode string when provided."""
        node = Pose3DNode()
        result = await node.validate({"depth_mode": ""})
        assert not result.valid
        assert result.errors

    @pytest.mark.asyncio
    async def test_validate_rejects_whitespace_only_depth_mode_string(self) -> None:
        """Should reject a whitespace-only depth_mode string when provided."""
        node = Pose3DNode()
        result = await node.validate({"depth_mode": "   "})
        assert not result.valid
        assert result.errors

    @pytest.mark.asyncio
    async def test_validate_rejects_non_string_depth_mode_value(self) -> None:
        """Should reject a non-string depth_mode value when provided."""
        node = Pose3DNode()
        result = await node.validate({"depth_mode": None})
        assert not result.valid
        assert result.errors

    @pytest.mark.asyncio
    async def test_validate_accepts_confidence_number(self) -> None:
        """Should accept a numeric confidence value."""
        node = Pose3DNode()
        result = await node.validate({"confidence": 0.5})
        assert result.valid
        assert result.errors == []
