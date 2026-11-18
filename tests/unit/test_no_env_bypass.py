"""No script may construct a real provider model without loading .env first.

THE BUG THIS CLASS KEEPS PRODUCING. `get_model()` resolves the azureai key in
`__init__` and otherwise falls through to managed identity, so the credential
is captured on the object and a later dotenv load cannot displace it. A
script that calls `get_model("azureai/...")` before loading .env dies with
"requires the azure-identity package" — which names the wrong fix, because
installing that package makes it worse: construction then succeeds with a
token provider that 401s on every call.

It has happened twice. First in sedition_inspect/run.py, found by
the pre-matrix audit. Then again in scripts/officer_instrument_audit.py,
which reintroduced it by bypassing build_model_roles — the same file that
carries a comment about the original.

Same family as the probe-verified-not-harness-verified findings in
DECISIONS.md #26: a helper drifting from the real path.

The rule: a module that names a real provider must either go through
build_model_roles (which loads .env) or call load_project_dotenv itself.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
#: Provider prefixes that need a credential. mockllm needs nothing.
REAL_PROVIDERS = ("azureai/", "openai/", "anthropic/")

#: WIDENED to rglob 2026-08-26. It was `glob("*.py")`, top level only, so
#: scripts/strat_dev/ was never scanned -- and moving analyze_full_matched.py
#: into scripts/legacy/ would have quietly removed it from the guard too. A
#: script that names a real provider and skips load_project_dotenv is exactly as
#: dangerous one directory down.
SCANNED = sorted(p for p in (REPO / "scripts").rglob("*.py")
                 if "__pycache__" not in p.parts)


def _names_a_real_provider(text: str) -> bool:
    # Ignore the prefix appearing only inside a comment or docstring line.
    code = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    return any(p in code for p in REAL_PROVIDERS)


#: Declared exemptions: scripts that name a provider string but never build a
#: model, so there is no credential to resolve and nothing for .env to supply.
#: Named individually rather than loosened out of the detector, and checked
#: below so the list cannot go stale into a vacuous pass.
#:
#: Surfaced 2026-08-26 when SCANNED was widened to rglob and picked up
#: scripts/strat_dev/ for the first time. Pre-existing, not caused by the
#: widening: these were simply never scanned.
_NO_MODEL_CONSTRUCTED = {
    # names the three azureai model ids only as keys in a per-token price
    # table, to cost a completed run out of its logs.
    "strat_analyze.py",
}


PROVIDER_SCRIPTS = tuple(
    p for p in SCANNED
    if _names_a_real_provider(p.read_text(encoding="utf-8"))
    and p.name not in _NO_MODEL_CONSTRUCTED
)


@pytest.mark.parametrize("path", PROVIDER_SCRIPTS, ids=lambda p: p.name)
def test_script_naming_a_real_provider_loads_dotenv(path):
    text = path.read_text(encoding="utf-8")
    routed = "build_model_roles" in text
    loads = "load_project_dotenv" in text
    assert routed or loads, (
        f"{path.name} names a real provider but neither goes through "
        f"build_model_roles nor calls load_project_dotenv. get_model resolves the "
        f"azureai credential at construction, so .env must be loaded first — "
        f"see DECISIONS.md #26."
    )


@pytest.mark.parametrize("name", sorted(_NO_MODEL_CONSTRUCTED))
def test_an_exempt_script_really_constructs_no_model(name):
    """Guards the exemption list from going stale into a vacuous pass.

    An exemption that stops being true is worse than no exemption: it excuses
    a script that now DOES build a model, and the failure is a missing
    credential at run time rather than here.
    """
    hits = [p for p in SCANNED if p.name == name]
    assert hits, f"{name} is exempted but is not on disk; drop it from the list"
    text = hits[0].read_text(encoding="utf-8")
    for token in ("get_model(", "build_model_roles", "eval(", "eval_async"):
        assert token not in text, (
            f"{name} is declared as constructing no model but contains "
            f"{token!r}; remove the exemption and make it load .env")


def test_the_runner_itself_still_loads_dotenv():
    """The original instance. Guarded here too so a refactor cannot quietly
    drop it from the one path every real run goes through.

    Ordering is checked on the AST, not on raw text: run.py's comment
    explaining this bug contains the literal "get_model(", so a string search
    matches the explanation rather than the call.
    """
    import ast
    import inspect as _inspect
    import textwrap

    from sedition_inspect.run import build_model_roles

    tree = ast.parse(textwrap.dedent(_inspect.getsource(build_model_roles)))
    names = [
        getattr(n.func, "id", getattr(n.func, "attr", ""))
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    ]
    assert "load_project_dotenv" in names, "build_model_roles no longer loads .env"
    gm = [i for i, n in enumerate(names) if n == "get_model"]
    assert gm, "build_model_roles no longer constructs a model"
    assert names.index("load_project_dotenv") < min(gm), (
        "load_project_dotenv must run BEFORE the first get_model call — the azureai "
        "credential is captured at construction"
    )
