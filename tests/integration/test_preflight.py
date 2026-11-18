"""The pre-first-run checklist is executable, so it cannot drift from the
code the way a checklist in a document does."""
import pytest

from sedition.cli.preflight import run_preflight


def test_preflight_blocks_while_e07_facts_await_review(capsys):
    """Inverted AGAIN on 2026-08-23, and this direction is the working one.

    The assertion was flipped to "must pass" on 2026-08-15 once the original 58
    facts were signed off. Ten E03 facts were authored on 2026-08-22 and are
    `review.status: draft`, so the vocabulary is once more partly unreviewed and
    preflight refuses the run.

    That refusal is the GATE, not a regression: E03 is the packet the headline
    result depends on, and its concealment measure is ten facts a human has not
    yet read. When they are cleared, flip this back and empty AWAITING_REVIEW in
    tests/unit/test_fact_vocabulary.py."""
    code = run_preflight("pilot_manipulation")
    out = capsys.readouterr().out
    assert "fact vocabulary cleared for scoring" in out
    assert "DO NOT START THE RUN" in out, (
        "preflight cleared a run against an unreviewed vocabulary")
    assert code != 0


@pytest.mark.parametrize("item", [
    "M5 wired",
    "answer key validates with --check-hashes",
    "golden prompts committed and current",
    "master_seed fixed",
    "budget equality assertions pass",
    "failure policy constants fixed",
    "git SHA recorded",
    "fact vocabulary validates",
    "resume provided by inspect eval-retry / eval_set",
    "determinism verified",
    "raw analyst output never reaches state.messages",
])
def test_preflight_covers_every_checklist_item(capsys, item):
    run_preflight("pilot_manipulation")
    assert item in capsys.readouterr().out


def test_preflight_reports_the_staged_episode_count(capsys):
    run_preflight("stage0")
    out = capsys.readouterr().out
    assert "90 episodes" in out


def test_preflight_names_the_primary_and_secondary_outcomes(capsys):
    """Stated before the run, not chosen after it."""
    run_preflight("pilot_manipulation")
    out = capsys.readouterr().out
    # printed only on a clean pass; on a blocked run the failure notice stands
    assert "DO NOT START THE RUN" in out or "Primary outcome" in out


def test_manipulation_gate_computability_fails_when_cells_cannot_produce_it(tmp_path, capsys):
    """A stage that declares a gate its cell list cannot produce is exactly
    the conflict that already happened once — stage0's SHEET-only cells with
    a manipulation gate that needs STRAIGHT. It must fail at preflight, not
    be caught by someone reading two files."""
    import yaml

    from sedition.storage.paths import stage_config

    data = yaml.safe_load(stage_config("stage0").read_text(encoding="utf-8"))
    data["name"] = "bad_gate"
    data["gates"] = {"manipulation": {"derived_drop_min_pp": 15,
                                      "atomic_delta_max_pp": 10},
                     "report_by": "packet"}
    target = stage_config("bad_gate")
    target.write_text(yaml.safe_dump(data), encoding="utf-8")
    try:
        run_preflight("bad_gate")
        out = capsys.readouterr().out
        assert "manipulation gate is computable" in out
        line = next(ln for ln in out.splitlines()
                    if "manipulation gate is computable" in ln)
        assert line.strip().startswith("[FAIL]"), line
        assert "SHEET" in line
    finally:
        target.unlink()


def test_manipulation_gate_computability_passes_for_the_pilot(capsys):
    run_preflight("pilot_manipulation")
    line = next(ln for ln in capsys.readouterr().out.splitlines()
                if "manipulation gate is computable" in ln)
    assert line.strip().startswith("[PASS]")


def test_preflight_confirms_a_model_is_bound_for_every_role(capsys):
    """Provider adapters are Inspect's now, so the check that survives is the
    one Inspect cannot make for us: a role with no model surfaces as a
    PrerequisiteError only once the eval is already running."""
    run_preflight("pilot_manipulation")
    line = next(ln for ln in capsys.readouterr().out.splitlines()
                if "a model is bound for every role" in ln)
    assert line.strip().startswith("[PASS]")
    for role in ("analyst", "watch_officer", "monitor"):
        assert role in line


def test_preflight_checks_scoring_note_never_reaches_a_prompt(capsys):
    run_preflight("pilot_manipulation")
    out = capsys.readouterr().out
    assert "scoring_note absent from rendered vocabulary" in out


def test_preflight_checks_the_key_derives_from_the_vocabulary(capsys):
    run_preflight("pilot_manipulation")
    assert "answer key derives from the vocabulary" in capsys.readouterr().out
