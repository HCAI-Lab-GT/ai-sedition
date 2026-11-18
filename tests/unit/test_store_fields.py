"""Every attribute the solver writes must be a declared store Field.

THE BUG THIS CATCHES, twice in one session. `EpisodePublic` and
`AnalystPrivate` are Inspect `StoreModel`s: assigning to an attribute that is
not a declared Field raises at RUNTIME, mid-episode, not at import. Adding a
field as a bare annotation —

    overridden: bool = False          # wrong, silently not a Field
    overridden: bool = Field(...)     # right

— looks correct, passes import, passes every test that does not run a real
episode, and then kills the run.

It cost 36 real episodes: every rung-1 episode reached the selection call,
recorded its ABSTAIN, and then died on `private.overridden = True` with
'"AnalystPrivate" object has no field "overridden"'. The eval reported
status=success because the sample error was captured per-sample, so the
failure was invisible until the store was read back.

Same family as DECISIONS.md #26: something reported success about a thing it
was not actually checking.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from sedition_inspect._store import AnalystPrivate, EpisodePublic

REPO = Path(__file__).resolve().parents[2]
ADAPTER = REPO / "src" / "sedition_inspect"
SOLVER = ADAPTER / "solver.py"

MODELS = {"public": EpisodePublic, "private": AnalystPrivate}


def _assigned_attributes() -> dict[str, set[str]]:
    """Every `public.x = ...` / `private.x = ...` in the solver."""
    tree = ast.parse(SOLVER.read_text(encoding="utf-8"))
    found: dict[str, set[str]] = {k: set() for k in MODELS}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AugAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            if (isinstance(t, ast.Attribute)
                    and isinstance(t.value, ast.Name)
                    and t.value.id in found):
                found[t.value.id].add(t.attr)
    return found


@pytest.mark.parametrize("var,model", MODELS.items(), ids=list(MODELS))
def test_every_attribute_the_solver_writes_is_a_declared_field(var, model):
    written = _assigned_attributes()[var]
    declared = set(model.model_fields)
    undeclared = sorted(written - declared)
    assert not undeclared, (
        f"solver.py assigns {var}.{undeclared} but {model.__name__} declares "
        f"no such Field. A StoreModel raises at runtime on an undeclared "
        f"attribute, so this kills every episode that reaches the assignment. "
        f"Declare it with Field(default=...), not a bare annotation."
    )


@pytest.mark.parametrize("name,model", MODELS.items(), ids=list(MODELS))
def test_no_store_field_is_a_bare_annotation(name, model):
    """A bare annotation is not a Field, and the difference is invisible until
    an episode runs."""
    src = (ADAPTER / "_store.py").read_text(encoding="utf-8")
    body = src.split(f"class {model.__name__}")[1].split("\nclass ")[0]
    bare = re.findall(r"^\s{4}([a-z_]+)\s*:\s*[^=\n]+=\s*(?!Field\()(\S)", body, re.M)
    assert not bare, (
        f"{model.__name__} has fields declared without Field(): "
        f"{[b[0] for b in bare]}"
    )
