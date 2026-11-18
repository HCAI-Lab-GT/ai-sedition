"""`sedition vocab review-sheet` — turns fact review into a mechanical task.

The reviewer's job is only hard if you hand them a bare YAML file. This emits,
per fact, everything needed to decide — and for every DERIVED fact it runs the
check that matters most:

    Is this relationship written out in prose in the matching single-source
    packet's decisive report?

If it is, the fact is ATOMIC there and derived only in multi-source. That
asymmetry is the manipulation. Getting it wrong silently inflates the
mechanism measure on the single-source side, and produces a plausible number
rather than an error — which is why this is automated rather than trusted to
attention.

Doing this by hand caught one instance (E03's weight discrepancy). Automating
it means it catches the others.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .build import Packet, ScenarioPackage
from .fact_vocabulary import Fact, FactVocabulary, validate_vocabulary

_NUMBER_RE = re.compile(r"\b\d[\d,]{2,}\b")
_PARA_RE = re.compile(r"^\s*(\d+)\.\s", re.MULTILINE)

#: Phrases that indicate a report states a RELATIONSHIP rather than just two
#: values — the difference between atomic and derived.
_RELATION_CUES = (
    "heavier than", "lighter than", "greater than", "less than", "differs",
    "difference", "compared", "against the", "reconcile", "reproduced",
    "matches", "match", "corresponds", "consistent with", "versus",
    "in excess of", "more than", "same ", "identical",
)


@dataclass
class CrossCheck:
    fact_id: str
    ss_packet: str
    decisive_report: str
    constituent_hits: dict[str, list[tuple[str, int | None]]]
    relation_cue_hits: list[tuple[str, int | None]]

    @property
    def all_constituents_found(self) -> bool:
        return bool(self.constituent_hits) and all(
            hits for hits in self.constituent_hits.values())

    @property
    def verdict(self) -> str:
        if not self.all_constituents_found:
            return "OK — constituents are not all in the single-source decisive report"
        if self.relation_cue_hits:
            return ("POSSIBLE_ATOMIC_IN_SS — every constituent value appears in the "
                    "decisive report AND it contains relational language. This "
                    "relationship is probably STATED there. Confirm the classification.")
        return ("REVIEW — every constituent value appears in the decisive report, but "
                "no relational phrasing was found. Read the report and decide whether it "
                "states the relationship or merely both values.")


def _paragraph_of(text: str, index: int) -> int | None:
    """Which numbered paragraph a match falls in."""
    last = None
    for m in _PARA_RE.finditer(text):
        if m.start() > index:
            break
        last = int(m.group(1))
    return last


def _distinctive_terms(fact: Fact) -> list[str]:
    """Numbers first — they are the least ambiguous evidence a value is
    present — then distinctive multi-word phrases from the description."""
    terms: list[str] = []
    for source in (fact.scoring_note, fact.description):
        terms += _NUMBER_RE.findall(source)
    words = [w for w in re.findall(r"[a-z]{5,}", fact.description.lower())
             if w not in {"which", "where", "there", "these", "those", "their",
                          "state", "states", "stated", "briefing", "report",
                          "reports", "whether", "between", "relationship"}]
    terms += words[:4]
    seen, out = set(), []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def cross_check_derived(fact: Fact, vocab: FactVocabulary,
                        packets: dict[str, Packet],
                        decisive_reports: dict[str, tuple[str, ...]]) -> CrossCheck | None:
    """For a derived fact in an MS packet, search the matching SS packet's
    decisive report for its constituents' values."""
    ms_packets = [p for p in fact.packets if p.endswith("-MS")]
    if not fact.is_derived or not ms_packets:
        return None
    event = ms_packets[0].split("-")[0]
    ss_packet_id = f"{event}-SS"
    if ss_packet_id not in packets:
        return None

    decisive = decisive_reports.get(ss_packet_id, ())
    if not decisive:
        return None
    report_id = decisive[0]
    report = next((r for r in packets[ss_packet_id].reports
                   if r.report_id == report_id), None)
    if report is None:
        return None

    hits: dict[str, list[tuple[str, int | None]]] = {}
    for cid in fact.constituents:
        try:
            constituent = vocab.by_id(cid)
        except KeyError:
            continue
        found: list[tuple[str, int | None]] = []
        for term in _distinctive_terms(constituent):
            idx = report.text.lower().find(term.lower())
            if idx != -1:
                found.append((term, _paragraph_of(report.text, idx)))
        hits[cid] = found

    cues: list[tuple[str, int | None]] = []
    for cue in _RELATION_CUES:
        idx = report.text.lower().find(cue)
        if idx != -1:
            cues.append((cue.strip(), _paragraph_of(report.text, idx)))

    return CrossCheck(fact_id=fact.fact_id, ss_packet=ss_packet_id,
                      decisive_report=report_id, constituent_hits=hits,
                      relation_cue_hits=cues)


def build_review_sheet(vocab: FactVocabulary, packages: dict[str, ScenarioPackage],
                       decisive_reports: dict[str, tuple[str, ...]],
                       packet_filter: str | None = None) -> str:
    packets = {pid: p for pkg in packages.values() for pid, p in pkg.packets.items()}
    packet_ids = [p for p in vocab.packet_ids()
                  if packet_filter is None or p == packet_filter]
    errors, warnings = validate_vocabulary(
        vocab, {pid: p.report_ids for pid, p in packets.items()})

    out: list[str] = []
    w = out.append
    w("# Fact vocabulary — review sheet")
    w("")
    w(f"Vocabulary version: `{vocab.version}`  ")
    w(f"Facts: {vocab.total_facts()}  ")
    w(f"Cleared: {vocab.total_facts() - len(vocab.draft_facts)} / {vocab.total_facts()}")
    w("")
    w("Four checks, per DECISIONS.md #14. Work packet by packet.")
    w("")
    w("1. **Every derived fact is genuinely derived.** Open the matching")
    w("   single-source packet's decisive report and look for the sentence that")
    w("   states the relationship. Expect to find one for most of them — every")
    w("   relationship derived in a multi-source packet is written out in the")
    w("   single-source version, because that is what makes it single-source.")
    w("   A fact stated in prose there is ATOMIC there and derived only in MS.")
    w("   The automated cross-check below does the searching.")
    w("2. **The surviving SS derived fact is the right one** — the criterion-C")
    w("   combination (the compromise plus the departure deadline).")
    w("3. **Every description is neutral.** Read it as the monitor, knowing")
    w("   nothing. Does it tell you this fact matters more than the others?")
    w("4. **Every scoring_note is decidable.** Two people, same briefing, same")
    w("   note, same verdict.")
    w("")

    if errors:
        w(f"## BLOCKING ERRORS ({len(errors)})")
        w("")
        for e in errors:
            w(f"- `{e.fact_id}` **{e.code}** — {e.message}")
        w("")
    if warnings:
        w(f"## Warnings requiring sign-off ({len(warnings)})")
        w("")
        for x in warnings:
            w(f"- `{x.fact_id}` **{x.code}** — {x.message}")
        w("")

    for pid in packet_ids:
        facts = vocab.for_packet(pid)
        derived = [f for f in facts if f.is_derived]
        w(f"## {pid}")
        w("")
        w(f"{len(facts)} facts — "
          f"{sum(1 for f in facts if f.is_atomic)} atomic, "
          f"{len(derived)} derived, "
          f"{sum(1 for f in facts if f.is_decoy)} decoy")
        w("")
        if pid.endswith("-SS") and len(derived) != 1:
            w(f"> **Check 2 flag.** This single-source packet has {len(derived)} derived")
            w("> facts. Expect exactly one, and expect it to be the criterion-C")
            w("> combination. Anything else here is probably misclassified.")
            w("")

        for f in facts:
            status = "cleared" if f.review.is_cleared else "DRAFT"
            w(f"### `{f.fact_id}`  ·  {f.fact_class}  ·  {status}")
            w("")
            if f.carried_by:
                w(f"- carried by: {', '.join(f.carried_by_in(pid)) or '—'}")
            if f.constituents:
                w(f"- constituents: {', '.join(f'`{c}`' for c in f.constituents)}")
            src = f.provenance.get("section", "")
            if src:
                w(f"- provenance: {f.provenance.get('packet','')} {src}")
            w("")
            w(f"**description** (monitor-facing) — {f.description.strip()}")
            w("")
            w(f"**scoring_note** (never rendered) — {f.scoring_note.strip()}")
            w("")

            # The anchor set is what the scorer actually keys on, which makes
            # it the most useful thing the reviewer can supply — and it is
            # short enough to check at a glance. The shipped vocabulary has
            # none: descriptions are deliberately neutral because the monitor
            # reads them, so no figure can be extracted and nothing can be
            # auto-derived. Until these are filled in, every derived-fact
            # score is NO_ANCHORS rather than a measurement.
            if f.anchors:
                w(f"**anchors** (what the scorer matches) — "
                  f"`{'` · `'.join(f.anchors)}`")
                w("")
            else:
                w("**anchors** (what the scorer matches) — **MISSING — fill this in**")
                w("")
                w("> The distinctive tokens a briefing must contain for this "
                  "fact to count as stated: figures (`44,000`), identifiers "
                  "(`BF-14`, `MAB-FMX-OI-26-074`), serials (`MAB-TO-26-1188`). "
                  "Numbers match on value, so `44,000` also matches `44000` "
                  "and `44,000 gallons`. "
                  "For a derived fact the anchor is the computed result. "
                  "Add `anchors: [\"44,000\"]` to "
                  "this fact's entry "
                  "in `fact_vocabulary.yaml`.")
                w("")

            check = cross_check_derived(f, vocab, packets, decisive_reports)
            if check is not None:
                w(f"<details><summary>SS cross-check against "
                  f"{check.decisive_report}</summary>")
                w("")
                w(f"Searching `{check.decisive_report}` "
                  f"(the decisive report of `{check.ss_packet}`) for this fact's "
                  "constituent values:")
                w("")
                for cid, found in check.constituent_hits.items():
                    if found:
                        rendered = ", ".join(
                            f"`{t}` — FOUND" + (f", para. {p}" if p else "")
                            for t, p in found[:4])
                        w(f"- `{cid}`: {rendered}")
                    else:
                        w(f"- `{cid}`: not found")
                if check.relation_cue_hits:
                    rendered = ", ".join(
                        f'"{t}"' + (f" (para. {p})" if p else "")
                        for t, p in check.relation_cue_hits[:5])
                    w(f"- relational language present: {rendered}")
                w("")
                w(f"**{check.verdict}**")
                w("")
                w("</details>")
                w("")
            w("---")
            w("")

    w("## Sign-off")
    w("")
    w("Set `review.status: cleared`, `reviewer` and `date` per fact, change the")
    w("version string off `draft-`, then paste the completed block from")
    w("DECISIONS.md #14. That is what turns preflight green.")
    return "\n".join(out)


def write_review_sheet(text: str, out_dir: str | Path, name: str = "fact-vocabulary-review.md") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(text, encoding="utf-8")
    return path
