"""Cluster-aware inference. Blocks are the clustering unit, not episodes.

Preregistered as THE inferential method for the primary contrasts before the
deep pilot ran. Naive standard errors may still be quoted, but only as
descriptive summary, and every table that shows one says so.

WHY BLOCKS
==========

Episodes inside a block share byte-identical reports in identical order. Two
episodes from the same block are not two independent draws on the question
"does this analyst form the relationship" — they are two draws conditioned on
the same twelve reports in the same sequence. Treating 750 episodes as 750
independent observations produces standard errors that are too small by
roughly the square root of the within-block correlation, and the error is in
the direction that makes every contrast look more significant than it is.

The permutation test below fixes the unit of resampling at the block, so a
p-value cannot borrow strength from within-block repetition.

WITHIN-BLOCK FACTORS ARE PERMUTED WITHIN BLOCK
==============================================

The overlay contrast (v_current vs v_balanced) is a WITHIN-block factor: both
variants run on the same 25 blocks against the same materials. Permuting the
label across the whole dataset would destroy that pairing and test a null
nobody proposed. `block_permutation_test` therefore flips the label
assignment inside each block independently, which is the null "the overlay
label is exchangeable within a block" — the one the design actually poses.

ZERO-EVENT CELLS
================

A permutation test on a statistic that is identically zero in every
permutation returns p=1.0 and means nothing. When either arm has no events,
report the rule-of-three bound instead: 0 events in n trials puts the 95%
upper bound at about 3/n. `rule_of_three` does that, and
`block_permutation_test` refuses rather than returning a meaningless p.
"""
from __future__ import annotations

import random
from collections import defaultdict
from typing import Callable, NamedTuple

#: Fixed so a reported p-value is reproducible from the committed log by the
#: documented command. A permutation p that moves between runs is not a
#: result anyone can check.
PERMUTATION_SEED = 20260814

DEFAULT_PERMUTATIONS = 10_000
DEFAULT_BOOTSTRAPS = 10_000


class PermutationResult(NamedTuple):
    observed: float | None
    p_value: float | None
    n_permutations: int
    n_blocks: int
    note: str

    def report(self) -> str:
        if self.p_value is None:
            return f"permutation test not applicable — {self.note}"
        return (f"observed difference {self.observed:+.4f}, "
                f"p = {self.p_value:.4f} "
                f"({self.n_permutations:,} block permutations over "
                f"{self.n_blocks} blocks)")


class BootstrapResult(NamedTuple):
    estimate: float | None
    lo: float | None
    hi: float | None
    n_blocks: int
    n_resamples: int

    def report(self) -> str:
        if self.estimate is None:
            return "block bootstrap not applicable — no data"
        return (f"{self.estimate:.4f}  95% CI [{self.lo:.4f}, {self.hi:.4f}] "
                f"(block bootstrap, {self.n_blocks} blocks, "
                f"{self.n_resamples:,} resamples)")


def _by_block(rows: list[dict], block_key: str) -> dict:
    out = defaultdict(list)
    for r in rows:
        out[r.get(block_key)].append(r)
    return dict(out)


def rule_of_three(n: int) -> float | None:
    """95% upper bound on a rate when zero events were observed in n trials.

    Not an estimate. It answers "how high could the true rate still be",
    which is the only honest thing to say about a cell that never fired.
    """
    return 3.0 / n if n else None


def block_permutation_test(
    rows: list[dict],
    *,
    group_key: str,
    group_a: str,
    group_b: str,
    statistic: Callable[[list[dict]], float | None],
    block_key: str = "block",
    n_permutations: int = DEFAULT_PERMUTATIONS,
    seed: int = PERMUTATION_SEED,
) -> PermutationResult:
    """Two-sided permutation test on `statistic(a) - statistic(b)`.

    Labels are shuffled WITHIN each block, so the test respects the pairing
    the design creates and never treats two episodes from one block as
    independent.
    """
    blocks = _by_block([r for r in rows if r.get(group_key) in (group_a, group_b)],
                       block_key)
    if not blocks:
        return PermutationResult(None, None, 0, 0, "no rows in either group")

    def diff(assignment: dict) -> float | None:
        a, b = [], []
        for blk, rs in blocks.items():
            for i, r in enumerate(rs):
                (a if assignment[(blk, i)] else b).append(r)
        sa, sb = statistic(a), statistic(b)
        return None if sa is None or sb is None else sa - sb

    truth = {(blk, i): (r.get(group_key) == group_a)
             for blk, rs in blocks.items() for i, r in enumerate(rs)}
    observed = diff(truth)
    if observed is None:
        return PermutationResult(None, None, 0, len(blocks),
                                 "a group had no scoreable rows")

    # A statistic that cannot move under relabelling carries no information;
    # returning p=1.0 would look like a finding of no difference.
    if all(statistic(rs) in (0.0, None) for rs in blocks.values()):
        return PermutationResult(
            observed, None, 0, len(blocks),
            "statistic is zero in every block — use rule_of_three instead")

    rng = random.Random(seed)
    at_least_as_extreme = 0
    for _ in range(n_permutations):
        shuffled = {}
        for blk, rs in blocks.items():
            labels = [truth[(blk, i)] for i in range(len(rs))]
            rng.shuffle(labels)
            for i, lab in enumerate(labels):
                shuffled[(blk, i)] = lab
        d = diff(shuffled)
        if d is not None and abs(d) >= abs(observed) - 1e-12:
            at_least_as_extreme += 1

    # +1/+1 so a p-value is never exactly zero: with N permutations the
    # smallest defensible claim is 1/(N+1).
    p = (at_least_as_extreme + 1) / (n_permutations + 1)
    return PermutationResult(observed, p, n_permutations, len(blocks),
                             "labels permuted within block")


def block_bootstrap_ci(
    rows: list[dict],
    *,
    statistic: Callable[[list[dict]], float | None],
    block_key: str = "block",
    n_resamples: int = DEFAULT_BOOTSTRAPS,
    seed: int = PERMUTATION_SEED,
    alpha: float = 0.05,
) -> BootstrapResult:
    """Percentile CI, resampling whole BLOCKS with replacement.

    Resampling episodes would treat within-block repetition as independent
    information and shrink the interval for a reason unrelated to evidence.
    """
    blocks = list(_by_block(rows, block_key).values())
    if not blocks:
        return BootstrapResult(None, None, None, 0, 0)
    point = statistic(rows)
    if point is None:
        return BootstrapResult(None, None, None, len(blocks), 0)

    rng = random.Random(seed)
    draws = []
    for _ in range(n_resamples):
        sample = []
        for _ in range(len(blocks)):
            sample.extend(rng.choice(blocks))
        s = statistic(sample)
        if s is not None:
            draws.append(s)
    if not draws:
        return BootstrapResult(point, None, None, len(blocks), 0)
    draws.sort()
    lo = draws[int((alpha / 2) * len(draws))]
    hi = draws[min(len(draws) - 1, int((1 - alpha / 2) * len(draws)))]
    return BootstrapResult(point, lo, hi, len(blocks), len(draws))


def rate_of(predicate: Callable[[dict], bool]) -> Callable[[list[dict]], float | None]:
    """Build a proportion statistic for the two functions above."""
    def stat(rs: list[dict]) -> float | None:
        if not rs:
            return None
        return sum(1 for r in rs if predicate(r)) / len(rs)
    return stat
