"""``aimation-eval`` — local quality-metrics CLI (console script).

A top-level composition root (SDD §2.2). Loads a NeutralMotion JSON document
(0.2 is migrated to canonical 0.3 via :func:`migrate_neutral_motion`), computes
the pure-domain quality metrics (plan §21 Phase 1), and prints a readable
table; ``--out`` additionally writes a pretty JSON report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aimation_actor_core.domain.animation import NeutralMotion, migrate_neutral_motion
from aimation_actor_core.domain.animation.metrics import QualityReport, compute_metrics

PROG = "aimation-eval"


class EvalCliError(Exception):
    """Fatal CLI error — printed to stderr and mapped to a non-zero exit."""


def _load_motion(path: Path) -> NeutralMotion:
    """Read and migrate a NeutralMotion document from ``path``.

    Raises:
        EvalCliError: If the file cannot be read or is not valid JSON.
        ValueError: If the document version is unsupported or the shape is
            invalid (propagated from the migration/validation layer).
    """
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvalCliError(f"cannot read motion file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EvalCliError(f"invalid JSON in {path}: {exc}") from exc
    return migrate_neutral_motion(raw)


def _print_report(report: QualityReport) -> None:
    """Print the report as a readable two-column table."""
    rows = (
        ("metric", "value"),
        ("jitter_score", f"{report.jitter_score:.6f}"),
        ("foot_sliding_score", f"{report.foot_sliding_score:.6f}"),
        ("root_drift", f"{report.root_drift:.6f}"),
        ("frames", str(report.frames)),
        ("duration_frames", str(report.duration_frames)),
    )
    width = max(len(name) for name, _ in rows)
    for name, value in rows:
        print(f"{name:<{width}}  {value}")


def _cmd_report(args: argparse.Namespace) -> int:
    """Compute and print (optionally write) the quality report."""
    motion = _load_motion(Path(args.motion))
    report = compute_metrics(motion)
    _print_report(report)
    if args.out:
        try:
            Path(args.out).write_text(
                json.dumps(report.model_dump(), indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise EvalCliError(f"cannot write {args.out}: {exc}") from exc
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the ``aimation-eval`` argument parser."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Compute quality metrics for a NeutralMotion document.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    report = sub.add_parser("report", help="compute and print the quality report")
    report.add_argument("--motion", required=True, help="NeutralMotion JSON file")
    report.add_argument("--out", default=None, help="write the report JSON to this file")
    report.set_defaults(func=_cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (console script ``aimation-eval``)."""
    args = _build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except EvalCliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        # UnsupportedNeutralVersionError and pydantic ValidationError both
        # subclass ValueError; map them to a clean exit-1 instead of a traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - also reachable via entry point
    raise SystemExit(main())