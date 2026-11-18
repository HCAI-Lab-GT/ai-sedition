"""Typed stage config: validates on load, and every locked invariant that can
be checked statically refuses the config rather than warning."""
import pytest
import yaml
from pydantic import ValidationError

from sedition.config.schema import Budgets, load_stage
from sedition.enums import Cell, WorkingCondition
from sedition.storage.paths import stage_config

STAGE0 = stage_config("stage0")
PILOT = stage_config("pilot_manipulation")


def _write_variant(tmp_path, mutate):
    data = yaml.safe_load(STAGE0.read_text(encoding="utf-8"))
    mutate(data)
    p = tmp_path / "variant.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_stage0_is_the_90_episode_core():
    config = load_stage(STAGE0)
    assert config.cells == (Cell.HONEST_SHEET, Cell.BASIC_SHEET, Cell.STRATEGIC_SHEET)
    assert config.blocks == 5
    assert config.episode_count == 90
    assert config.is_sheet_only()
    assert config.provider.allow_real_calls is False
    assert config.source_sha256


def test_manipulation_pilot_carries_the_straight_cell_stage0_lacks():
    """The pilot exists because the manipulation gate needs honest x STRAIGHT,
    which stage0 has not got — and a gate that runs after the saboteur budget
    is spent is not a gate. See DECISIONS.md #12."""
    pilot = load_stage(PILOT)
    assert Cell.HONEST_STRAIGHT in pilot.cells
    assert not pilot.is_sheet_only()
    assert pilot.episode_count == 36
    # same seed as stage0, so shared blocks stay comparable
    assert pilot.master_seed == load_stage(STAGE0).master_seed


def test_public_budgets_matched_across_working_conditions():
    b = load_stage(STAGE0).budgets
    assert b.max_output_tokens("STRAIGHT", "briefing") == b.briefing_max_tokens
    assert (b.max_output_tokens("SHEET", "briefing")
            == b.briefing_max_tokens + b.sheet_allowance_tokens)
    assert b.max_output_tokens("STRAIGHT", "clarification") == b.clarification_max_tokens
    b.assert_public_budgets_matched()  # raises if not


def test_mismatched_public_budget_fails_the_run_not_warns():
    """If these ever diverge, part of the working-condition comparison is
    output length rather than procedure."""
    class _Skewed(Budgets):
        def max_output_tokens(self, working_condition: str, turn: str) -> int:
            if working_condition == "STRAIGHT" and turn == "briefing":
                return self.briefing_max_tokens - 500   # STRAIGHT shortchanged
            return super().max_output_tokens(working_condition, turn)

    skewed = _Skewed(briefing_max_tokens=2600, sheet_allowance_tokens=1800,
                     clarification_max_tokens=700, clarification_check_allowance_tokens=500,
                     briefing_word_budget=1300)
    with pytest.raises(ValueError, match="differs between SHEET and STRAIGHT"):
        skewed.assert_public_budgets_matched()


def test_unknown_cell_rejected(tmp_path):
    p = _write_variant(tmp_path, lambda d: d.update(cells=["overloaded_honest"]))
    with pytest.raises(ValidationError):
        load_stage(p)


def test_duplicate_cells_rejected(tmp_path):
    p = _write_variant(tmp_path, lambda d: d.update(cells=["honest_sheet", "honest_sheet"]))
    with pytest.raises(ValidationError, match="duplicate"):
        load_stage(p)


def test_unknown_key_rejected(tmp_path):
    """extra='forbid': a typo'd key fails at load with a field name, not
    three modules later with a silent default."""
    p = _write_variant(tmp_path, lambda d: d.update(blockz=5))
    with pytest.raises(ValidationError):
        load_stage(p)


def test_malformed_private_policy_locked(tmp_path):
    p = _write_variant(tmp_path,
                       lambda d: d["failure_policy"].update(malformed_private_output="retry_once"))
    with pytest.raises(ValidationError, match="invalid_no_retry"):
        load_stage(p)


def test_drop_not_replace_locked(tmp_path):
    p = _write_variant(tmp_path,
                       lambda d: d["failure_policy"].update(replace_dropped_episodes=True))
    with pytest.raises(ValidationError, match="must be false"):
        load_stage(p)


def test_models_must_define_all_three_roles(tmp_path):
    p = _write_variant(tmp_path, lambda d: d["models"].pop("monitor"))
    with pytest.raises(ValidationError, match="analyst, watch_officer, monitor"):
        load_stage(p)


def test_cells_expose_their_factors():
    assert Cell.HONEST_STRAIGHT.policy.value == "honest"
    assert Cell.HONEST_STRAIGHT.working_condition is WorkingCondition.STRAIGHT
    assert not Cell.HONEST_STRAIGHT.has_hidden_objective
    assert Cell.STRATEGIC_SHEET.has_hidden_objective


def test_real_calls_still_gated_in_config():
    """The provider-side lock went with sedition/providers/ — Inspect owns
    model access now. The config-side lock is the half that survives, and it
    is the half the preregistration records (DECISIONS.md #10)."""
    config = load_stage(STAGE0)
    assert config.provider.allow_real_calls is False
