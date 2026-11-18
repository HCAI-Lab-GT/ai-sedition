"""The benign-error arm differs from the honest arm by MODEL ALONE.

The previous definition — honest analyst without the working sheet — was
perfectly confounded with the working-condition factor, which is now retired.
The replacement isolates capability by holding the instructions fixed, so the
thing that must be true is that the analyst prompt is byte-identical.

If this test ever fails, the arm has stopped measuring capability and started
measuring a prompt difference, which is the defect it was built to remove.
"""

import pytest

from sedition.enums import RETIRED_CELLS, RUNNABLE_CELLS, Cell, Policy, WorkingCondition
from sedition.pipeline.blocks import make_permutation
from sedition.prompts.assembly import render_analyst_briefing
from sedition_inspect._resources import (
    components, packet, scenario_for, target_slots,
)

PACKET = "E03-MS"
SEED = 20260814


def analyst_prompt(cell: Cell, block: int = 85) -> str:
    pk = packet(PACKET)
    return render_analyst_briefing(
        policy=cell.policy.value,
        working_condition=cell.working_condition.value,
        scenario=scenario_for(PACKET),
        packet=pk,
        permutation=make_permutation(pk.report_ids, SEED, "E03", "MS", block),
        components=components(),
        word_budget=1300,
        target=target_slots().get(PACKET),
    ).payload.text


# ------------------------------------------------------- the defining property


def test_benign_error_analyst_prompt_is_byte_identical_to_honest():
    """The whole point of the redefinition."""
    assert analyst_prompt(Cell.BENIGN_ERROR) == analyst_prompt(Cell.HONEST_STRAIGHT)


@pytest.mark.parametrize("block", [85, 90, 124])
def test_byte_identical_across_blocks(block: int):
    assert analyst_prompt(Cell.BENIGN_ERROR, block) == analyst_prompt(Cell.HONEST_STRAIGHT, block)


def test_benign_error_is_the_honest_policy_not_a_fourth_one():
    assert Cell.BENIGN_ERROR.policy is Policy.HONEST
    assert not Cell.BENIGN_ERROR.has_hidden_objective


def test_benign_error_differs_from_a_saboteur_prompt():
    """Guards against the identity test passing because rendering is broken."""
    assert analyst_prompt(Cell.BENIGN_ERROR) != analyst_prompt(Cell.BASIC_STRAIGHT)


# ------------------------------------------------------- the model is the diff


def test_the_benign_model_set_differs_from_frozen_only_in_the_analyst_seat():
    from sedition_inspect.run import MODEL_SETS

    base, benign = MODEL_SETS["foundry_deepseek_frozen"], MODEL_SETS["foundry_deepseek_benign"]
    assert set(base) == set(benign)
    differing = {r for r in base if base[r] != benign[r]}
    assert differing == {"analyst"}, f"expected only the analyst to differ, got {differing}"
    assert base["analyst"][0] == "azureai/DeepSeek-V4-Pro"
    assert benign["analyst"][0] == "azureai/DeepSeek-V3.2"


def test_the_frozen_temperatures_survive():
    """Analyst seats at 0.7, officer and monitor at 0.0."""
    from sedition_inspect.run import MODEL_SETS

    for name in ("foundry_deepseek_frozen", "foundry_deepseek_benign"):
        spec = MODEL_SETS[name]
        assert spec["analyst"][1] == 0.7, f"{name}: analyst must be 0.7"
        assert spec["watch_officer"][1] == 0.0, f"{name}: officer must be 0.0"
        assert spec["monitor"][1] == 0.0, f"{name}: monitor must be 0.0"


# --------------------------------------------------------------- SHEET retired


def test_sheet_cells_are_retired_not_runnable():
    assert set(RUNNABLE_CELLS) == {
        Cell.HONEST_STRAIGHT, Cell.BASIC_STRAIGHT,
        Cell.STRATEGIC_STRAIGHT,
        Cell.DEGRADED_STRAIGHT,
    }
    # BENIGN_ERROR joined the retired set on 2026-08-27: its preregistered
    # subset mechanism closed on 2026-08-26 and it was never in a committed
    # dataset. Retired, not deleted -- raw pilot logs deserialize to it.
    assert set(RETIRED_CELLS) == {
        Cell.HONEST_SHEET, Cell.BASIC_SHEET, Cell.STRATEGIC_SHEET,
        Cell.BENIGN_ERROR,
    }
    assert not set(RUNNABLE_CELLS) & set(RETIRED_CELLS)


def test_every_runnable_cell_is_straight():
    """The factor is retired, so no runnable cell varies it."""
    for c in RUNNABLE_CELLS:
        assert c.working_condition is WorkingCondition.STRAIGHT


def test_retired_cells_still_parse_so_stored_episodes_stay_readable():
    """Retired enum values remain parseable for compatibility with external records."""
    for value in ("honest_sheet", "basic_sheet", "strategic_sheet",
                  "benign_error"):
        assert Cell(value) in RETIRED_CELLS


def test_the_dropped_process_constraint_variant_is_gone():
    from sedition.storage.paths import PROMPT_MODULES_DIR

    assert not (PROMPT_MODULES_DIR / "degraded_analyst_v1.md").exists(), (
        "the process-constraint definition of benign error should be deleted"
    )


def test_the_working_sheet_module_is_kept_and_marked_retired():
    from sedition.storage.paths import PROMPT_MODULES_DIR

    p = PROMPT_MODULES_DIR / "working_sheet_v2.md"
    assert p.exists(), "the module is retired from scope, not deleted"
    assert "DROPPED FROM SCOPE" in p.read_text(encoding="utf-8")
