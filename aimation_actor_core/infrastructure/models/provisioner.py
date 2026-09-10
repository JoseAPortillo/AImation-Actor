"""Model provisioning: license gate → verified download → atomic install.

Implements the SpecSecDev model-integrity policy (docs/model-licenses.md):
downloaded bytes are NEVER executed — they are only hashed and moved into
place with ``os.replace`` (atomic within the same filesystem). A recorded
``sha256`` is verified before install; entries without one are accepted only
through an explicit ``--trust-on-first-use`` (TOFU) opt-in, which records the
observed hash back into ``manifest.json``.

Stdlib only (``urllib``): no httpx/requests dependency is added for downloads.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from pathlib import Path

from aimation_actor_core.infrastructure.models.registry import (
    ModelRegistry,
    ModelSpec,
    hash_file,
)


class ModelProvisionError(ValueError):
    """Model download, verification, or installation failed."""


def _default_opener(url: str) -> bytes:
    """Download ``url`` with a 30 s timeout and return the raw bytes."""
    with urllib.request.urlopen(url, timeout=30) as response:
        data: bytes = response.read()
    return data


def _cleanup(path: Path) -> None:
    """Best-effort removal of a partial download artifact."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


class ModelProvisioner:
    """Installs manifest entries into the registry root.

    The HTTP layer is injectable (``opener: Callable[[str], bytes]``) so tests
    can serve canned payloads without any network access.

    Attributes:
        registry: The catalog/root the provisioner reads from and installs into.
    """

    def __init__(
        self,
        registry: ModelRegistry,
        opener: Callable[[str], bytes] | None = None,
    ) -> None:
        self.registry = registry
        self._opener: Callable[[str], bytes] = opener or _default_opener

    def install(
        self,
        spec: ModelSpec,
        *,
        accept_license: str | None,
        trust_on_first_use: bool = False,
    ) -> Path:
        """License-gated, hash-verified download and atomic install of ``spec``.

        Order of gates (no network is touched before every gate passes):

        1. ``accept_license`` must equal ``spec.license`` exactly.
        2. ``spec.url`` must be non-empty.
        3. ``spec.sha256`` must be present, or ``trust_on_first_use`` (TOFU).

        The payload is streamed to a ``.part`` file inside the models root so
        the final ``os.replace`` is atomic on the same filesystem. With a
        recorded hash, the digest is verified before naming; a mismatch leaves
        no residue. Under TOFU, the observed hash is written back into
        ``manifest.json`` (pretty JSON, catalog preserved).

        Args:
            spec: The manifest entry to install.
            accept_license: SPDX identifier the user explicitly accepts; must
                match ``spec.license``.
            trust_on_first_use: Accept an entry with no recorded ``sha256`` and
                record the observed digest in the manifest.

        Returns:
            The installed file path.

        Raises:
            ModelProvisionError: For any gate failure, download failure,
                hash mismatch, or install failure.
        """
        if accept_license != spec.license:
            raise ModelProvisionError(
                f"license not accepted: expected {spec.license} "
                f"(use --accept-license {spec.license})"
            )
        if not spec.url:
            raise ModelProvisionError(f"no download URL recorded for {spec.name}")
        if not spec.sha256 and not trust_on_first_use:
            raise ModelProvisionError(
                f"unverified manifest entry {spec.name!r}: no sha256 recorded; "
                "use --trust-on-first-use to accept the download on first use"
            )

        self.registry.ensure_root()
        tmp = self.registry.root / f"{spec.file}.part"
        target = self.registry.installed_path(spec)

        try:
            data = self._opener(spec.url)
        except OSError as exc:
            _cleanup(tmp)
            raise ModelProvisionError(f"failed to download {spec.url}: {exc}") from exc

        try:
            tmp.write_bytes(data)
        except OSError as exc:
            _cleanup(tmp)
            raise ModelProvisionError(f"failed to write {tmp}: {exc}") from exc

        digest = hash_file(tmp)
        if spec.sha256:
            if digest != spec.sha256:
                _cleanup(tmp)
                raise ModelProvisionError(
                    f"model hash mismatch for {spec.name}: expected {spec.sha256}, got {digest}"
                )
        else:
            self._record_sha256(spec, digest)

        try:
            os.replace(tmp, target)
        except OSError as exc:
            _cleanup(tmp)
            raise ModelProvisionError(f"failed to install {target}: {exc}") from exc
        return target

    def verify_installed(self, spec: ModelSpec) -> bool:
        """Return ``True`` when ``spec`` is on disk and not known-corrupt.

        Delegates to :meth:`ModelRegistry.status`; ``"installed-unverified"``
        counts as installed (a recorded hash would upgrade it to
        ``"installed"`` on a later verify).
        """
        return self.registry.status(spec) in {"installed", "installed-unverified"}

    def _record_sha256(self, spec: ModelSpec, digest: str) -> None:
        """TOFU: persist the observed digest into the manifest entry."""
        manifest = self.registry.manifest_path
        if not manifest.exists():
            raise ModelProvisionError(f"cannot record TOFU hash: missing manifest at {manifest}")
        try:
            payload: object = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelProvisionError(f"cannot read manifest for TOFU update: {exc}") from exc
        if not isinstance(payload, dict):
            raise ModelProvisionError("manifest is malformed: expected a JSON object")
        raw_models = payload.get("models")
        if not isinstance(raw_models, list):
            raise ModelProvisionError("manifest is malformed: expected a 'models' list")
        updated = False
        for entry in raw_models:
            if isinstance(entry, dict) and entry.get("name") == spec.name:
                entry["sha256"] = digest
                updated = True
        if not updated:
            raise ModelProvisionError(
                f"model {spec.name!r} not found in manifest for TOFU update"
            )
        try:
            manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            raise ModelProvisionError(f"failed to write updated manifest: {exc}") from exc