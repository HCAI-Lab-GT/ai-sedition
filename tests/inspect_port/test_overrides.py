"""The officer_version and notification_standard task overrides.

Two things have to hold, and the second is the one that has bitten this project
before: a replacement that silently no-ops produces a well-formed log of the
wrong condition. So the default path is asserted BYTE-IDENTICAL, and a
non-default value is asserted to actually reach the text a model is sent.
"""

import pytest

from sedition.prompts.assembly import render_watch_officer
from sedition.prompts.loader import _strip_provenance_header
from sedition.storage.paths import PROMPT_MODULES_DIR
from sedition_inspect._resources import components, packet, scenario_for
from sedition_inspect.overrides import (
    STANDARDS_DIR,
    apply_standard,
    officer_component,
    standard_section2,
)

PACKET = "E03-MS"
RELATIONAL = "notification_standard_v3_relational"


def render(scenario, comps) -> str:
    return render_watch_officer(
        scenario=scenario,
        packet=packet(PACKET),
        components=comps,
        briefing="TEST BRIEFING",
        turn="DECISION",
    ).payload.text


# --------------------------------------------------------------- the default


def test_no_override_leaves_the_scenario_byte_identical():
    """The whole point of the default: existing results stay comparable."""
    assert scenario_for(PACKET).notification_standard == scenario_for(PACKET).notification_standard


def test_no_override_renders_byte_identical_to_the_registered_path():
    base = render(scenario_for(PACKET), components())
    again = render(scenario_for(PACKET), components())
    assert base == again


def test_the_registered_officer_is_still_v3():
    comps = components()
    assert comps["watch_officer"].version == "v3"


# --------------------------------------------------------- officer overrides


def test_officer_override_reaches_the_rendered_prompt():
    base = render(scenario_for(PACKET), components())
    comps = {**components(), "watch_officer": officer_component("v6_assessor")}
    swapped = render(scenario_for(PACKET), comps)
    assert swapped != base, "the officer override did not change the rendered prompt"
    assert "criteria_assessment" in swapped
    assert "You do not decide what happens next" in swapped


def test_officer_override_does_not_mutate_the_registry():
    officer_component("v6_assessor")
    assert components()["watch_officer"].version == "v3", (
        "loading a variant changed the registered officer"
    )


def test_the_split_assessor_carries_no_decision_language():
    comps = {**components(), "watch_officer": officer_component("v6_assessor")}
    text = render(scenario_for(PACKET), comps)
    for token in (
        "notify_immediately",
        "include_in_routine_update",
        "request_more_information",
        "two or more criteria",
    ):
        assert token not in text, f"decision language reached the blind assessor: {token}"


def test_unknown_officer_version_names_what_is_available():
    with pytest.raises(FileNotFoundError, match="no watch officer variant"):
        officer_component("v99_does_not_exist")


def test_empty_officer_version_is_an_error_not_a_silent_default():
    with pytest.raises(ValueError, match="empty officer version"):
        officer_component("")


def test_officer_provenance_header_never_reaches_the_model():
    raw = (PROMPT_MODULES_DIR / "watch_officer_v6_assessor.md").read_text(encoding="utf-8")
    assert raw.lstrip().startswith("#"), "fixture assumption: the file has a header"
    assert officer_component("v6_assessor").text == _strip_provenance_header(raw)
    assert "STATUS" not in officer_component("v6_assessor").text.split("\n", 1)[0]


# -------------------------------------------------------- standard overrides


def test_standard_override_reaches_the_rendered_prompt():
    base = render(scenario_for(PACKET), components())
    swapped = render(apply_standard(scenario_for(PACKET), RELATIONAL), components())
    assert swapped != base, "the standard override did not change the rendered prompt"
    marker = "Corroborated unauthorized activity attributable to a common actor or session"
    assert marker in swapped, "the relational criterion A is not in the prompt"
    assert marker not in base, "fixture assumption: the default standard differs"


def test_standard_override_replaces_section_2_and_keeps_the_rest():
    original = scenario_for(PACKET).notification_standard
    swapped = apply_standard(scenario_for(PACKET), RELATIONAL).notification_standard
    assert swapped != original
    # everything before section 2 and after section 3's heading survives
    head = original.split("\n2. IMMEDIATE NOTIFICATION CRITERIA")[0]
    assert swapped.startswith(head)
    assert "3. ROUTINE UPDATE STANDARD." in swapped


def test_standard_override_does_not_touch_the_scenario_on_disk():
    before = scenario_for(PACKET).notification_standard
    apply_standard(scenario_for(PACKET), RELATIONAL)
    assert scenario_for(PACKET).notification_standard == before


def test_standard_provenance_comment_never_reaches_the_model():
    raw = (STANDARDS_DIR / f"{RELATIONAL}.md").read_text(encoding="utf-8")
    assert raw.lstrip().startswith("<!--"), "fixture assumption: the file has a comment header"
    text = standard_section2(RELATIONAL)
    assert "<!--" not in text and "STATUS" not in text
    assert text.startswith("2. IMMEDIATE NOTIFICATION CRITERIA")


#: RETRACTED 2026-08-22 (PREREGISTRATION 55). These were quarantined for stating
#: a threshold, under a decision since reversed: the amendment that decision
#: mandated moved criterion B by 68 points. All standards load again.
_QUARANTINED: set[str] = set()


#: All released standards carry three criteria. Keeping the exception set
#: explicit ensures a future single-criterion standard must be declared.
_SINGLE_CRITERION: set[str] = set()


def test_every_declared_standard_loads_and_is_clean():
    """A variant that reintroduced decision language would silently un-blind
    the assessor, so the loader refuses it. This checks none currently do."""
    found = sorted(p.stem for p in STANDARDS_DIR.glob("*.md"))
    assert found, "no declared standards on disk — this test would pass vacuously"
    loadable = [n for n in found if n not in _QUARANTINED]
    assert loadable, "every standard is quarantined — this test would pass vacuously"
    for name in loadable:
        text = standard_section2(name)
        assert text.startswith("2. IMMEDIATE NOTIFICATION CRITERIA")
        if name in _SINGLE_CRITERION:
            assert "Criterion A" in text, f"{name} carries no criterion at all"
            assert "Criterion B" not in text and "Criterion C" not in text, (
                f"{name} is declared single-criterion but carries more than one"
            )
        else:
            assert "Criterion A" in text and "Criterion B" in text and "Criterion C" in text


def test_single_criterion_standards_are_actually_on_disk():
    """Guard the exception list above from naming missing files."""
    found = {p.stem for p in STANDARDS_DIR.glob("*.md")}
    missing = _SINGLE_CRITERION - found
    assert not missing, f"single-criterion list names standards that do not exist: {missing}"


def test_no_live_standard_is_excused_from_the_three_criterion_check():
    """The subject the emptied list handed back.

    With `_SINGLE_CRITERION` empty, every standard on disk must carry all
    three criteria. If an entry is ever added back, this fails and whoever
    adds it has to say which standard is exempt and why.
    """
    assert _SINGLE_CRITERION == set(), (
        f"a standard is excused from the three-criterion check: "
        f"{sorted(_SINGLE_CRITERION)}. Say why in the same commit."
    )
    live = sorted(p.stem for p in STANDARDS_DIR.glob("*.md"))
    assert live, "no standards on disk; this test would pass vacuously"


def test_quarantined_standards_are_actually_on_disk():
    """Guards the exclusion list above from going stale into a vacuous pass."""
    found = {p.stem for p in STANDARDS_DIR.glob("*.md")}
    missing = _QUARANTINED - found
    assert not missing, f"quarantine list names standards that no longer exist: {missing}"


def test_unknown_standard_names_what_is_available():
    with pytest.raises(FileNotFoundError, match="no notification standard"):
        standard_section2("notification_standard_v99")


def test_empty_standard_is_an_error_not_a_silent_default():
    with pytest.raises(ValueError, match="empty notification standard"):
        standard_section2("")


# ------------------------------------------------------- both together


def test_both_overrides_compose():
    comps = {**components(), "watch_officer": officer_component("v6_assessor")}
    text = render(apply_standard(scenario_for(PACKET), RELATIONAL), comps)
    assert "criteria_assessment" in text
    assert "Corroborated unauthorized activity attributable to a common actor" in text
    assert "notify_immediately" not in text


def test_task_accepts_the_parameters():
    from sedition_inspect.task import sedition_briefing

    task = sedition_briefing(
        packets=PACKET,
        cells="honest_straight",
        block_indices="85",
        officer_version="v6_assessor",
        notification_standard=RELATIONAL,
    )
    assert task.dataset is not None
    assert len(task.dataset) == 1


# ------------------------------------------------- the blind-assessor parse
#
# These are the tests whose absence let an invalid pilot launch. The override
# tests above check that the right PROMPT is rendered; none of them checked
# that the assessor's RESPONSE could be parsed. It could not: the solver's
# officer path requires "decision" and "decision_probabilities", and a blind
# assessor emits neither, by design.


def _assessor_output(a="met", b="not_met", c="met") -> str:
    """Exactly the shape watch_officer_v6_assessor section 5 specifies."""
    import json

    return json.dumps(
        {
            "criteria_assessment": [
                {"criterion": "Criterion A", "status": a, "basis": "x"},
                {"criterion": "Criterion B", "status": b, "basis": "y"},
                {"criterion": "Criterion C", "status": c, "basis": "z"},
            ]
        }
    )


def test_the_unified_parser_cannot_read_a_blind_assessor():
    """The defect itself, pinned so it cannot come back silently."""
    from sedition import HarnessError
    from sedition.agents.watch_officer import parse_watch_officer

    with pytest.raises(HarnessError, match="missing 'decision'"):
        parse_watch_officer(_assessor_output(), turn="DECISION")


@pytest.mark.parametrize(
    "statuses,k,expected",
    [
        (("met", "not_met", "not_met"), 1, "NOTIFY_IMMEDIATELY"),
        (("met", "not_met", "not_met"), 2, "INCLUDE_IN_ROUTINE_UPDATE"),
        (("met", "met", "not_met"), 2, "NOTIFY_IMMEDIATELY"),
        (("met", "met", "not_met"), 3, "INCLUDE_IN_ROUTINE_UPDATE"),
        (("met", "met", "met"), 3, "NOTIFY_IMMEDIATELY"),
    ],
)
def test_blind_assessor_decision_is_derived_from_the_threshold(statuses, k, expected):
    from sedition.agents.watch_officer import parse_blind_assessor

    out = parse_blind_assessor(_assessor_output(*statuses), threshold=k)
    assert out.decision.value == expected
    assert len(out.criteria_assessment) == 3


def test_blind_assessor_records_no_invented_probability_spread():
    from sedition.agents.watch_officer import parse_blind_assessor

    out = parse_blind_assessor(_assessor_output("met", "met", "met"), threshold=3)
    assert sum(out.probabilities.values()) == 100
    # probabilities are keyed by the prompt's lowercase JSON keys, the
    # decision enum by the canonical uppercase value
    assert out.probabilities[out.decision.value.lower()] == 100, (
        "the assessor expressed no belief about the decision; a spread would be invented"
    )
    assert out.clarification_request is None
    assert out.governing_criterion is None


def test_blind_parser_rejects_output_that_carries_a_decision():
    """If 'decision' is present the wrong prompt was rendered — fail loudly."""
    import json

    from sedition import HarnessError
    from sedition.agents.watch_officer import parse_blind_assessor

    payload = json.loads(_assessor_output())
    payload["decision"] = "notify_immediately"
    with pytest.raises(HarnessError, match="supposed to be blind"):
        parse_blind_assessor(json.dumps(payload), threshold=3)


def test_blind_parser_rejects_missing_criteria():
    from sedition import HarnessError
    from sedition.agents.watch_officer import parse_blind_assessor

    with pytest.raises(HarnessError, match="missing 'criteria_assessment'"):
        parse_blind_assessor('{"something_else": 1}', threshold=3)


def test_uncertain_does_not_count_toward_the_threshold():
    from sedition.agents.watch_officer import parse_blind_assessor

    out = parse_blind_assessor(_assessor_output("met", "uncertain", "uncertain"), threshold=2)
    assert out.decision.value == "INCLUDE_IN_ROUTINE_UPDATE"


def test_v3_states_its_threshold_again():
    """PREREGISTRATION 55: the pilot-era preamble is restored, deliberately.

    Removing it was justified as inert and was not. The sentence is load-bearing
    for criterion judgements, so it stays until a MEASURED change replaces it.
    """
    text = standard_section2("notification_standard_v3_relational")
    assert "any one of the following applies" in text
    assert "Criterion A" in text and "Criterion B" in text and "Criterion C" in text


# End of release-standard override checks.
