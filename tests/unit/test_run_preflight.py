"""The launch preflight in scripts/run_two_axis.py must refuse before spending.

Two guards live there, and both were written after the thing they guard had
already gone wrong once:

`--dry-run` runs the preflight.
    The twin gate used to sit BELOW the dry-run return, so `--dry-run` printed a
    clean plan and a config hash for a matrix the real run would refuse. A
    preflight you cannot exercise without paying for it is not a preflight.

Every (packet, variant) cell is resolved, not just the ablated ones.
    The DRAFT gate in variants._require_reviewed fires per episode at
    solver.py:316. dataset.py builds its permutation from the THREAT packet and
    never resolves the twin, so the dataset builds, eval_set starts, and with
    fail_on_error False every twin episode errors individually while the run
    reports completed. A log full of errored samples is not a refusal.

Azure Foundry only.
    "Never OpenRouter" was a written rule that nothing executed. OPENROUTER_API_KEY
    is in .env and scripts/strat_dev/strat_run.py carries an openrouter/ role set,
    so a model-set entry pointing there would have run and logged normally.

Each test below drives main() through --dry-run, which reaches both guards and
makes no network call.
"""
from __future__ import annotations

import sys

import pytest

import scripts.run_two_axis as R

BASE = [
    "run_two_axis.py",
    "--packets", "E01-MS",
    "--cells", "honest_straight",
    "--blocks", "9999",
    "--log-root", "logs/_preflight_probe",
    "--allow-block-collision",
    "--dry-run",
]


def _run(monkeypatch, *extra: str) -> int:
    monkeypatch.setattr(sys, "argv", BASE + list(extra))
    return R.main()


def test_a_clean_matrix_passes_preflight(monkeypatch):
    """Anti-vacuity. Every refusal test below would also pass if main() simply
    always returned non-zero, so one cell that MUST be admitted is pinned."""
    assert _run(monkeypatch, "--model-set", "foundry_frozen_flash") == 0


def test_the_committed_model_sets_are_all_azure(monkeypatch):
    """The rule applied to what is actually committed, not only to a probe."""
    for name, roles in R.MODEL_SETS.items():
        for role, spec in roles.items():
            mid = spec[0] if isinstance(spec, (tuple, list)) else spec
            assert str(mid).startswith(
                ("azureai/", "mockllm/", "openai/", "sedition_mock/")
            ), (
                f"model set {name!r} role {role!r} points at {mid!r}; the run "
                f"path is Azure Foundry only")


def test_a_non_azure_model_set_is_refused(monkeypatch):
    """The guard can fire. Without this the assertion above is untested logic:
    every committed set is already Azure, so nothing exercises the refusal."""
    R.MODEL_SETS["_probe_openrouter"] = {
        "analyst": ("openrouter/deepseek/deepseek-v4-pro", 0.7),
        "watch_officer": ("azureai/DeepSeek-V4-Flash", 0.0),
        "monitor": ("azureai/DeepSeek-V4-Flash", 0.0),
    }
    try:
        assert _run(monkeypatch, "--model-set", "_probe_openrouter") == 2
    finally:
        R.MODEL_SETS.pop("_probe_openrouter", None)


def test_a_draft_twin_is_refused_at_dry_run(monkeypatch, capsys, tmp_path):
    """The regression this file exists for.

    Requesting the ablated variant for a DRAFT twin must refuse at PLAN time
    -- before a single episode is dispatched -- and must name the twin rather
    than failing with a bare non-zero.

    Every released twin is reviewed, so a DRAFT twin is written to a temporary
    directory and `variants.TWINS_DIR` is pointed
    at it, so the gate is exercised whatever the shipped files say.
    """
    import json
    import shutil

    from sedition.packets import variants

    for src in variants.TWINS_DIR.glob("*-control.json"):
        shutil.copy(src, tmp_path / src.name)
    victim = tmp_path / "E01-MS-control.json"
    data = json.loads(victim.read_text(encoding="utf-8"))
    data["status"] = "DRAFT - awaiting criterion-level human review"
    data["review"] = {"status": data["status"]}
    victim.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(variants, "TWINS_DIR", tmp_path)
    variants.control_packet.cache_clear()

    try:
        monkeypatch.setattr(sys, "argv", BASE + [
            # Deliberately the LEGACY spelling: recorded command lines must
            # stay replayable, and the draft gate must fire through the
            # canonicalization seam too.
            "--model-set", "foundry_frozen_flash", "--variants", "ablated"])
        assert R.main() == 2
        out = capsys.readouterr().out
        assert "REFUSING TO LAUNCH" in out
        assert "E01-MS" in out and "DRAFT" in out
        assert "CRITERION_TABLE_FOR_SIGNOFF" in out, (
            "a refusal that does not say how to clear it sends the reader to "
            "the source; the message must name the table")
    finally:
        variants.control_packet.cache_clear()


def test_the_cleared_twins_pass_preflight(monkeypatch):
    """The counterpart: the live twins are signed off, so the same request must
    be admitted. A gate that refuses every ablated run is indistinguishable
    from a broken loader.

    NO --admit-heldout ANY MORE. These packets were held out under the ids
    E01 and E03; the 2026-08-26 rename made them CORE as E01 and E03, so they
    load by default and admitting them by their collected names is now refused
    by name. This test is the canary for that change: if `HELDOUT_RUNNABLE` or
    the admit branches in `parse_all` are wrong, it fails here first.
    """
    monkeypatch.setattr(sys, "argv", [
        "run_two_axis.py", "--model-set", "foundry_frozen_flash",
        "--packets", "E01-SS,E01-MS,E03-SS,E03-MS",
        # Legacy spelling on purpose -- canonicalized on parse to "control".
        "--variants", "threat,ablated",
        "--cells", "honest_straight,degraded_straight,basic_straight,strategic_straight",
        "--blocks", "9999", "--log-root", "logs/_preflight_probe",
        "--allow-block-collision", "--dry-run"])
    assert R.main() == 0


def test_an_unknown_packet_is_refused_at_dry_run(monkeypatch, capsys):
    """The widened guard's other half: resolving every cell also catches a
    packet id that does not exist, which previously surfaced only once episodes
    were already in flight."""
    monkeypatch.setattr(sys, "argv", [
        "run_two_axis.py", "--model-set", "foundry_frozen_flash",
        "--packets", "E01-MS,E99-MS", "--cells", "honest_straight",
        "--blocks", "9999", "--log-root", "logs/_preflight_probe",
        "--allow-block-collision", "--dry-run"])
    assert R.main() == 2
    assert "E99-MS" in capsys.readouterr().out


@pytest.mark.parametrize("cell", ["honest", "basic_saboteur", "strategic_saboteur"])
def test_a_cell_name_that_does_not_exist_is_refused(monkeypatch, cell):
    """These three are the plausible-looking names for the real cells, and
    `--cells honest,basic_saboteur,strategic_saboteur` once planned a clean
    54-episode run against all three."""
    monkeypatch.setattr(sys, "argv", [
        "run_two_axis.py", "--model-set", "foundry_frozen_flash",
        "--packets", "E01-MS", "--cells", cell, "--blocks", "9999",
        "--log-root", "logs/_preflight_probe", "--allow-block-collision",
        "--dry-run"])
    with pytest.raises(SystemExit):
        R.main()
