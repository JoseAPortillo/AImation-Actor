"""Shared media-root path allowlist (SDD §4.3, decision D3).

A single security boundary for every media file access: the frame-serving
endpoint, video uploads, and ``FrameExtractorNode``. Absolute and traversal
paths are rejected before any file is opened; only paths that fully resolve
inside ``media_root`` are ever returned.
"""

from __future__ import annotations

from pathlib import Path

from aimation_actor_core.shared.errors import AImationError


class MediaPathError(AImationError):
    """Raised when a media reference is disallowed by the media-root allowlist."""

    code = "media_path_disallowed"


def resolve_media_path(
    media_root: Path,
    relative_path: str,
    *,
    must_exist: bool = True,
) -> Path:
    """Resolve ``relative_path`` against the ``media_root`` allowlist.

    Rejects non-string/blank references, absolute or drive-qualified paths,
    and any reference that resolves outside ``media_root``. When
    ``must_exist`` is true the resolved path must also be an existing regular
    file. No file is ever opened; only path normalization runs before the
    allowlist checks, and metadata checks only run after they pass.

    Args:
        media_root: Allowlisted base directory for media files.
        relative_path: Media reference relative to ``media_root``.
        must_exist: Require the resolved path to be an existing file.

    Returns:
        The fully resolved path, guaranteed to sit inside ``media_root``.

    Raises:
        MediaPathError: If the reference violates the allowlist.
    """
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise MediaPathError("media reference must be a non-empty relative path string")

    candidate = Path(relative_path)
    if candidate.is_absolute() or candidate.drive:
        raise MediaPathError("media reference must be a relative path under media_root")

    root = media_root.resolve()
    resolved = (media_root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise MediaPathError("media reference escapes the allowlisted media_root")

    if must_exist:
        if not resolved.exists():
            raise MediaPathError("media reference does not exist under media_root")
        if not resolved.is_file():
            raise MediaPathError("media reference is not a file under media_root")
    return resolved
