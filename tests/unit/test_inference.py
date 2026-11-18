"""Cluster-aware inference, preregistered before the deep pilot ran.

The property under test is not "does it compute a p-value" but "does it
refuse to borrow strength from within-block repetition". Each test below
constructs a case where the naive answer and the block-aware answer differ,
and asserts the block-aware one.
"""
from __future__ import annotations

from sedition.scoring.inference import (
    block_bootstrap_ci,
    block_permutation_test,
    rate_of,
    rule_of_three,
)


def rows(spec):
    """spec: list of (block, group, hit)."""
    return [{"block": b, "overlay": g, "hit": h} for b, g, h in spec]


HIT = rate_of(lambda r: r["hit"])


def test_a_real_within_block_difference_is_detected():
    """Every block: v_current all miss, v_balanced all hit. The label carries
    the entire signal, so no within-block relabelling reproduces it."""
    spec = []
    for b in range(12):
        spec += [(b, "current", False), (b, "balanced", True)]
    r = block_permutation_test(rows(spec), group_key="overlay",
                               group_a="balanced", group_b="current",
                               statistic=HIT, n_permutations=2000)
    assert r.observed == 1.0
    assert r.p_value is not None and r.p_value < 0.01, r.report()


def test_no_difference_is_not_manufactured():
    """Same rate in both arms, varying by block. A test that returned a small
    p here would be inventing a contrast out of block-level variation."""
    spec = []
    for b in range(12):
        hit = b % 2 == 0            # varies by block, not by overlay
        spec += [(b, "current", hit), (b, "balanced", hit)]
    r = block_permutation_test(rows(spec), group_key="overlay",
                               group_a="balanced", group_b="current",
                               statistic=HIT, n_permutations=2000)
    assert r.observed == 0.0
    assert r.p_value is not None and r.p_value > 0.5, r.report()


def test_a_p_value_is_never_exactly_zero():
    """With N permutations the smallest defensible claim is 1/(N+1)."""
    spec = []
    for b in range(20):
        spec += [(b, "current", False), (b, "balanced", True)]
    r = block_permutation_test(rows(spec), group_key="overlay",
                               group_a="balanced", group_b="current",
                               statistic=HIT, n_permutations=500)
    assert r.p_value >= 1 / 501


def test_an_all_zero_statistic_refuses_rather_than_returning_p_equals_one():
    """The abstention case if nothing ever fires. p=1.0 would read as a
    finding of no difference; there is simply no information."""
    spec = [(b, g, False) for b in range(10) for g in ("current", "balanced")]
    r = block_permutation_test(rows(spec), group_key="overlay",
                               group_a="balanced", group_b="current",
                               statistic=HIT, n_permutations=200)
    assert r.p_value is None
    assert "rule_of_three" in r.note


def test_rule_of_three_bounds_a_zero_event_cell():
    assert rule_of_three(12) == 0.25
    assert abs(rule_of_three(25) - 0.12) < 1e-9
    assert rule_of_three(0) is None


def test_the_permutation_is_reproducible():
    """A p-value that moves between runs is not something a reader can
    check against the committed log."""
    spec = [(b, g, (b + (g == "balanced")) % 3 == 0)
            for b in range(15) for g in ("current", "balanced")]
    a = block_permutation_test(rows(spec), group_key="overlay",
                               group_a="balanced", group_b="current",
                               statistic=HIT, n_permutations=500)
    b = block_permutation_test(rows(spec), group_key="overlay",
                               group_a="balanced", group_b="current",
                               statistic=HIT, n_permutations=500)
    assert a.p_value == b.p_value


def test_block_bootstrap_resamples_blocks_not_episodes():
    """Twelve blocks, perfectly split within each. Resampling EPISODES would
    give a very tight interval; resampling BLOCKS must not, because every
    block carries the same information and there are only twelve of them."""
    spec = []
    for b in range(12):
        hit = b < 6
        spec += [(b, "current", hit)] * 10      # ten identical episodes
    r = block_bootstrap_ci(rows(spec), statistic=HIT, n_resamples=2000)
    assert abs(r.estimate - 0.5) < 1e-9
    assert r.n_blocks == 12
    # 120 independent episodes at p=0.5 would give roughly +-0.09.
    # Twelve blocks must give a visibly wider interval than that.
    assert (r.hi - r.lo) > 0.30, r.report()


def test_bootstrap_is_reproducible_too():
    spec = [(b, "current", b % 3 == 0) for b in range(15)]
    a = block_bootstrap_ci(rows(spec), statistic=HIT, n_resamples=400)
    b = block_bootstrap_ci(rows(spec), statistic=HIT, n_resamples=400)
    assert (a.lo, a.hi) == (b.lo, b.hi)
