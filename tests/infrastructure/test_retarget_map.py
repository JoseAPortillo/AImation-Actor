"""Tests for RetargetMapNode (REQ retargeting §14 / tasks 3.1-3.2).

Mirrors the ``TemporalCleanupNode`` test pattern: catalog schema assertions
(RIGGING category, ``motion: NEUTRAL_ANIMATION`` in/out, five params),
``execute`` returns a retargeted ``NeutralMotion`` (with dict coercion for the
job-store serialized path and ``asyncio.to_thread`` offload), and ``validate``
rejects a nonexistent preset. The shipped ``media/presets/identity.yaml`` is
exercised end-to-end as the runtime harness (identity preset == passthrough).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aimation_actor_core.domain.animation.entities import Frame, Pose, Transform3D
from aimation_actor_core.domain.animation.neutral_motion import NeutralMotion
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON
from aimation_actor_core.domain.pipeline.node import ExecutionContext
from aimation_actor_core.domain.pipeline.schema import DataType, NodeCategory
from aimation_actor_core.infrastructure.ai_models.retarget_map import RetargetMapNode

#: A full-cover identity preset: every neutral bone maps to itself with
#: identity rotation/scale and no axis correction (plan §14.2 names).
IDENTITY_PRESET = """\
mapping:
  Root: Root
  Hips: Hips
  Spine: Spine
  Chest: Chest
  Neck: Neck
  Head: Head
  LeftShoulder: LeftShoulder
  LeftArm: LeftArm
  LeftForeArm: LeftForeArm
  LeftHand: LeftHand
  RightShoulder: RightShoulder
  RightArm: RightArm
  RightForeArm: RightForeArm
  RightHand: RightHand
  LeftUpLeg: LeftUpLeg
  LeftLeg: LeftLeg
  LeftFoot: LeftFoot
  LeftToeBase: LeftToeBase
  RightUpLeg: RightUpLeg
  RightLeg: RightLeg
  RightFoot: RightFoot
  RightToeBase: RightToeBase
use_root_translation: true
foot_ik: false
scale_source_height: false
preserve_keyframes: false
"""

#: A nontrivial preset: doubles LeftUpLeg's per-bone scale.
SCALE_PRESET = """\
mapping:
  LeftUpLeg:
    target_name: target_upLeg
    scale: [2, 2, 2]
use_root_translation: true
foot_ik: false
scale_source_height: false
preserve_keyframes: false
"""


def _motion(n_frames: int = 2) -> NeutralMotion:
    """Build a small valid NeutralMotion over the default skeleton."""
    frames = [
        Frame(
            frame=i + 1,
            time=(i + 1) / 24.0,
            pose=Pose(
                transforms={
                    "Root": Transform3D(translation=(0.0, 0.0, 0.0)),
                    "Hips": Transform3D(translation=(0.0, 95.0, 0.0)),
                    "LeftUpLeg": Transform3D(translation=(0.0, -8.0, 0.0)),
                    "LeftFoot": Transform3D(translation=(0.0, -42.0, 0.0)),
                    "RightFoot": Transform3D(translation=(0.0, -42.0, 0.0)),
                }
            ),
        )
        for i in range(n_frames)
    ]
    motion = NeutralMotion(skeleton=DEFAULT_NEUTRAL_SKELETON, frames=frames)
    motion.validate_invariants()
    return motion


def _write_preset(
    tmp_path: Path, name: str = "identity.yaml", body: str = IDENTITY_PRESET
) -> Path:
    """Write a preset under ``tmp_path/presets/`` and return the preset root."""
    preset_root = tmp_path / "presets"
    preset_root.mkdir(exist_ok=True)
    (preset_root / name).write_text(body, encoding="utf-8")
    return preset_root


class TestRetargetMapNodeSchema:
    """Test RetargetMapNode catalog schema."""

    def test_schema_type(self) -> None:
        """Should declare type 'retarget-map'."""
        schema = RetargetMapNode.get_schema()
        assert schema.type == "retarget-map"

    def test_schema_category(self) -> None:
        """Should be a RIGGING node."""
        schema = RetargetMapNode.get_schema()
        assert schema.category == NodeCategory.RIGGING

    def test_schema_inputs(self) -> None:
        """Should declare motion: NEUTRAL_ANIMATION input port."""
        schema = RetargetMapNode.get_schema()
        assert len(schema.inputs) == 1
        assert schema.inputs[0].name == "motion"
        assert schema.inputs[0].data_type == DataType.NEUTRAL_ANIMATION

    def test_schema_outputs(self) -> None:
        """Should declare motion: NEUTRAL_ANIMATION output port."""
        schema = RetargetMapNode.get_schema()
        assert len(schema.outputs) == 1
        assert schema.outputs[0].name == "motion"
        assert schema.outputs[0].data_type == DataType.NEUTRAL_ANIMATION

    def test_schema_params(self) -> None:
        """Should declare the five retarget params (preset + four bools)."""
        schema = RetargetMapNode.get_schema()
        param_names = [p.name for p in schema.params]
        assert param_names == [
            "mapping_preset",
            "use_root_translation",
            "foot_ik",
            "scale_source_height",
            "preserve_keyframes",
        ]
        preset = schema.params[0]
        assert preset.data_type == DataType.STRING
        assert preset.required is True
        # The four bools are optional with no default so an unset param lets
        # the preset document's value win (node > preset > default).
        for p in schema.params[1:]:
            assert p.data_type == DataType.BOOLEAN
            assert p.required is False
            assert p.default is None


class TestRetargetMapNodeExecute:
    """Test RetargetMapNode execution."""

    @pytest.fixture
    def context(self) -> ExecutionContext:
        """Create an execution context."""
        return ExecutionContext(trace_id="test-trace")

    @pytest.mark.asyncio
    async def test_execute_applies_preset_scale(
        self, tmp_path: Path, context: ExecutionContext
    ) -> None:
        """Should return a retargeted NeutralMotion with the preset's scale."""
        preset_root = _write_preset(tmp_path, "scale.yaml", SCALE_PRESET)
        node = RetargetMapNode(preset_root=preset_root)
        result = await node.execute(
            inputs={"motion": _motion()},
            params={"mapping_preset": "scale.yaml"},
            context=context,
        )
        motion = result.values["motion"]
        assert isinstance(motion, NeutralMotion)
        motion.validate_invariants()
        scaled = motion.frames[0].pose.transforms["LeftUpLeg"]
        assert scaled.scale == (2.0, 2.0, 2.0)

    @pytest.mark.asyncio
    async def test_execute_dict_inputs_coerce_to_neutral_motion(
        self, tmp_path: Path, context: ExecutionContext
    ) -> None:
        """Should coerce raw dict motion (job-store serialized path)."""
        preset_root = _write_preset(tmp_path, "identity.yaml")
        node = RetargetMapNode(preset_root=preset_root)
        raw = _motion().model_dump()
        result = await node.execute(
            inputs={"motion": raw},
            params={"mapping_preset": "identity.yaml"},
            context=context,
        )
        motion = result.values["motion"]
        assert isinstance(motion, NeutralMotion)
        assert [f.frame for f in motion.frames] == [1, 2]

    @pytest.mark.asyncio
    async def test_execute_deterministic(
        self, tmp_path: Path, context: ExecutionContext
    ) -> None:
        """Should produce byte-identical output for identical input+params."""
        preset_root = _write_preset(tmp_path, "scale.yaml", SCALE_PRESET)
        node = RetargetMapNode(preset_root=preset_root)
        params = {"mapping_preset": "scale.yaml"}
        first = await node.execute(inputs={"motion": _motion()}, params=params, context=context)
        second = await node.execute(inputs={"motion": _motion()}, params=params, context=context)
        first_doc = first.values["motion"].model_dump_json()
        second_doc = second.values["motion"].model_dump_json()
        assert first_doc == second_doc

    @pytest.mark.asyncio
    async def test_execute_shipped_identity_preset_is_passthrough(
        self, context: ExecutionContext
    ) -> None:
        """Should load media/presets/identity.yaml (default root) as identity."""
        node = RetargetMapNode()
        motion = _motion()
        result = await node.execute(
            inputs={"motion": motion},
            params={"mapping_preset": "identity.yaml"},
            context=context,
        )
        out = result.values["motion"]
        assert isinstance(out, NeutralMotion)
        assert out.model_dump() == motion.model_dump()

    @pytest.mark.asyncio
    async def test_uses_asyncio_to_thread(
        self, tmp_path: Path, context: ExecutionContext
    ) -> None:
        """Should offload the retarget to a worker thread via asyncio.to_thread."""
        import asyncio

        preset_root = _write_preset(tmp_path, "scale.yaml", SCALE_PRESET)
        node = RetargetMapNode(preset_root=preset_root)
        original_to_thread = asyncio.to_thread
        calls: list[tuple[Any, tuple[Any, ...]]] = []

        async def mock_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            calls.append((func, args))
            return await original_to_thread(func, *args, **kwargs)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(asyncio, "to_thread", mock_to_thread)
        try:
            result = await node.execute(
                inputs={"motion": _motion()},
                params={"mapping_preset": "scale.yaml"},
                context=context,
            )
            assert len(calls) > 0
            assert isinstance(result.values["motion"], NeutralMotion)
        finally:
            monkeypatch.undo()


class TestRetargetMapNodeValidate:
    """Test RetargetMapNode parameter validation."""

    @pytest.mark.asyncio
    async def test_validate_rejects_missing_preset_param(self) -> None:
        """Should reject an absent mapping_preset (required param)."""
        node = RetargetMapNode()
        result = await node.validate({})
        assert not result.valid
        assert any("mapping_preset" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_validate_rejects_nonexistent_preset(self, tmp_path: Path) -> None:
        """Should reject a mapping_preset that does not exist in the root."""
        preset_root = _write_preset(tmp_path, "identity.yaml")
        node = RetargetMapNode(preset_root=preset_root)
        result = await node.validate({"mapping_preset": "nope.yaml"})
        assert not result.valid
        assert result.errors

    @pytest.mark.asyncio
    async def test_validate_rejects_traversal_preset(self, tmp_path: Path) -> None:
        """Should reject a preset name escaping the allowlisted root."""
        preset_root = _write_preset(tmp_path, "identity.yaml")
        node = RetargetMapNode(preset_root=preset_root)
        result = await node.validate({"mapping_preset": "../secret.yaml"})
        assert not result.valid
        assert result.errors

    @pytest.mark.asyncio
    async def test_validate_accepts_valid_preset(self, tmp_path: Path) -> None:
        """Should accept a resolvable, well-formed preset."""
        preset_root = _write_preset(tmp_path, "identity.yaml")
        node = RetargetMapNode(preset_root=preset_root)
        result = await node.validate({"mapping_preset": "identity.yaml"})
        assert result.valid
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_validate_rejects_non_boolean_param(self, tmp_path: Path) -> None:
        """Should reject a non-boolean value for a boolean param."""
        preset_root = _write_preset(tmp_path, "identity.yaml")
        node = RetargetMapNode(preset_root=preset_root)
        result = await node.validate({"mapping_preset": "identity.yaml", "foot_ik": "yes"})
        assert not result.valid
        assert any("foot_ik" in e for e in result.errors)