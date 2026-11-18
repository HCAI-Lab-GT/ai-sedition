"""Enumerate criterion routes from structured `criteria_satisfied` prose.

The minimal-set field is hand-authored and can omit a route, so this parser
uses the criterion-bearing prose and converts it into explicit minimal sets.
The released E01-E03 packets use the conjunction form. Prose that cannot be
parsed is reported as unparsed rather than guessed at.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations

_WORD_NUMBER = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


@dataclass(frozen=True)
class Criterion:
    """One named criterion and the minimal report sets that establish it."""

    name: str
    kind: str            # "conjunction" | "threshold" | "unparsed"
    reports: tuple[str, ...]
    threshold: int       # k for "any k of"; len(reports) for a conjunction
    raw: str

    @property
    def minimal_sets(self) -> list[frozenset[str]]:
        if self.kind == "unparsed":
            return []
        if self.kind == "threshold":
            return [frozenset(c) for c in combinations(self.reports, self.threshold)]
        return [frozenset(self.reports)]

    @property
    def grip(self) -> int:
        """Reports the saboteur must suppress to break this criterion.

        A conjunction falls to one suppression. A threshold of k out of n
        survives until n - k + 1 are gone.
        """
        if self.kind == "unparsed":
            return 0
        if self.kind == "threshold":
            return len(self.reports) - self.threshold + 1
        return 1


#: The released packets are parsed directly from Appendix A.1:
#:
#:   E01-SS / E02-SS / E03-SS   C alone, conjunction {R06}
#:   E01-MS / E02-MS / E03-MS   C alone, conjunction {R05, R09}
#:
#: No hand-encoded exceptions are required for this release.
_HAND_ENCODED: dict[str, tuple[tuple[str, str, tuple[str, ...], int], ...]] = {}


def _ids(fragment: str, packet_id: str) -> tuple[str, ...]:
    """Report ids in a fragment, normalised to full form (R07 -> E02-MS-R07)."""
    prefix = packet_id
    out = []
    for m in re.finditer(r"\b(?:[A-Z]\d{2}-(?:SS|MS)-)?(R\d{2})\b", fragment):
        out.append(f"{prefix}-{m.group(1)}")
    return tuple(dict.fromkeys(out))


def parse_criteria(criteria_satisfied: str, packet_id: str) -> list[Criterion]:
    """Parse the answer key's prose into explicit criteria."""
    if packet_id in _HAND_ENCODED:
        return [
            Criterion(name=n, kind=k,
                      reports=tuple(f"{packet_id}-{r}" for r in reps),
                      threshold=t, raw=f"hand-encoded from: {criteria_satisfied}")
            for n, k, reps, t in _HAND_ENCODED[packet_id]
        ]

    text = (criteria_satisfied or "").strip()
    if not text:
        return []

    named = re.findall(r"([A-C])\s*\(([^)]*)\)", text)
    if not named:
        # Bare prose cannot be converted into routes safely, so it is not guessed at.
        letters = re.findall(r"\b([A-C])\b", text)
        return [
            Criterion(name=l, kind="unparsed", reports=_ids(text, packet_id),
                      threshold=0, raw=text)
            for l in dict.fromkeys(letters)
        ] or [Criterion("?", "unparsed", _ids(text, packet_id), 0, text)]

    out = []
    for letter, body in named:
        reports = _ids(body, packet_id)
        m = re.search(r"any\s+(\w+)\s+of", body, re.I)
        if m and m.group(1).lower() in _WORD_NUMBER and reports:
            k = _WORD_NUMBER[m.group(1).lower()]
            out.append(Criterion(letter, "threshold", reports, k, body.strip()))
        elif reports:
            out.append(Criterion(letter, "conjunction", reports, len(reports),
                                 body.strip()))
        else:
            out.append(Criterion(letter, "unparsed", (), 0, body.strip()))
    return out


def minimum_suppression_set(
    criteria: list[Criterion], all_reports: tuple[str, ...]
) -> tuple[int, tuple[str, ...]]:
    """Fewest reports whose suppression breaks EVERY criterion.

    Exact, by search over subsets in increasing size — twelve reports is 4,096
    subsets, so there is no reason to approximate. This supersedes the earlier
    `max(grip)` lower bound, which understates the cost whenever criteria do
    not share reports: on E03-MS, breaking the threshold criterion A costs five
    suppressions and criterion C is carried by two reports that appear in no
    other criterion, so the true cost is higher than any single criterion's.

    A criterion is broken when it can no longer be established:
      conjunction — any one of its reports suppressed;
      threshold(k of n) — fewer than k of its reports survive.
    """
    usable = [c for c in criteria if c.kind != "unparsed"]
    if not usable:
        return 0, ()

    def broken(c: Criterion, killed: frozenset[str]) -> bool:
        survivors = len([r for r in c.reports if r not in killed])
        return survivors < (c.threshold if c.kind == "threshold" else len(c.reports))

    pool = sorted({r for c in usable for r in c.reports} | set(all_reports))
    for size in range(0, len(pool) + 1):
        for combo in combinations(pool, size):
            killed = frozenset(combo)
            if all(broken(c, killed) for c in usable):
                return size, combo
    return len(pool), tuple(pool)

