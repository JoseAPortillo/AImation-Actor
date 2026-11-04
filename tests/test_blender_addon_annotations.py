"""Blender evaluates class-body annotations, so a callback inside one must be safe.

Blender reads class-body annotations to declare operator, preference and
property-group properties. Without ``from __future__ import annotations`` the
annotation is evaluated where it is written and a lambda inside it keeps this
module's globals. With the future import the annotation stays a **string**, and
Blender builds the callback from a namespace that does **not** carry the module's
own bindings: a callback written as
``items=lambda self, context: _items(self, context)`` raises
``NameError: name '_items' is not defined`` every time it runs. Blender swallows
that error, so the surface draws nothing while every Python-side check stays
green. That was the empty-picker defect in the transposition add-on.

Measured, not assumed (Blender 5.2.3, four combinations of future-import and
definition order): the failure depends on the future import alone. A helper
defined *above* the class fails exactly like one defined below it, so this is not
a definition-order problem. Names resolved while the annotation is *evaluated*
(``default=SOME_CONSTANT``, ``update=_on_folder``) are fine either way, which is
why ``prefs.py`` works untouched.

This scan needs no Blender: it parses the sources and reports any callback inside
a property annotation that names a module-level global while the module postpones
annotations.
"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path

import pytest

_ADDON = Path(__file__).resolve().parents[1] / "blender_addon" / "aimation_transpose"

#: Names Blender does provide, or that are always available.
_PROVIDED = {"bpy"} | set(dir(builtins))

_NESTED_FUNCTIONS = (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)


def _module_sources() -> list[Path]:
    return sorted(_ADDON.glob("*.py"))


def _postpones_annotations(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


def _module_level_names(tree: ast.Module) -> set[str]:
    """Every name the module binds at its top level."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(
                    sub.id for sub in ast.walk(target) if isinstance(sub, ast.Name)
                )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _property_annotations(tree: ast.Module):
    """Class-body annotations, which are what Blender reads as declarations."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if isinstance(child, ast.AnnAssign) and child.annotation is not None:
                yield node.name, child.annotation


def _local_names(node) -> set[str]:
    """Parameters and names the callback binds itself."""
    local: set[str] = set()
    arguments = getattr(node, "args", None)
    if arguments is not None:
        for group in (arguments.posonlyargs, arguments.args, arguments.kwonlyargs):
            local.update(argument.arg for argument in group)
        for extra in (arguments.vararg, arguments.kwarg):
            if extra is not None:
                local.add(extra.arg)
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            local.add(child.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local.add(child.name)
    return local


def _hidden_globals(annotation: ast.expr, module_names: set[str]) -> list[str]:
    """Module globals a callback inside ``annotation`` would fail to find."""
    hidden: set[str] = set()
    for node in ast.walk(annotation):
        if not isinstance(node, _NESTED_FUNCTIONS):
            continue
        local = _local_names(node)
        # A lambda's own parameters belong to the lambda, not to an enclosing one.
        for name in ast.walk(node):
            if (
                isinstance(name, ast.Name)
                and isinstance(name.ctx, ast.Load)
                and name.id in module_names - local
            ):
                hidden.add(name.id)
    return sorted(hidden)


@pytest.mark.parametrize("path", _module_sources(), ids=lambda path: path.name)
def test_a_callback_in_a_postponed_annotation_never_names_a_module_global(
    path: Path,
) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    if not _postpones_annotations(tree):
        return

    module_names = _module_level_names(tree) - _PROVIDED
    offenders = []
    for owner, annotation in _property_annotations(tree):
        hidden = _hidden_globals(annotation, module_names)
        if hidden:
            offenders.append(f"{owner}: {', '.join(hidden)}")

    assert not offenders, (
        f"{path.name} postpones annotations and a callback inside a property "
        f"declaration names module globals Blender cannot see at call time: "
        f"{'; '.join(offenders)}. "
        "Either remove 'from __future__ import annotations' from that module or "
        "make the callback a module-level plain function reference."
    )


def test_the_picker_keeps_its_annotation_evaluated_eagerly() -> None:
    """The specific regression: the picker's callback calls a module function."""
    path = _ADDON / "mapping.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    assert not _postpones_annotations(tree), (
        "mapping.py must not postpone annotations: Blender builds the picker's "
        "items callback in a namespace without this module's globals, so _items "
        "becomes a NameError and the search popup draws no rows"
    )
