"""Prompt assembly: component loading, the F.2 composition matrix, golden
renders for all 18 core combinations, and a regression test confirming the
analyst payload boundary scanner accepts legitimate SHEET/saboteur content
(sheet delimiters, private-objective text) rather than rejecting it."""
from pathlib import Path

import pytest

from sedition import HarnessError, SpecViolationError
from sedition.config.schema import load_stage
from sedition.packets.build import parse_all
from sedition.prompts.assembly import (
    load_target_slots,
    render_analyst_briefing,
    render_strategic_selection,
    validate_rendered,
)
from sedition.prompts.loader import COMPONENT_FILES, load_all
from sedition.prompts.registry import PromptRegistry
from sedition.storage.paths import PROMPT_MODULES_DIR, SCENARIOS_DIR, TARGET_SLOTS, stage_config

ROOT = Path(__file__).resolve().parent.parent.parent
COMPONENTS_DIR = PROMPT_MODULES_DIR
CORE_CELLS = ("honest_sheet", "basic_sheet", "strategic_sheet")
CELL_POLICY = {"honest_sheet": "honest", "basic_sheet": "basic_saboteur",
               "strategic_sheet": "strategic_saboteur"}


@pytest.fixture(scope="module")
def packages():
    return parse_all(SCENARIOS_DIR)


@pytest.fixture(scope="module")
def components():
    return load_all(COMPONENTS_DIR, PromptRegistry())


@pytest.fixture(scope="module")
def targets():
    return load_target_slots(TARGET_SLOTS)


@pytest.fixture(scope="module")
def word_budget():
    return load_stage(stage_config("stage0")).budgets.briefing_word_budget


def test_all_ten_components_load(components):
    assert set(components) == set(COMPONENT_FILES)
    for name, component in components.items():
        assert component.text.strip(), f"{name} loaded empty"
        assert not component.text.lstrip().startswith("#"), (
            f"{name}: provenance header was not stripped")


def test_component_registry_is_immutable_once_registered(components):
    """Same name AND same version with different text must be refused.

    The version is read from COMPONENT_FILES rather than hardcoded: a
    hardcoded one silently stops testing anything the moment a module is
    bumped, because registering a *different* version is legitimate — that is
    exactly how a prompt change is supposed to be made.
    """
    registry = PromptRegistry()
    load_all(COMPONENTS_DIR, registry)
    from sedition.prompts.registry import PromptComponent

    current_version = COMPONENT_FILES["analyst_common"][0]
    with pytest.raises(HarnessError, match="require a NEW version"):
        registry.register(PromptComponent(name="analyst_common",
                                          version=current_version,
                                          text="different text"))


def test_registering_a_new_version_is_allowed(components):
    """The other half of the rule, which the immutability test alone does not
    cover: a bump must go through."""
    registry = PromptRegistry()
    load_all(COMPONENTS_DIR, registry)
    from sedition.prompts.registry import PromptComponent

    registry.register(PromptComponent(name="analyst_common", version="v999",
                                      text="a future revision"))


@pytest.mark.parametrize("event_id", ["E01", "E02", "E03"])
@pytest.mark.parametrize("version", ["SS", "MS"])
@pytest.mark.parametrize("cell_id", CORE_CELLS)
def test_all_18_core_combinations_render(packages, components, targets, word_budget,
                                         event_id, version, cell_id):
    """The M2 gate: every core (packet x SHEET cell) combination must render
    with real content — not skip, not stub."""
    pkg = packages[event_id]
    packet_id = f"{event_id}-{version}"
    packet = pkg.packets[packet_id]
    policy = CELL_POLICY[cell_id]
    target = targets[packet_id] if policy != "honest" else None

    call = render_analyst_briefing(
        policy=policy, working_condition="SHEET", scenario=pkg, packet=packet,
        permutation=packet.report_ids, components=components,
        word_budget=word_budget, target=target,
    )
    assert "{{" not in call.payload.text
    assert "APPENDIX A" not in call.payload.text
    validate_rendered(call.payload.text, packet)  # exact-once per report block


@pytest.mark.parametrize("packet_id", ["E01-SS", "E01-MS", "E02-SS", "E02-MS", "E03-SS", "E03-MS"])
def test_strategic_selection_renders_for_every_packet(packages, components, targets, packet_id):
    event_id = packet_id.split("-")[0]
    pkg = packages[event_id]
    packet = pkg.packets[packet_id]
    call = render_strategic_selection(
        scenario=pkg, packet=packet, permutation=packet.report_ids,
        components=components, target=targets[packet_id],
    )
    assert "{{" not in call.payload.text
    assert "APPENDIX A" not in call.payload.text
    # Only §§1,2,3,4,5,7 of analyst_common are excerpted — §6/§8/§9 excluded.
    assert "6. Briefing format" not in call.payload.text
    assert "8. Turn handling" not in call.payload.text
    assert "9. Clarification round" not in call.payload.text


def test_straight_condition_has_no_sheet_markers(packages, components, targets, word_budget):
    pkg = packages["E01"]
    packet = pkg.packets["E01-SS"]
    call = render_analyst_briefing(
        policy="honest", working_condition="STRAIGHT", scenario=pkg, packet=packet,
        permutation=packet.report_ids, components=components, word_budget=word_budget,
    )
    assert "=== WORKING SHEET ===" not in call.payload.text
    assert "=== CLARIFICATION CHECK ===" not in call.payload.text


def test_honest_sheet_and_strategic_abstain_are_byte_identical(packages, components, word_budget):
    """Part XII.8 Part E.3: ABSTAIN runs the briefing call as Honest —
    callers pass policy="honest"; there is no separate abstain assembly."""
    pkg = packages["E01"]
    packet = pkg.packets["E01-SS"]
    a = render_analyst_briefing(policy="honest", working_condition="SHEET", scenario=pkg,
                                packet=packet, permutation=packet.report_ids,
                                components=components, word_budget=word_budget)
    b = render_analyst_briefing(policy="honest", working_condition="SHEET", scenario=pkg,
                                packet=packet, permutation=packet.report_ids,
                                components=components, word_budget=word_budget)
    assert a.payload.text == b.payload.text


def test_bad_permutation_rejected(packages, components, word_budget):
    pkg = packages["E01"]
    packet = pkg.packets["E01-SS"]
    with pytest.raises(HarnessError, match="does not match this packet"):
        render_analyst_briefing(policy="honest", working_condition="SHEET", scenario=pkg,
                                packet=packet, permutation=("bogus",),
                                components=components, word_budget=word_budget)


def test_analyst_payload_accepts_legitimate_sheet_and_saboteur_content(packages, components, targets, word_budget):
    """Regression test: boundary.analyst_payload() must NOT reject the
    analyst's own real, assembled prompt — sheet delimiters and a
    saboteur's private-objective section are legitimate here, unlike for
    watch_officer_payload / monitor_payload."""
    pkg = packages["E01"]
    packet = pkg.packets["E01-MS"]
    call = render_analyst_briefing(
        policy="basic_saboteur", working_condition="SHEET", scenario=pkg, packet=packet,
        permutation=packet.report_ids, components=components, word_budget=word_budget,
        target=targets["E01-MS"],
    )
    assert "=== WORKING SHEET ===" in call.payload.text
    assert "Private working sheet (§E)" in call.payload.text or "Private objective" in call.payload.text
    assert call.payload.recipient == "analyst"


def test_missing_target_slots_for_saboteur_cell_leaves_unfilled_slot(packages, components, word_budget):
    """A saboteur cell rendered without target slots must fail the
    unfilled-slot assertion rather than silently ship a broken prompt."""
    pkg = packages["E01"]
    packet = pkg.packets["E01-SS"]
    with pytest.raises(SpecViolationError, match=r"\{\{"):
        render_analyst_briefing(policy="basic_saboteur", working_condition="SHEET", scenario=pkg,
                                packet=packet, permutation=packet.report_ids,
                                components=components, word_budget=word_budget, target=None)
