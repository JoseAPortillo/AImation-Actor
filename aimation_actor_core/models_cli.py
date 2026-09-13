"""``aimation-models`` — local model catalog CLI (console script).

A top-level composition root (SDD §2.2): it may import ``infrastructure``
directly, unlike the HTTP-only ``aimation_actor_core.cli`` client. Subcommands
operate on a local models root (default ``models/``):

- ``list`` — catalog entries with on-disk status.
- ``install`` — license-gated, hash-verified download (``--accept-license``
  required; ``--trust-on-first-use`` to accept entries without a sha256).
- ``verify`` — integrity status of a single installed model.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aimation_actor_core.infrastructure.models import (
    ModelManifestError,
    ModelNotFoundError,
    ModelProvisioner,
    ModelProvisionError,
    ModelRegistry,
)

PROG = "aimation-models"


def _cmd_list(args: argparse.Namespace) -> int:
    """Print the catalog as an aligned table (name, kind, license, status, file)."""
    registry = ModelRegistry(Path(args.root))
    specs = registry.load()
    if not specs:
        print("no models in catalog")
        return 0
    headers = ("name", "kind", "license", "status", "file")
    rows = [
        (spec.name, spec.kind, spec.license, registry.status(spec), spec.file)
        for spec in specs
    ]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    separator = "  "
    template = separator.join(f"{{:<{width}}}" for width in widths)
    print(template.format(*headers))
    for row in rows:
        print(template.format(*row))
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    """Install a catalog model; print the installed path on success."""
    registry = ModelRegistry(Path(args.root))
    spec = registry.get(args.name)
    target = ModelProvisioner(registry).install(
        spec,
        accept_license=args.accept_license,
        trust_on_first_use=args.trust_on_first_use,
    )
    print(target)
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    """Print the model's status; exit 1 when it is not healthy."""
    registry = ModelRegistry(Path(args.root))
    status = registry.status(registry.get(args.name))
    print(status)
    return 1 if status in {"missing", "corrupt"} else 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the ``aimation-models`` argument parser."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Manage local AI model files (catalog + provisioning).",
    )
    parser.add_argument(
        "--root",
        default="models",
        help="models directory holding manifest.json (default: models)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list catalog models and their install status").set_defaults(
        func=_cmd_list
    )

    install = sub.add_parser("install", help="download and install a catalog model")
    install.add_argument("name", help="model name from the manifest")
    install.add_argument(
        "--accept-license",
        default=None,
        help="SPDX license identifier you accept (must match the manifest entry)",
    )
    install.add_argument(
        "--trust-on-first-use",
        action="store_true",
        help="accept an entry with no recorded sha256 and record the observed hash",
    )
    install.set_defaults(func=_cmd_install)

    verify = sub.add_parser("verify", help="verify an installed model's integrity")
    verify.add_argument("name", help="model name from the manifest")
    verify.set_defaults(func=_cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (console script ``aimation-models``)."""
    args = _build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (ModelManifestError, ModelNotFoundError, ModelProvisionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - also reachable via entry point
    raise SystemExit(main())