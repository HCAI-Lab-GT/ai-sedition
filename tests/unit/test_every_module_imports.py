"""Every shipped module must at least parse and import.

WHY THIS EXISTS: on 2026-08-23 `sedition/cli/vocab.py` was committed with a raw
newline inside a string literal -- an outright SyntaxError. The full suite stayed
green at 864 passed, because no test imported that module. The CLI entry point
was broken and nothing said so.

A syntax error that only surfaces when a human runs the CLI is the same class of
failure as a check that passes vacuously: the signal says fine, the artefact is
not. These two tests are the cheapest possible floor under that.
"""
from __future__ import annotations

import ast
import importlib
import io
import pkgutil
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src"
ROOTS = {
    "sedition": SOURCE_ROOT / "sedition",
    "sedition_inspect": SOURCE_ROOT / "sedition_inspect",
}


def _py_files():
    for base in ROOTS.values():
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


def test_every_module_parses():
    """Cheap and total: catches a SyntaxError even in a module nothing imports."""
    broken = []
    for path in _py_files():
        try:
            ast.parse(io.open(path, encoding="utf-8").read(), filename=str(path))
        except SyntaxError as exc:
            broken.append(f"{path.relative_to(PROJECT_ROOT)}:{exc.lineno}: {exc.msg}")
    assert not broken, "modules that do not parse:\n  " + "\n  ".join(broken)


def _module_names():
    for root, base in ROOTS.items():
        for mod in pkgutil.walk_packages([str(base)], prefix=f"{root}."):
            if mod.name.rsplit(".", 1)[-1].startswith("_kill"):
                continue
            yield mod.name


@pytest.mark.parametrize("name", sorted(_module_names()))
def test_module_imports(name):
    """Parsing is not enough -- a bad top-level call or import also breaks a CLI."""
    importlib.import_module(name)
