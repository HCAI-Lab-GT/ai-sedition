"""The run manifest must record what executes, not what somebody remembered.

THE DEFECT THIS PINS. `scripts/run_two_axis.py` wrote the token budgets into
`run-manifest.json` from a literal::

    budgets = RAISED_BUDGETS if a.raised_budgets else {
        "selection_max_tokens": 1200, "briefing_max_tokens": 4000,
        "monitor_max_tokens": 1600}

The values that execute are the keyword defaults on `solver.sedition_episode`
and the module constant `scorers.MONITOR_MAX_TOKENS`, all three of which were
raised on 2026-08-22. Thirteen of the fourteen manifests committed under
`logs/` therefore describe a configuration no episode ever ran under, and
`logs/final240/run-manifest.json` -- a 240-episode run -- is one of them.

Nothing caught it because nothing compared the two. These tests are that
comparison, and they are written so that they fail if the manifest ever goes
back to restating a number instead of reading it.
"""

from __future__ import annotations

import functools
import json

import pytest

from sedition_inspect import effective_config as effcfg
from sedition_inspect import scorers as scorers_mod
from sedition_inspect import solver as solver_mod
from sedition_inspect import task as task_mod
from sedition_inspect.run import MODEL_SETS

#: Imported for the side effect as much as the names: importing the launcher
#: registers `foundry_frozen_flash` in MODEL_SETS, which is the set the
#: confirmatory run uses and which `run.py` does not declare.
import scripts.run_two_axis as R  # noqa: E402  (import order is load-bearing)

MODEL_SET = "foundry_frozen_flash"


@pytest.fixture
def restore_solver():
    """Undo any rebinding of the solver or the monitor budget.

    `--raised-budgets` mutates module attributes on `task` and `scorers`, and
    two tests below do the same to prove the introspection follows. Without
    this fixture the first of them would silently change the budgets every
    later test in the session reads.
    """
    original_solver = task_mod.sedition_episode
    original_monitor = scorers_mod.MONITOR_MAX_TOKENS
    try:
        yield
    finally:
        task_mod.sedition_episode = original_solver
        scorers_mod.MONITOR_MAX_TOKENS = original_monitor


# ------------------------------------------------------------ the defect ----


def test_the_budgets_are_read_from_the_solver_not_restated():
    """The recorded budgets are the solver's own defaults, value for value.

    Read through `inspect.signature` here as well, so this test cannot pass by
    agreeing with a second copy of the same literal.
    """
    import inspect as _inspect

    sig = _inspect.signature(solver_mod.sedition_episode)
    budgets = effcfg.token_budgets()
    for name in effcfg.SOLVER_TOKEN_PARAMS:
        assert budgets[name] == sig.parameters[name].default, (
            f"{name} recorded as {budgets[name]}, solver default is {sig.parameters[name].default}"
        )
    assert budgets["monitor_max_tokens"] == scorers_mod.MONITOR_MAX_TOKENS


def test_the_retired_literal_is_not_what_executes():
    """Anti-vacuity, and the regression stated directly.

    Every assertion above would also pass if the solver defaults happened to
    equal the old literal. They do not, and that gap IS the defect: this test
    fails the moment someone reintroduces `{1200, 4000, 1600}` as the recorded
    configuration.
    """
    budgets = effcfg.token_budgets()
    disagree = {
        k: (v, budgets[k]) for k, v in effcfg.RETIRED_BUDGET_LITERAL.items() if budgets[k] != v
    }
    assert disagree == {
        "selection_max_tokens": (1200, 4000),
        "briefing_max_tokens": (4000, 8000),
        "monitor_max_tokens": (1600, 4000),
    }, (
        f"the retired manifest literal now agrees with the code in some places: "
        f"{disagree}. If the defaults moved, this test's expectation moves with "
        f"them -- but the manifest must never be written from the literal again."
    )


# ------------------------------------------------- overrides are followed ----


def test_a_raised_budget_override_is_recorded_post_override(restore_solver):
    """`--raised-budgets` rebinds `task.sedition_episode` to a partial.

    The manifest has to report the value AFTER that rebinding, which is the
    whole reason `solver_keywords` reads the task module rather than the solver
    module.
    """
    task_mod.sedition_episode = functools.partial(
        solver_mod.sedition_episode,
        selection_max_tokens=R.RAISED_BUDGETS["selection_max_tokens"],
        briefing_max_tokens=R.RAISED_BUDGETS["briefing_max_tokens"],
    )
    scorers_mod.MONITOR_MAX_TOKENS = R.RAISED_BUDGETS["monitor_max_tokens"]

    budgets = effcfg.token_budgets()
    assert budgets["briefing_max_tokens"] == 10000
    assert budgets["selection_max_tokens"] == 4000
    assert budgets["monitor_max_tokens"] == 4000
    # Not overridden, so still the solver default -- the override is partial in
    # both senses and the manifest must not imply otherwise.
    assert budgets["officer_max_tokens"] == 2600


def test_an_override_the_solver_cannot_accept_is_refused(restore_solver):
    """A partial binding a keyword the solver has no parameter for would fail
    at episode construction, after the run had started. It fails here instead."""
    task_mod.sedition_episode = functools.partial(
        solver_mod.sedition_episode, briefing_max_toknes=10000
    )
    with pytest.raises(effcfg.EffectiveConfigError, match="briefing_max_toknes"):
        effcfg.token_budgets()


def test_a_budget_threaded_through_the_task_is_refused(monkeypatch):
    """The introspection is only sound while the task does not supply the value.

    If `sedition_briefing` ever takes a budget as a task argument, the solver's
    default stops being what executes and this module would keep recording it.
    """

    def fake_task(*, packets: str = "", briefing_max_tokens: int = 999) -> None:
        """Stand-in task that threads a budget the real one does not."""

    monkeypatch.setattr(task_mod, "sedition_briefing", fake_task)
    with pytest.raises(effcfg.EffectiveConfigError, match="briefing_max_tokens"):
        effcfg.token_budgets()


# ------------------------------------------------------ roles and seeds ----


def test_every_role_records_model_temperature_and_seed():
    roles = effcfg.role_config(MODEL_SET, seed=None)
    assert set(roles) == {"analyst", "watch_officer", "monitor"}
    for role, spec in roles.items():
        declared = MODEL_SETS[MODEL_SET][role]
        assert spec["model"] == declared[0]
        assert spec["declared_temperature"] == declared[1]
        assert "applied_temperature" in spec
        assert spec["seed"] is None, (
            "run_two_axis calls build_model_roles with MODEL_SAMPLING_SEED; if "
            "that stops being None the manifest must record the new value"
        )


def test_the_seed_the_manifest_records_is_the_seed_the_launcher_passes():
    """Anti-assertion: the manifest's seed claim has to be the executed one.

    `MODEL_SAMPLING_SEED` exists so the value is named once and passed at the
    call site, rather than the manifest describing a call it cannot see.
    """
    assert R.MODEL_SAMPLING_SEED is None
    roles = effcfg.role_config(MODEL_SET, seed=R.MODEL_SAMPLING_SEED)
    assert {spec["seed"] for spec in roles.values()} == {R.MODEL_SAMPLING_SEED}


def test_the_applied_temperature_is_the_one_the_call_site_sends():
    """`MODEL_SETS` sets a temperature on the role model, and every call site
    overrides it -- `Model._resolve_config` merges the call-site config last.
    The analyst's comes from the solver keyword; the officer's and the
    monitor's are literals in their call sites."""
    applied = effcfg.applied_temperatures()
    assert applied["analyst"] == effcfg.solver_keywords()["analyst_temperature"]
    assert applied["watch_officer"] == 0.0
    assert applied["monitor"] == 0.0


@pytest.mark.parametrize("model_set", sorted(MODEL_SETS))
def test_no_committed_model_set_declares_a_temperature_that_is_ignored(model_set):
    """Editing a `MODEL_SETS` temperature looks like changing the sampling and
    does not. Every committed set must therefore declare the value its call site
    actually sends, or the manifest records a number that reached no provider."""
    assert effcfg.temperature_disagreements(model_set) == []


def test_the_temperature_guard_can_fire():
    """Anti-vacuity for the test above: with every committed set already in
    agreement, nothing exercises the disagreement branch."""
    MODEL_SETS["_probe_hot_officer"] = {
        "analyst": ("azureai/DeepSeek-V4-Pro", 0.7),
        "watch_officer": ("azureai/DeepSeek-V4-Flash", 0.9),
        "monitor": ("azureai/DeepSeek-V4-Flash", 0.0),
    }
    try:
        found = effcfg.temperature_disagreements("_probe_hot_officer")
        assert len(found) == 1 and "watch_officer" in found[0]
    finally:
        MODEL_SETS.pop("_probe_hot_officer", None)


def test_a_mock_role_is_exempt_from_the_temperature_guard():
    """The mock set declares analyst 0.0 while the solver sends 0.7. A
    deterministic test double has no sampling, so this is not drift -- and
    treating it as drift would refuse every mock launch."""
    assert MODEL_SETS["mock"]["analyst"][1] != effcfg.applied_temperatures()["analyst"]
    assert effcfg.temperature_disagreements("mock") == []


# --------------------------------------------------- the manifest self-check --


def _namespace(**over):
    """A parsed-argument stand-in with the launcher's own defaults."""
    import argparse

    base = dict(
        model_set=MODEL_SET,
        benign_mechanism="subset",
        master_seed=20260814,
        officer_version="v6_assessor",
        standard="notification_standard_v3_relational",
        threshold_k=3,
        overlay="current",
        selection_mode="free",
        raised_budgets=False,
        log_root="logs/_selfcheck_probe",
    )
    base.update(over)
    return argparse.Namespace(**base)


def _manifest(tmp_path, **over):
    from pathlib import Path

    args = _namespace(log_root=str(tmp_path), **over)
    jobs = [
        R.Job(
            "honest_straight",
            "threat",
            MODEL_SET,
            ("E01-MS",),
            Path(args.log_root) / "honest_straight__threat",
        )
    ]
    blocks = (9999,)
    chash = R.config_hash(args, blocks, jobs)
    return args, blocks, jobs, R.build_manifest(args, chash, blocks, jobs, ())


def test_the_manifest_the_launcher_builds_passes_its_own_check(tmp_path):
    """Anti-vacuity. Every failure test below would pass against a self-check
    that always reported findings."""
    args, _blocks, _jobs, manifest = _manifest(tmp_path)
    assert R.manifest_self_check(args.log_root, manifest) == []


def test_the_manifest_is_json_native(tmp_path):
    """`json.dumps(..., default=str)` writes something other than what was
    computed, and every later comparison is then against a string. The manifest
    must serialise without coercion and read back identically."""
    _args, _blocks, _jobs, manifest = _manifest(tmp_path)
    assert json.loads(json.dumps(manifest)) == manifest


def test_a_tampered_budget_fails_the_self_check(tmp_path):
    """The defect, caught. This is what the check would have said on
    2026-08-22 if it had existed."""
    args, _blocks, _jobs, manifest = _manifest(tmp_path)
    manifest["effective_config"]["token_budgets"]["selection_max_tokens"] = 1200
    findings = R.manifest_self_check(args.log_root, manifest)
    assert any("selection_max_tokens" in f and "1200" in f for f in findings), findings


def test_assert_config_matches_raises_rather_than_returning(tmp_path):
    _args, _blocks, _jobs, manifest = _manifest(tmp_path)
    recorded = json.loads(json.dumps(manifest["effective_config"]))
    effcfg.assert_config_matches(recorded, MODEL_SET, seed=None)
    recorded["token_budgets"]["monitor_max_tokens"] = 1600
    with pytest.raises(effcfg.ManifestMismatch, match="monitor_max_tokens"):
        effcfg.assert_config_matches(recorded, MODEL_SET, seed=None)


def test_a_manifest_already_on_disk_must_agree_with_this_launch(tmp_path):
    """A resume whose config changed produces one log directory holding two
    experiments. The manifest already written is the record of the first."""
    args, _blocks, _jobs, manifest = _manifest(tmp_path)
    (tmp_path / "run-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    assert R.manifest_self_check(args.log_root, manifest) == []

    _a2, _b2, _j2, changed = _manifest(tmp_path, threshold_k=2)
    findings = R.manifest_self_check(args.log_root, changed)
    assert any("threshold_k" in f for f in findings), findings


# End of effective-configuration checks.
