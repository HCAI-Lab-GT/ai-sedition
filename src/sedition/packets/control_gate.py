"""Mechanical gate for control packet twins (PREREGISTRATION section 18.4).

A control twin is one of the six threat packets with its decisive elements
resolved, so the correct answer becomes routine update. Section 18.4 fixes two
conditions before any twin may be used:

  gate 1  no criterion is satisfiable from the control reports
  gate 2  near-miss material survives -- "a packet in which nothing happened is
          free to call routine and discriminates nothing"

Both are checked here without a model call, so a packet author can iterate
against a deterministic result instead of another agent round.

HOW THE GATES ARE DECIDED, AND WHY NO THRESHOLD IS INVENTED
-----------------------------------------------------------
A derived fact carries reviewer-authored `formation_groups`: conjunctive across
groups, disjunctive within. The fact forms only when every group is hit. That
supplies both gates directly, with no tuned constant:

  gate 1 fails when all of a fact's groups still hit -- the decisive relation
         survives the control transformation and the officer can still reach it
  gate 2 fails when none of a fact's groups hit -- the material is gone
         entirely, so the twin is a packet in which nothing happened

Measured against the six threat packets, every derived fact carries between 3
and 5 groups, so the band between the two gates is never empty. A twin that
removes exactly one group is a near miss by construction; removing more is
legal but weakens the discrimination the twin exists to provide, and is
reported as OVER_ABLATED rather than silently accepted.

A single-group derived fact could satisfy neither gate. None exists today; if
one is authored later this module refuses it explicitly rather than scoring it
as a pass.

SCOPE LIMIT -- WHAT THE FORMATION GATES DO NOT PROVE
-----------------------------------------------------
Section 18.4's gate 1 is "no CRITERION is satisfiable". What `_grade` checks is
"no derived RELATION forms". These are closely related and not identical, and
the difference matters in one direction that is easy to miss:

  deletion twins   -- material is removed. A relation that cannot form usually
                      takes its criterion with it, but the equivalence is not
                      proven, so `criterion_support()` below reports the
                      criterion picture separately rather than assuming it.

  resolution twins -- section 18.4 also permits the decisive elements to be
                      "resolved" rather than removed: the standard itself says
                      criterion A "is not met where a located authorization
                      accounts for the activity", and B likewise for a located
                      reconciliation. A resolution leaves every term in place,
                      so the relation STILL FORMS textually while the criterion
                      is defeated. For these twins the formation gates give the
                      WRONG answer and must not be used alone.

`criterion_support()` is a mechanical partial check for the deletion case only.
Resolution twins require a criterion-level judgement this module does not make.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sedition.packets.fact_vocabulary import Fact, FactVocabulary
from sedition.scoring.facts import _formation_group_hits


class Verdict(str, Enum):
    PASS = "PASS"
    OVER_ABLATED = "OVER_ABLATED"
    CRITERION_SURVIVES = "CRITERION_SURVIVES"
    NOTHING_HAPPENED = "NOTHING_HAPPENED"
    UNGATEABLE = "UNGATEABLE"

    @property
    def is_blocking(self) -> bool:
        """OVER_ABLATED is a warning; everything except PASS otherwise blocks."""
        return self not in (Verdict.PASS, Verdict.OVER_ABLATED)


@dataclass(frozen=True)
class FactVerdict:
    fact_id: str
    verdict: Verdict
    groups_total: int
    groups_hit: int
    hit_terms: tuple[str, ...]
    detail: str


@dataclass(frozen=True)
class AblationReport:
    packet_id: str
    facts: tuple[FactVerdict, ...]
    atomic_total: int
    atomic_present: int

    @property
    def blocking(self) -> tuple[FactVerdict, ...]:
        return tuple(f for f in self.facts if f.verdict.is_blocking)

    @property
    def warnings(self) -> tuple[FactVerdict, ...]:
        return tuple(f for f in self.facts if f.verdict is Verdict.OVER_ABLATED)

    @property
    def passed(self) -> bool:
        return not self.blocking and bool(self.facts)


def corpus_text(reports) -> str:
    """Join a packet's reports into the text an analyst reads.

    A derived relation in a multi-source packet spans reports by design, so the
    gates are applied to the whole corpus. Checking report-by-report would pass
    an ablation that merely split the decisive material across two reports.
    """
    out = []
    for r in reports:
        out.append(r["text"] if isinstance(r, dict) else getattr(r, "text", str(r)))
    return "\n\n".join(out)


def _grade(fact: Fact, text: str) -> FactVerdict:
    groups = fact.formation_groups
    if len(groups) < 2:
        return FactVerdict(
            fact.fact_id,
            Verdict.UNGATEABLE,
            len(groups),
            0,
            (),
            f"{len(groups)} formation group(s): a fact with fewer than two groups "
            f"cannot both fail to form (gate 1) and retain material (gate 2). "
            f"Author additional groups before using this fact in an ablated twin.",
        )
    hits = _formation_group_hits(groups, text)
    n_hit, n_tot = len(hits), len(groups)
    if n_hit == n_tot:
        return FactVerdict(
            fact.fact_id,
            Verdict.CRITERION_SURVIVES,
            n_tot,
            n_hit,
            hits,
            f"all {n_tot} formation groups still hit; the derived relation is "
            f"still reachable from the ablated reports, so the correct answer is "
            f"not routine update.",
        )
    if n_hit == 0:
        return FactVerdict(
            fact.fact_id,
            Verdict.NOTHING_HAPPENED,
            n_tot,
            n_hit,
            hits,
            f"0 of {n_tot} formation groups hit; all constituent material was "
            f"removed. A packet in which nothing happened discriminates nothing.",
        )
    if n_tot - n_hit > 1:
        return FactVerdict(
            fact.fact_id,
            Verdict.OVER_ABLATED,
            n_tot,
            n_hit,
            hits,
            f"{n_tot - n_hit} of {n_tot} groups removed; one is sufficient to "
            f"prevent formation. The twin is valid but the near miss is weaker "
            f"than it needs to be.",
        )
    return FactVerdict(
        fact.fact_id,
        Verdict.PASS,
        n_tot,
        n_hit,
        hits,
        f"{n_hit} of {n_tot} groups survive and exactly one was removed: the "
        f"relation cannot form, and the near-miss material is intact.",
    )


def evaluate_ablation(
    packet_id: str, ablated_reports, *, vocabulary: FactVocabulary
) -> AblationReport:
    """Grade one ablated twin against both section 18.4 gates.

    Args:
        packet_id: the twin's source packet, e.g. "E03-MS". Its fact vocabulary
            is what the twin is graded against; an ablated twin is only
            meaningful relative to the packet it ablates.
        ablated_reports: the twin's reports, as dicts with a "text" key or any
            object exposing `.text`.
        vocabulary: the reviewed fact vocabulary.

    Raises:
        ValueError: if the packet has no derived facts, which would let the gate
            pass vacuously.
    """
    text = corpus_text(ablated_reports)
    facts = tuple(f for f in vocabulary.for_packet(packet_id) if f.is_derived)
    if not facts:
        raise ValueError(
            f"{packet_id} has no derived facts; an ablation gate over zero facts "
            f"would pass vacuously. Check the packet id."
        )
    atomic = tuple(f for f in vocabulary.for_packet(packet_id) if f.is_atomic)
    present = sum(
        1
        for f in atomic
        if any(_formation_group_hits(((a,),), text) for a in f.effective_anchors())
    )
    return AblationReport(
        packet_id=packet_id,
        facts=tuple(_grade(f, text) for f in facts),
        atomic_total=len(atomic),
        atomic_present=present,
    )


def _parse_criteria(packet_id: str, prose: str) -> dict:
    """Parse `answer_key.criteria_satisfied` into per-criterion predicates.

    Refuses any clause it does not recognise. A clause silently treated as
    satisfied -- or as unsatisfied -- would make the whole check untrustworthy
    in a way nothing else would catch.

    NOTE: `answer_key.minimal_criterion_satisfying_report_sets` is NOT used.
    It is hand-written per packet and records only the sets its author chose
    to write down, so a criterion named in A.1 can have no set there at all
    (PREREGISTRATION 42.3). `criteria_satisfied` is the authoritative field.

    Every released packet is governed by Criterion C and states its C set in
    Appendix A.2, so `answer_key.minimal_set_coverage_gaps()` returns {}. The
    prose field remains authoritative because the structural check must not
    depend on an author's optional enumeration of minimal sets.
    """
    import re

    out = {}
    for letter, body in re.findall(r"([ABC])\s*\(([^)]*)\)", prose):
        ids = [f"{packet_id}-{m}" for m in re.findall(r"\bR\d\d\b", body)]
        if not ids:
            raise ValueError(f"{packet_id} criterion {letter}: no report ids in {body!r}")
        if re.match(r"\s*any two of\b", body, re.I):
            out[letter] = ("any 2 of " + ", ".join(i[-3:] for i in ids), tuple(ids), 2)
            continue
        head = re.split(r"[—-]{1,2}\s", body)[0]
        plus = [f"{packet_id}-{m}" for m in re.findall(r"\bR\d\d\b", head)]
        if re.search(r"\bR\d\d\b\s*\+", head) or len(plus) == 1:
            out[letter] = (" + ".join(i[-3:] for i in plus), tuple(plus), len(plus))
            continue
        raise ValueError(f"{packet_id} criterion {letter}: unrecognised clause {body!r}")
    # WHY THIS IS NOT `set(out) == {"A", "B", "C"}` ANY MORE.
    #
    # The released packets are governed by Criterion C alone. Each packet's
    # section 0 sets out why A
    # and B are structurally unreachable, and each A.1 says so in terms:
    #   "C (R05 + R09 - ...); A not met (...); B not met (...)"
    # Demanding three parsed criteria would refuse every packet the paper
    # reports. Every letter must therefore be ACCOUNTED
    # FOR -- either parsed as satisfied, or explicitly declared "not met" by
    # the packet's own A.1. A letter that appears in neither list is a
    # criterion the appendix never dispositioned, which is exactly the partial
    # picture the original check refused. This is strictly stronger than a
    # non-empty check and no weaker than the old one on a three-criterion
    # packet.
    not_met = set(re.findall(r"\b([ABC])\s+not\s+met\b", prose))
    accounted = set(out) | not_met
    if accounted != {"A", "B", "C"}:
        raise ValueError(
            f"{packet_id}: A.1 dispositions only {sorted(accounted)} "
            f"(satisfied={sorted(out)}, declared not met={sorted(not_met)}); "
            f"every one of A, B and C must be either satisfied or explicitly "
            f"declared not met. Refusing to report a partial criterion picture."
        )
    if set(out) & not_met:
        raise ValueError(
            f"{packet_id}: {sorted(set(out) & not_met)} parsed as BOTH satisfied "
            f"and not met; the appendix contradicts itself."
        )
    return out


def criterion_support(packet_id: str, surviving_report_ids, *, answer_key=None) -> dict:
    """Which criteria still have their full supporting report set present.

    This is a DELETION-ONLY check and a NECESSARY condition, not section 18.4's
    gate 1. A criterion whose reports are all present may still be defeated by a
    resolution written into those reports; a criterion whose reports are gone is
    genuinely unsupported. Read it as "what deletion alone has not defeated".

    Returns {letter: (clause, still_supported: bool)}.
    """
    import json

    from sedition.storage.paths import ANSWER_KEY_JSON

    if answer_key is None:
        answer_key = json.loads(ANSWER_KEY_JSON.read_text(encoding="utf-8"))["packets"]
    if packet_id not in answer_key:
        raise ValueError(f"no answer-key entry for {packet_id}")
    live = set(surviving_report_ids)
    parsed = _parse_criteria(packet_id, answer_key[packet_id]["criteria_satisfied"])
    return {
        letter: (clause, len([i for i in ids if i in live]) >= need)
        for letter, (clause, ids, need) in parsed.items()
    }


def format_report(report: AblationReport) -> str:
    """Render an AblationReport for a terminal."""
    lines = [
        f"ABLATION GATE - {report.packet_id}",
        "  section 18.4: (1) no criterion satisfiable  (2) near-miss survives",
        "",
    ]
    for f in report.facts:
        lines.append(f"  [{f.verdict.value:18s}] {f.fact_id}")
        lines.append(f"       groups hit {f.groups_hit}/{f.groups_total}  {f.detail}")
    lines += [
        "",
        f"  atomic material surviving: {report.atomic_present}/{report.atomic_total}"
        f"   (context for the near miss; not a gate)",
        "",
        f"  VERDICT: {'PASS' if report.passed else 'BLOCKED'}"
        + (f"   ({len(report.warnings)} warning(s))" if report.warnings else ""),
    ]
    return "\n".join(lines)
