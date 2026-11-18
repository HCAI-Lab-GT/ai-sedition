"""Notification-standard lookup and blind-assessor schema contracts."""
from __future__ import annotations

import re

import pytest
from inspect_ai.util import json_schema

from sedition_inspect._resources import scenarios
from sedition_inspect._schema import BlindAssessorOutput, WatchOfficerDecision
from sedition_inspect.overrides import (
    _SECTION_2,
    STANDARDS_DIR,
    _standard_path,
    apply_standard,
    standard_section2,
)

EVENTS = ("E01", "E02", "E03")

def _criteria(section2: str) -> dict[str, str]:
    out = {}
    for line in section2.strip().split("\n"):
        m = re.match(r"Criterion ([ABC]) — ", line)
        if m:
            out[m.group(1)] = line
    assert set(out) == {"A", "B", "C"}, f"expected A, B, C; got {sorted(out)}"
    return out


def _opener(section2: str) -> str:
    return section2.strip().split("\n")[0]


def _scenario_section2(eid: str) -> str:
    sc = scenarios()[eid]
    return _SECTION_2.search(sc.notification_standard).group(0)


# ---------------------------------------------------------------- lookup

def test_the_scoped_lookup_mechanism_is_intact_even_though_nothing_uses_it():
    """`_standard_path` still prefers `{name}.{event}.md` over `{name}.md`.

    No scoped file exists any more, so `event_id` currently changes nothing.
    The mechanism is kept rather than deleted so a per-event standard authored
    against the packets now on disk resolves the same way it always did.
    """
    assert not list(STANDARDS_DIR.glob("*.E0[123].md")), (
        "a scoped standard reappeared; add its review and behavior tests")
    generic = _standard_path("notification_standard_v3_relational", "E01")
    assert generic.name == "notification_standard_v3_relational.md"
    assert standard_section2("notification_standard_v3_relational", event_id="E02") \
        == standard_section2("notification_standard_v3_relational")


def test_existing_generic_callers_are_unaffected():
    """`apply_standard` with a generic variant renders exactly as before the
    per-scenario lookup existed."""
    sc = scenarios()["E03"]
    swapped = apply_standard(sc, "notification_standard_v3_relational").notification_standard
    assert standard_section2("notification_standard_v3_relational") in swapped


# ------------------------------------------- released packet standards

@pytest.mark.parametrize("eid", EVENTS)
def test_each_released_packet_states_all_three_criteria(eid):
    """The structural precondition any future per-event standard needs.

    A v6-style variant edits one criterion and carries the other two verbatim,
    so it needs three parseable `Criterion X — ` lines to carry. This is what
    survives of the old per-event tests: the shape, not the content.
    """
    assert set(_criteria(_scenario_section2(eid))) == {"A", "B", "C"}


def test_all_three_released_packets_carry_the_threshold_sentence():
    """All scenario standards use the same any-one threshold semantics."""
    for eid in EVENTS:
        assert "any one of the following" in _opener(_scenario_section2(eid)).lower(), (
            f"{eid} lost its threshold sentence")

# ------------------------------------------------ blind assessor schema

def test_blind_assessor_schema_carries_no_decision_fields():
    blind = json_schema(BlindAssessorOutput)
    unified = json_schema(WatchOfficerDecision)
    assert set(blind.properties) == {"criteria_assessment"}
    assert "decision" in unified.properties and "decision_probabilities" in unified.properties
