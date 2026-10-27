"""Layering check for NFR-01: ``core/`` and ``ports/`` stay free of third-party imports.

The one-way dependency rule (``adapters → ports → core``) is what lets the domain
be tested without Qt, torch or Blender installed, and a rule like this only
survives with a machine checking it. This reads the import statements of every
domain module rather than importing them, so it catches a new dependency even when
the package is installed.

Being static has one limitation worth knowing: it sees module-level imports, not a
third-party import buried inside a function body reaching for a dependency.
Imports there would still be caught, since the statement is walked, but a dynamic
``importlib`` call would not be.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "aimation_actor"
DOMAIN_PACKAGES = ("core", "ports")

#: The domain may not reach back into the layers that depend on it.
_FORBIDDEN_PREFIXES = ("aimation_actor.adapters",)


def _domain_modules() -> list[Path]:
    modules: list[Path] = []
    for package in DOMAIN_PACKAGES:
        modules.extend(sorted((PACKAGE_ROOT / package).rglob("*.py")))
    return modules


def _imported_modules(path: Path) -> set[str]:
    """Dotted module names imported by ``path``, relative imports included."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module)
    return imported


def test_the_domain_packages_have_modules_to_check() -> None:
    # Without this, the check below would pass by finding nothing at all.
    modules = _domain_modules()
    names = {path.name for path in modules}

    assert modules, "expected modules under core/ and ports/"
    assert "models.py" in names


def test_core_and_ports_import_only_the_standard_library() -> None:
    offenders: list[str] = []
    for path in _domain_modules():
        for module in sorted(_imported_modules(path)):
            root = module.split(".")[0]
            if root == "aimation_actor" or root in sys.stdlib_module_names:
                continue
            offenders.append(f"{path.name} imports {module!r}")

    assert not offenders, "the domain must stay third-party free:\n" + "\n".join(offenders)


def test_the_domain_does_not_depend_on_the_adapters() -> None:
    offenders: list[str] = []
    for path in _domain_modules():
        for module in sorted(_imported_modules(path)):
            if module.startswith(_FORBIDDEN_PREFIXES):
                offenders.append(f"{path.name} imports {module!r}")

    assert not offenders, "adapters must not leak into the domain:\n" + "\n".join(offenders)
