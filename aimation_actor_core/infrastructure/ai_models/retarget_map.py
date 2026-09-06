"""Retarget map node: ``NEUTRAL_ANIMATION → NEUTRAL_ANIMATION`` (REQ §14).

A deterministic :class:`RetargetMapNode` (category ``RIGGING``) that consumes a
:class:`NeutralMotion` and maps it onto a target rig via a user YAML/JSON
``RetargetMap`` preset, emitting a retargeted ``NeutralMotion``. No new
``DataType`` (decision B) — the node reuses ``NEUTRAL_ANIMATION`` in/out.

Following the ``TemporalCleanupNode`` adapter pattern, this node owns no math
of its own — it adapts the :class:`INode` contract to :func:`retarget_motion`
(design D7): dict coercion via :func:`migrate_neutral_motion` for the
serialized job-store path, ``asyncio.to_thread`` offload, and param
validation. All math lives in :mod:`aimation_actor_core.domain.retargeting`.

Security (SDD §4.2 new row, spec "Safe preset ingestion"): presets load only
from an allowlisted root (``media/presets/`` by default) — absolute paths,
``..`` traversal and symlink escapes are rejected before any read; files are
capped at :data:`MAX_PRESET_BYTES` *before* parsing (billion-laughs defense);
YAML is parsed with :func:`yaml.safe_load` and JSON with :func:`json.load`;
unknown fields are rejected by the ``extra="forbid"`` ``RetargetMap`` model.
``eval``/``exec``/``yaml.load|full_load|unsafe_load`` are never used.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from aimation_actor_core.domain.animation.neutral_motion import (
    NeutralMotion,
    migrate_neutral_motion,
)
from aimation_actor_core.domain.animation.skeleton_presets import DEFAULT_NEUTRAL_SKELETON
from aimation_actor_core.domain.pipeline.node import (
    ExecutionContext,
    INode,
    NodeOutput,
    ValidationResult,
)
from aimation_actor_core.domain.pipeline.schema import (
    DataType,
    NodeCategory,
    NodeSchema,
    PortSpec,
)
from aimation_actor_core.domain.retargeting import RetargetMap, retarget_motion
from aimation_actor_core.shared.errors import AImationError

#: Maximum preset size in bytes; enforced BEFORE parsing (billion-laughs
#: defense, spec "Safe preset ingestion").
MAX_PRESET_BYTES = 262_144

#: Preset extensions allowed by the loader; anything else is rejected.
_ALLOWED_EXTENSIONS = frozenset({".yaml", ".yml", ".json"})

#: Boolean override params; a provided node param wins over the preset
#: document (precedence: node > preset > model default).
_BOOL_PARAMS = (
    "use_root_translation",
    "foot_ik",
    "scale_source_height",
    "preserve_keyframes",
)


class PresetError(AImationError):
    """Raised when a preset is disallowed, unreadable, or malformed."""

    code = "preset_error"


class RetargetMapNode(INode):
    """Maps a neutral motion onto a target rig from an allowlisted preset.

    Stateless at the contract level; every per-run choice (preset name plus
    boolean overrides) lives in the ``params`` passed to :meth:`execute`. The
    blocking resolve/parse/retarget chain runs off the asyncio loop via
    :func:`asyncio.to_thread`.
    """

    def __init__(self, preset_root: Path = Path("media/presets")) -> None:
        self._preset_root = preset_root

    @staticmethod
    def get_schema() -> NodeSchema:
        """Return the node schema."""
        return NodeSchema(
            type="retarget-map",
            category=NodeCategory.RIGGING,
            title="Retarget Map",
            description=(
                "Map a neutral motion onto a target rig from a YAML/JSON preset"
            ),
            inputs=[PortSpec(name="motion", data_type=DataType.NEUTRAL_ANIMATION)],
            outputs=[PortSpec(name="motion", data_type=DataType.NEUTRAL_ANIMATION)],
            params=[
                PortSpec(
                    name="mapping_preset",
                    data_type=DataType.STRING,
                    required=True,
                    description="Preset file name under the allowlisted preset root",
                ),
                PortSpec(
                    name="use_root_translation",
                    data_type=DataType.BOOLEAN,
                    required=False,
                    description="Override the preset use_root_translation (node wins)",
                ),
                PortSpec(
                    name="foot_ik",
                    data_type=DataType.BOOLEAN,
                    required=False,
                    description="Override the preset foot_ik (node wins)",
                ),
                PortSpec(
                    name="scale_source_height",
                    data_type=DataType.BOOLEAN,
                    required=False,
                    description="Override the preset scale_source_height (node wins)",
                ),
                PortSpec(
                    name="preserve_keyframes",
                    data_type=DataType.BOOLEAN,
                    required=False,
                    description="Override the preset preserve_keyframes (node wins)",
                ),
            ],
        )

    def _resolve_preset_path(self, preset_name: str) -> Path:
        """Resolve and validate ``preset_name`` against the preset-root allowlist.

        Mirrors ``FrameExtractorNode._resolve_video_path`` (SDD §4.3 path
        allowlist): rejects non-strings, absolute paths, traversal escapes,
        symlink escapes (via :meth:`pathlib.Path.resolve` +
        :meth:`~pathlib.PurePath.is_relative_to`), disallowed extensions, and
        missing/non-file targets — before any read or parse.
        """
        if not isinstance(preset_name, str) or not preset_name.strip():
            raise PresetError("param mapping_preset must be a non-empty path string")

        candidate = Path(preset_name)
        if candidate.is_absolute():
            raise PresetError("param mapping_preset must be a relative path under the preset root")
        if candidate.suffix.lower() not in _ALLOWED_EXTENSIONS:
            raise PresetError(
                "param mapping_preset must end in .yaml, .yml or .json "
                f"(got {candidate.suffix!r})"
            )

        root = self._preset_root.resolve()
        resolved = (self._preset_root / candidate).resolve()
        try:
            inside = resolved.is_relative_to(root)
        except ValueError:  # pragma: no cover - defensive for non-matching drives
            inside = False
        if not inside:
            raise PresetError("param mapping_preset escapes the allowlisted preset root")
        if not resolved.exists():
            raise PresetError("param mapping_preset does not exist under the preset root")
        if not resolved.is_file():
            raise PresetError("param mapping_preset is not a file under the preset root")
        return resolved

    @staticmethod
    def _read_preset(resolved: Path) -> dict[str, Any]:
        """Read and parse a resolved preset file (runs off the loop).

        Enforces the size cap before parsing (billion-laughs defense), then
        parses JSON with :func:`json.load` and YAML with :func:`yaml.safe_load`
        only. Returns a plain ``dict`` for :class:`RetargetMap` validation.
        """
        size = resolved.stat().st_size
        if size > MAX_PRESET_BYTES:
            raise PresetError(
                f"preset exceeds the {MAX_PRESET_BYTES}-byte size cap"
            )
        text = resolved.read_text(encoding="utf-8")
        if resolved.suffix.lower() == ".json":
            data = json.loads(text)
        else:
            data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise PresetError("preset root must be a YAML/JSON mapping")
        return data

    @staticmethod
    def _build_retarget_map(data: dict[str, Any], params: dict[str, Any]) -> RetargetMap:
        """Validate the parsed preset and apply node-param overrides.

        Precedence (design): **node > preset > model default**. A node param
        present with a non-``None`` value overrides the preset document; an
        absent/``None`` param lets the preset (or its model default) win.
        """
        retarget_map = RetargetMap.model_validate(data)
        retarget_map.validate_against(DEFAULT_NEUTRAL_SKELETON)
        overrides = {
            key: params[key]
            for key in _BOOL_PARAMS
            if key in params and params[key] is not None
        }
        if overrides:
            retarget_map = retarget_map.model_copy(update=overrides)
        return retarget_map

    def _retarget_blocking(
        self, motion: NeutralMotion, preset_name: str, params: dict[str, Any]
    ) -> NeutralMotion:
        """Resolve, parse, validate, and apply a preset (runs off the loop)."""
        resolved = self._resolve_preset_path(preset_name)
        data = self._read_preset(resolved)
        retarget_map = self._build_retarget_map(data, params)
        return retarget_motion(motion, retarget_map)

    async def execute(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> NodeOutput:
        """Execute the retarget.

        Args:
            inputs: Input ``motion`` (a :class:`NeutralMotion` or raw serialized
                dict from the job-store path; migrated on read per ADR-001).
            params: ``mapping_preset`` (required) plus optional boolean
                overrides that win over the preset document.
            context: Execution context.

        Returns:
            NodeOutput with the retargeted :class:`NeutralMotion` under
            ``motion``.
        """
        del context  # unused; kept for the INode contract
        motion = migrate_neutral_motion(inputs["motion"])
        preset_name = params.get("mapping_preset")
        if not isinstance(preset_name, str) or not preset_name.strip():
            raise PresetError("param mapping_preset must be a non-empty path string")

        # Resolve/parse/validate/retarget off the event loop (design D7).
        result = await asyncio.to_thread(
            self._retarget_blocking, motion, preset_name, params
        )
        return NodeOutput(values={"motion": result})

    async def validate(self, params: dict[str, Any]) -> ValidationResult:
        """Validate parameters before execution (defense-in-depth).

        ``mapping_preset`` must be a non-empty string resolving to an existing
        file inside the allowlisted root whose content parses and validates as
        a :class:`RetargetMap` against the neutral skeleton; the four boolean
        overrides must be booleans when provided. The executor does not call
        :meth:`validate` — it is kept for the contract and direct callers.
        """
        errors: list[str] = []
        preset_name = params.get("mapping_preset")
        if not isinstance(preset_name, str) or not preset_name.strip():
            errors.append("missing required param: mapping_preset")
        for key in _BOOL_PARAMS:
            if key in params and params[key] is not None and not isinstance(params[key], bool):
                errors.append(f"{key} must be a boolean")
        if not errors and isinstance(preset_name, str):
            try:
                await asyncio.to_thread(self._validate_preset_blocking, preset_name)
            except (PresetError, yaml.YAMLError, ValidationError, ValueError, OSError) as exc:
                errors.append(f"preset invalid: {exc}")
        return ValidationResult(valid=not errors, errors=errors)

    def _validate_preset_blocking(self, preset_name: str) -> None:
        """Resolve, parse, and model-validate a preset (runs off the loop)."""
        resolved = self._resolve_preset_path(preset_name)
        data = self._read_preset(resolved)
        retarget_map = RetargetMap.model_validate(data)
        retarget_map.validate_against(DEFAULT_NEUTRAL_SKELETON)