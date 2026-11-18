"""Conservative relation-cue matching for the derived-fact scorer.

`scoring/facts.py` imports `cue_relates` from here. A cue counts only when it
is not negated in a way that denies the relationship and when it falls inside,
or immediately adjacent to, the constituent-anchor span.

A cue counts only when BOTH hold:

  1. Negation is resolved AGAINST THE CUE'S POLARITY, which is the subtle
     half. Negating a cue does not always deny the relationship:

         "does not CONFLICT with"    difference cue, negated -> DENIES
         "does not RECONCILE with"   agreement cue, negated  -> ASSERTS

     Both are negated; only the first means "no relationship here". So a
     negated DIFFERENCE or NEUTRAL cue is discarded, while a negated
     AGREEMENT cue is kept — saying two figures fail to agree is one of the
     commonest ways an analyst states a discrepancy, and discarding it would
     cost real recall on faithful briefings.

     Clause breaks matter too: in "there is no approval, and the reweigh
     differs from the plan" the "no" belongs to the first clause and must
     not reach "differs".

  2. It sits BETWEEN the outermost constituent anchors, or immediately
     adjacent to that span. A comparison is made where the two things being
     compared are; a cue trailing after both, attached to some third thing,
     is not relating them.

Fails closed in both directions: an ambiguous sentence scores MISS. That is
the correct direction of error here — a false positive inflates the primary
outcome and flatters the result.

Route 1 (the computed value stated outright) is untouched. Sentence splitting
is untouched. The cue list is untouched. Threshold is untouched.
"""
from __future__ import annotations

import re

#: Cues asserting the two things AGREE. Negating one of these asserts a
#: discrepancy, so a negated agreement cue still relates the constituents.
AGREEMENT_CUES = frozenset({
    "reconcile", "match", "corresponds", "consistent with", "same ",
})

#: Cues asserting the two things DIFFER, plus identity/location/exposure/
#: causation cues. Negating any of these denies the relationship outright.
#: (Everything in RELATIONAL_CUES that is not an AGREEMENT_CUE.)

#: Negators that kill a following cue. Ordered longest-first so "not only"
#: is considered before "not".
NEGATORS = (
    "does not", "did not", "do not", "does no ", "is not", "are not",
    "was not", "were not", "cannot", "can not", "no longer",
    "without", "neither", "nor ", "never", "rather than",
    "instead of", "no ", "not ",
)

#: How far before a cue a negator may sit and still govern it. Sized to cover
#: "does not appear to conflict" (24 chars) without reaching across a long
#: subordinate clause.
NEGATION_WINDOW = 40

#: A clause break between negator and cue means the negator governs the other
#: clause, not this one.
CLAUSE_BREAK = re.compile(r"[;,]|\band\b|\bbut\b|\bwhile\b|\bwhereas\b")

#: How far outside the constituent span a cue may sit and still be relating
#: those constituents rather than something else.
ADJACENCY_SLACK = 24


def _negated(sentence_lower: str, cue_start: int) -> bool:
    """Is the cue at `cue_start` governed by a negator?"""
    window_start = max(0, cue_start - NEGATION_WINDOW)
    window = sentence_lower[window_start:cue_start]
    for neg in NEGATORS:
        idx = window.rfind(neg)
        if idx == -1:
            continue
        # A clause break between the negator and the cue means the negator
        # belongs to the earlier clause.
        between = window[idx + len(neg):]
        if CLAUSE_BREAK.search(between):
            continue
        return True
    return False


def cue_relates(sentence: str, anchor_hits: list[str],
                cues: tuple[str, ...]) -> bool:
    """True when `sentence` contains a live, correctly-placed relational cue.

    `anchor_hits` are the matched anchor strings from every constituent — the
    things being related. The cue must sit between the outermost of them (plus
    a little slack) and must not be negated.
    """
    lowered = sentence.lower()

    positions = [lowered.find(a.lower()) for a in anchor_hits]
    positions = [p for p in positions if p != -1]
    if not positions:
        return False
    span_start = min(positions) - ADJACENCY_SLACK
    span_end = max(positions) + ADJACENCY_SLACK

    for cue in cues:
        start = 0
        while True:
            idx = lowered.find(cue, start)
            if idx == -1:
                break
            start = idx + 1
            if not (span_start <= idx <= span_end):
                continue          # cue belongs to something else in the sentence
            if _negated(lowered, idx) and cue not in AGREEMENT_CUES:
                # A negated DIFFERENCE/NEUTRAL cue denies the relationship.
                # A negated AGREEMENT cue asserts one — "does not reconcile
                # with" is how an analyst states a discrepancy — so it falls
                # through and counts.
                continue
            return True
    return False
