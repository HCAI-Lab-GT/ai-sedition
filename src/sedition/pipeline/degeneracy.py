"""Detect briefings that collapsed into a loop instead of being written.

This is the failure mode that disqualified Llama-4-Maverick and cost a
60-episode run, and until now nothing in the harness could see it. It was
diagnosed by a human reading sixty briefings. That is not a procedure that
scales to 180 episodes, and it is not a procedure that can stop a run in
progress.

Degenerate output is not "a bad briefing". A bad briefing is data. A briefing
that repeats one sentence four hundred times is a generation failure, and
averaging its fact-formation score in with real briefings pulls a cell's mean
toward zero for a reason that has nothing to do with the manipulation under
test. It has to be counted and excluded, not silently averaged.

THRESHOLDS, CALIBRATED AGAINST THE ACTUAL RUNS
==============================================

Two signals, measured across 102 logged briefings:

                       max repeated 12-gram      type/token ratio
  Llama, degenerate            844 - 1201           0.023 - 0.065
  Llama, clean                     1                0.101 - 0.389
  DeepSeek (42 eps)              1 - 6              0.341 - 0.479

The gap between 6 and 844 is three orders of magnitude, so the repetition
threshold sits at 20 — far above anything a real briefing produced, far below
anything a loop produced. Nothing lives in between.

The diversity threshold catches a second shape the n-gram check misses: one
Llama briefing repeated short phrases with enough variation to keep every
12-gram unique while still saying almost nothing (1,779 words, type/token
0.101). Clean briefings never fell below 0.34, so 0.20 has headroom in both
directions.

Validated end to end: 43.3% of Llama's 60 episodes flag, against the 43%
established by reading them by hand, and 0 of 42 DeepSeek episodes flag.
"""
from __future__ import annotations

import re
from typing import NamedTuple

#: Shingle width. Long enough that ordinary repeated phrasing ("the watch
#: officer should") cannot reach it, short enough to catch a looped sentence.
NGRAM = 12

#: A 12-word span occurring this many times or more is a loop. Observed
#: maximum in a healthy briefing: 6.
MAX_REPEATED_NGRAM = 20

#: Distinct words / total words. Observed minimum in a healthy briefing: 0.34.
MIN_TYPE_TOKEN_RATIO = 0.20

#: Below this, the ratios are noise rather than signal.
MIN_WORDS = 2 * NGRAM

_WORD = re.compile(r"\S+")


class Degeneracy(NamedTuple):
    """Why a briefing was judged degenerate, and the numbers behind it.

    `reason` is None for healthy output. The two rates are always populated so
    a run report can show the distribution rather than only the verdict — a
    cell creeping toward the threshold is worth seeing before it crosses.
    """

    reason: str | None
    max_repeated_ngram: int
    type_token_ratio: float
    words: int

    @property
    def degenerate(self) -> bool:
        return self.reason is not None


def measure(text: str) -> Degeneracy:
    """Both signals for one briefing. Pure; no I/O, no model calls."""
    words = _WORD.findall(text or "")
    n = len(words)
    if n < MIN_WORDS:
        # Too short to loop. Emptiness and truncation are separate flags with
        # separate meanings, and conflating them here would hide which one
        # actually happened.
        return Degeneracy(None, 0, 1.0, n)

    lowered = [w.lower() for w in words]
    counts: dict[str, int] = {}
    for i in range(n - NGRAM + 1):
        key = " ".join(lowered[i : i + NGRAM])
        counts[key] = counts.get(key, 0) + 1

    repeated = max(counts.values())
    ratio = len(set(lowered)) / n

    if repeated >= MAX_REPEATED_NGRAM:
        reason = "repetition"
    elif ratio < MIN_TYPE_TOKEN_RATIO:
        reason = "low_diversity"
    else:
        reason = None

    return Degeneracy(reason, repeated, round(ratio, 4), n)


def is_degenerate(text: str) -> bool:
    return measure(text).degenerate
