"""No test function disappears without someone saying so.

WHY THIS EXISTS. Integrating reviewer-c-branch on 2026-08-24 produced a suite of
1,207 passing tests that was nonetheless MISSING 25 regression tests present on
main. Nothing caught it. The checks that ran were each correct and each blind to
the layer beneath:

    git diff --diff-filter=D   ->  missed rename-paired deletions (6 twins)
    whole-file deletion check  ->  missed content cut from surviving files
                                   (the E03/E03 target slots)
    test-MODULE count (71)     ->  missed test FUNCTIONS inside the modules
    "the suite is green"       ->  missed that the suite was simply smaller

A green suite is not evidence of an intact suite. This file closes the last two
layers: the manifest names every test function, and removal fails by name rather
than showing up as a slightly smaller number nobody reads.

REGENERATING THE MANIFEST IS ALLOWED. Renaming and consolidating tests is normal
work. What is not allowed is a removal nobody noticed, so the manifest is
committed, the diff is visible in review, and the commit has to say why.
"""
from __future__ import annotations

import ast
import io
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = PROJECT_ROOT / "tests"
MANIFEST = TESTS_DIR / "TEST_MANIFEST.json"

#: Guards whose removal would silently un-gate something expensive. These are
#: named individually because a count would not notice which one went.
LOAD_BEARING = (
    "test_the_capability_flag_is_still_off_on_disk",
    "test_strategic_cell_refuses_to_build",
    "test_content_failures_are_never_retried",
    "test_shipped_vocabulary_is_cleared_and_attributed",
    "test_benign_error_analyst_prompt_is_byte_identical_to_honest",
    "test_correct_decisions_all_notify",
)


def _collect() -> dict[str, str]:
    found: dict[str, str] = {}
    for f in sorted(TESTS_DIR.rglob("test_*.py")):
        if "__pycache__" in str(f):
            continue
        try:
            tree = ast.parse(io.open(f, encoding="utf-8").read())
        except SyntaxError:
            continue
        rel = str(f.relative_to(PROJECT_ROOT)).replace("\\", "/")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name.startswith("test_"):
                found.setdefault(node.name, rel)
    return found


def _manifest() -> dict[str, str]:
    return json.loads(io.open(MANIFEST, encoding="utf-8").read())["tests"]


def test_the_manifest_exists_and_is_not_empty():
    """Anti-vacuity: every assertion below would pass on an empty manifest."""
    assert MANIFEST.exists(), f"{MANIFEST} is missing — regenerate it"
    m = _manifest()
    assert len(m) >= 400, f"manifest has only {len(m)} entries; that is not this suite"


def test_no_manifested_test_has_disappeared():
    """The one that would have caught the 25."""
    missing = sorted(set(_manifest()) - set(_collect()))
    assert not missing, (
        f"{len(missing)} test function(s) in the manifest no longer exist. If this is a "
        f"rename or a deliberate consolidation, regenerate TEST_MANIFEST.json in the same "
        f"commit and say why. If it is not, a regression test has been removed.\n  "
        + "\n  ".join(missing))


def test_the_manifest_is_not_stale():
    """New tests must be manifested too, or the guard erodes silently: a
    manifest that lags the suite protects less of it every week."""
    extra = sorted(set(_collect()) - set(_manifest()))
    assert not extra, (
        f"{len(extra)} test function(s) are not in the manifest. Regenerate it.\n  "
        + "\n  ".join(extra[:20]))


@pytest.mark.parametrize("name", LOAD_BEARING)
def test_the_named_load_bearing_guards_are_present(name):
    """A count cannot tell you WHICH test went. These are named so it can."""
    assert name in _collect(), (
        f"{name} is gone. It is named here because its removal would silently "
        f"un-gate something the project has already paid to learn.")
