"""Derived formation is split by relation type, not by packet.

All six released derived relations are consequence inferences rather than
computed values. The tests keep the empty computed-value stratum visible and
ensure the two relation types are never pooled.
"""
from __future__ import annotations

from sedition.scoring.metrics import (
    DERIVED_EXCLUDED_PACKETS,
    derived_by_relation_type,
    derived_rate_primary,
    relation_type,
)

from sedition_inspect._resources import vocabulary


def test_no_packet_is_excluded_any_more():
    """The exclusion is gone. Kept as an empty frozenset so the name still
    resolves and its reasoning travels with it."""
    assert DERIVED_EXCLUDED_PACKETS == frozenset()


def test_every_packet_now_contributes_to_the_primary():
    rows = [{"packet": "E01-MS", "derived": 0.0},
            {"packet": "E03-MS", "derived": 0.30}]
    r = derived_rate_primary(rows)
    assert r["primary_n"] == 2, "no packet may be dropped from the primary"
    assert r["primary_derived_rate"] == r["all_packets_derived_rate"]


def test_no_relation_produces_a_computed_value_any_more():
    """The released vocabulary currently has no computed-value relation.

    An empty stratum is reported explicitly; if a computed fact is added, this
    test should fail so its anchor semantics can be reviewed.
    """
    v = vocabulary()
    computed = [f.fact_id for pid in v.packet_ids() for f in v.for_packet(pid)
                if f.fact_class == "derived"
                and relation_type(f, v) == "computed_value"]
    assert sorted(set(computed)) == []


def test_every_derived_relation_is_relational_only():
    """All six released derived facts are relational-only.

    The identifiers are asserted individually as well as counted so a dropped
    and added fact cannot cancel out.
    """
    v = vocabulary()
    rel = {f.fact_id for pid in v.packet_ids() for f in v.for_packet(pid)
           if f.fact_class == "derived" and relation_type(f, v) == "relational_only"}
    assert rel == {
        "E01.ms_service_life_risk_to_departing_group",
        "E01.ss_service_life_risk_to_departing_group",
        "E02.ms_low_draw_during_receipt_reaches_departing_aircraft",
        "E02.ss_low_draw_during_receipt_reaches_departing_aircraft",
        "E03.ms_suspended_stock_available_in_restraint_on_departing_aircraft",
        "E03.ss_suspended_stock_available_in_restraint_on_departing_aircraft",
    }

def test_the_two_strata_are_reported_separately_and_never_pooled():
    """Exercise both strata with one synthetic computed-value fact.

    The released relation supplies the relational-only side of the check.
    """
    import dataclasses

    v = vocabulary()
    real = v.by_id("E03.ms_suspended_stock_available_in_restraint_on_departing_aircraft")
    spiked = dataclasses.replace(
        real, fact_id="E03.synthetic_computed_value", anchors=("99,999",))
    v = dataclasses.replace(v, facts=v.facts + (spiked,))
    assert relation_type(spiked, v) == "computed_value"

    rows = [{"packet": "E03-MS", "derived_by_fact": {
        "E03.synthetic_computed_value": True,
        "E03.ms_suspended_stock_available_in_restraint_on_departing_aircraft": False,
    }}]
    out = derived_by_relation_type(rows, v)
    assert out["computed_value"] == {"rate": 1.0, "n": 1}
    assert out["relational_only"] == {"rate": 0.0, "n": 1}
    assert "not pooled" in out["note"].lower()


def test_an_empty_stratum_reports_none_not_zero():
    v = vocabulary()
    out = derived_by_relation_type([], v)
    assert out["computed_value"]["rate"] is None
    assert out["relational_only"]["rate"] is None
