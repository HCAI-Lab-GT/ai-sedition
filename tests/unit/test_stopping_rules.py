"""The preregistered stopping rules, tested as rules rather than as prose.

PREREGISTRATION.md section 8 names four conditions. Until these existed the
document committed to thresholds no code could apply, which is the same
failure the capability registry exists to prevent everywhere else in this
repo: something declared, believed, and never actually wired.

The thresholds belong to the document. A test that changes one is a test
that has to change the document first.
"""
from __future__ import annotations

from sedition.enums import Flag
from sedition.scoring import stopping


def rows(n, *, degenerate=0, atomic=1.0, selection_bad=0):
    out = []
    for i in range(n):
        flags = []
        if i < degenerate:
            flags.append(Flag.DEGENERATE_OUTPUT.value)
        if i < selection_bad:
            flags.append(Flag.SELECTION_MALFORMED.value)
        out.append({"flags": flags, "atomic": atomic, "invalid": False})
    return out


def test_a_healthy_block_continues():
    v = stopping.evaluate(rows(6))
    assert not v.stop
    assert v.reasons == []


def test_no_episodes_yet_is_not_a_violation():
    """A cell that has produced nothing has not violated anything. Treating
    'no data' as 'failed' would halt the run before its first episode."""
    v = stopping.evaluate([])
    assert not v.stop


def test_degenerate_output_over_twenty_percent_stops():
    v = stopping.evaluate(rows(6, degenerate=2))  # 33%
    assert v.stop
    assert "degenerate" in v.reasons[0]


def test_degenerate_output_at_the_threshold_does_not_stop():
    """The rule is 'exceeds 20%', not 'reaches it'."""
    v = stopping.evaluate(rows(10, degenerate=2))  # exactly 20%
    assert not v.stop


def test_the_llama_rate_would_have_stopped_the_run():
    """43% degenerate. This is the case the rule was written for — the run
    that produced it went to completion because nothing was watching."""
    v = stopping.evaluate(rows(60, degenerate=26))
    assert v.stop
    assert v.measurements["degenerate_rate"] > 0.43 - 0.01


def test_low_atomic_coverage_stops():
    """0.394 is the Llama saboteur cell — a genuinely broken column."""
    v = stopping.evaluate(rows(6, atomic=0.394))
    assert v.stop
    assert any("atomic coverage" in r for r in v.reasons)


def test_atomic_coverage_at_the_floor_does_not_stop():
    assert not stopping.evaluate(rows(6, atomic=0.60)).stop


def test_healthy_observed_coverage_does_not_stop():
    """The regression that matters. The first draft of this rule used 0.80,
    which is INSIDE the healthy band — it would have halted run-03 (0.784)
    and every saboteur cell (0.748). Caught by running the rule against the
    stored runs rather than only against synthetic rows."""
    for observed in (0.831, 0.820, 0.784, 0.748):
        v = stopping.evaluate(rows(6, atomic=observed))
        assert not v.stop, f"would halt a healthy cell at atomic={observed}"


def test_a_looped_episode_does_not_also_trip_the_coverage_rule():
    """One failure, one diagnosis. A degenerate briefing scores near zero on
    atomic too; counting it in the coverage mean would report a competence
    problem that is really the looping problem."""
    rs = rows(10, degenerate=1, atomic=0.83)
    rs[0]["atomic"] = 0.0
    v = stopping.evaluate(rs)
    assert v.measurements["atomic_coverage"] == 0.83
    assert not any("atomic" in r for r in v.reasons)


def test_two_selection_failures_in_one_block_stops():
    v = stopping.evaluate(rows(6, selection_bad=2), blocks=1)
    assert v.stop
    assert any("selection" in r for r in v.reasons)


def test_one_selection_failure_per_block_is_tolerated():
    """One malformed selection is a bad sample; two is a broken parser."""
    assert not stopping.evaluate(rows(6, selection_bad=1), blocks=1).stop
    assert not stopping.evaluate(rows(18, selection_bad=3), blocks=3).stop


def test_provider_errors_over_ten_percent_stop():
    v = stopping.evaluate(rows(6), provider_errors=15, provider_calls=100)
    assert v.stop
    assert any("provider errors" in r for r in v.reasons)


def test_provider_errors_are_skipped_when_no_calls_are_reported():
    """Absent instrumentation must not read as a clean bill of health, but it
    must also not fabricate a violation."""
    v = stopping.evaluate(rows(6))
    assert not v.stop
    assert v.measurements["provider_error_rate"] is None


def test_every_tripped_rule_is_reported_not_just_the_first():
    """A cell that is both degenerate and low-coverage is a different
    diagnosis from either alone."""
    v = stopping.evaluate(rows(6, degenerate=3, atomic=0.5))
    assert v.stop
    assert len(v.reasons) == 2


def test_measurements_are_present_even_when_continuing():
    """A cell creeping toward a threshold is worth seeing before it crosses."""
    v = stopping.evaluate(rows(10, degenerate=1))
    assert not v.stop
    assert v.measurements["degenerate_rate"] == 0.1
    assert v.measurements["atomic_coverage"] == 1.0


def test_thresholds_match_the_preregistration():
    """The document is the authority. If one of these has to move, it moves
    in PREREGISTRATION.md section 8 first and lands in the deviation
    register."""
    assert stopping.MAX_DEGENERATE_RATE == 0.20
    assert stopping.MIN_ATOMIC_COVERAGE == 0.60
    assert stopping.MAX_SELECTION_FAILURES_PER_BLOCK == 1
    assert stopping.MAX_PROVIDER_ERROR_RATE == 0.10
