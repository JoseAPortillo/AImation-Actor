"""Model catalog registry (``models/manifest.json``).

Reads, validates, and inspects the local model catalog: the manifest shape is
frozen by ``schema_version: 1`` and each entry is validated by
:class:`ModelSpec` (pydantic, extra fields forbidden). Belongs to the
``infrastructure`` layer (SDD §2.2): stdlib + pydantic only, no API imports.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError


class ModelSpec(BaseModel):
    """One catalog entry describing a downloadable model artifact.

    Attributes:
        name: Unique catalog name, e.g. ``"rtmpose-light"``.
        kind: Backend category, e.g. ``"pose-2d"`` / ``"pose-3d"``.
        version: Model version tag; empty when not pinned.
        file: File name under the models root, e.g. ``"rtmpose.onnx"``.
        url: Download URL; empty when no source is recorded yet.
        sha256: Expected SHA-256 hex digest; empty means unverified (TOFU).
        license: SPDX license identifier of the artifact.
        description: Human-readable notes (origin, compliance pointers).
        archive_inner: Optional relative path inside a zip archive to extract.
            When set, the provisioner downloads the zip, extracts this member,
            and verifies/installs the extracted file instead of the raw archive.
            The sha256 refers to the extracted file, not the zip container.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: str
    version: str = ""
    file: str
    url: str = ""
    sha256: str = ""
    license: str
    description: str = ""
    archive_inner: str | None = None


class ModelManifestError(ValueError):
    """Raised when the manifest is missing, malformed, or unsupported."""


class ModelNotFoundError(ValueError):
    """Raised when a requested model name is absent from the manifest.

    Attributes:
        name: The requested model name.
    """

    def __init__(self, name: str) -> None:
        super().__init__(f"model {name!r} not found in manifest")
        self.name = name


def hash_file(path: Path) -> str:
    """Return the lowercase hex SHA-256 digest of the file at ``path``."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ModelRegistry:
    """File-system backed model catalog rooted at ``root/manifest.json``.

    Attributes:
        root: Directory holding ``manifest.json`` and the model binaries.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path("models")

    @property
    def manifest_path(self) -> Path:
        """Path of the manifest file (``root / "manifest.json"``)."""
        return self.root / "manifest.json"

    def ensure_root(self) -> None:
        """Create the models root directory (parents included)."""
        self.root.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[ModelSpec]:
        """Read and validate the manifest; return the catalog entries.

        Raises:
            ModelManifestError: If the manifest is missing, is not a JSON
                object, has an unsupported ``schema_version``, lacks a
                ``models`` list, or contains an invalid entry.
        """
        manifest = self.manifest_path
        if not manifest.exists():
            raise ModelManifestError(f"missing manifest at {manifest}")
        try:
            payload: object = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelManifestError(f"cannot read manifest at {manifest}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ModelManifestError(f"manifest at {manifest} must be a JSON object")
        if payload.get("schema_version") != 1:
            raise ModelManifestError(
                f"unsupported manifest schema_version "
                f"{payload.get('schema_version')!r} (expected 1)"
            )
        raw_models = payload.get("models")
        if not isinstance(raw_models, list):
            raise ModelManifestError(f"manifest at {manifest} must contain a 'models' list")
        try:
            return [ModelSpec.model_validate(entry) for entry in raw_models]
        except ValidationError as exc:
            raise ModelManifestError(f"invalid model entry in {manifest}: {exc}") from exc

    def get(self, name: str) -> ModelSpec:
        """Return the catalog entry for ``name``.

        Raises:
            ModelNotFoundError: If no entry matches ``name``.
        """
        for spec in self.load():
            if spec.name == name:
                return spec
        raise ModelNotFoundError(name)

    def status(self, spec: ModelSpec) -> str:
        """Classify the on-disk state of ``spec``.

        Returns:
            ``"missing"`` when the model file is absent; ``"corrupt"`` when its
            hash does not match the recorded ``sha256``; ``"installed-unverified"``
            when no hash is recorded (TOFU); ``"installed"`` otherwise.
        """
        path = self.installed_path(spec)
        if not path.exists():
            return "missing"
        if spec.sha256 and hash_file(path) != spec.sha256:
            return "corrupt"
        if not spec.sha256:
            return "installed-unverified"
        return "installed"

    def installed_path(self, spec: ModelSpec) -> Path:
        """Resolve the on-disk path of ``spec`` under the models root."""
        return self.root / spec.file