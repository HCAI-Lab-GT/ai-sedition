"""Fact vocabulary: the single authored source of fact identity.

build/answer_key.json derives from this. The key's builder declares criteria,
trigger rules, decoys and packet composition; it does not declare facts.

TWO TEXT FIELDS, AND THE SPLIT IS LOAD-BEARING:

    description   monitor-facing, neutral, no report IDs
    scoring_note  NEVER rendered into any prompt

`MonitorFact` is the only shape a renderer can receive, and it structurally
cannot carry a scoring_note — the field does not exist on it. That is a
stronger guarantee than remembering to strip it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

DRAFT_MARKER = "draft"
CLASSES = ("atomic", "derived", "decoy")

#: Used by the description-leak lint to spot a report id quoted inside a
#: monitor-facing description.
_REPORT_ID_RE = re.compile(r"E\d\d-(?:SS|MS)-R\d\d")
_PACKET_ID_RE = re.compile(r"^(E\d{2}-(?:SS|MS))-R\d\d$")

#: The released vocabulary covers every released packet. This registry stays
#: explicit so future omissions cannot be mistaken for intentional exclusions.
DECLARED_UNCOVERED: dict[str, str] = {}

#: Words that signal importance. A monitor-facing description containing one
#: tells the monitor which facts matter — which is the answer key.
NEUTRALITY_LINT = (
    "decisive", "critical", "crucial", "proves", "establishes", "urgent",
    "must", "notification", "criterion", "threshold", "serious",
)
#: "key" needs word-boundary care: "key-loader" is equipment, not emphasis.
_BARE_KEY_RE = re.compile(r"\bkey\b(?!-)", re.IGNORECASE)


@dataclass(frozen=True)
class MonitorFact:
    """The ONLY fact shape a prompt renderer may receive.

    No scoring_note field exists here. A renderer cannot leak what it was
    never handed.
    """
    fact_id: str
    description: str


@dataclass(frozen=True)
class Review:
    status: str          # draft | cleared
    reviewer: str | None
    date: str | None

    @property
    def is_cleared(self) -> bool:
        return self.status == "cleared"


@dataclass(frozen=True)
class Fact:
    fact_id: str
    fact_class: str
    packets: tuple[str, ...]
    constituents: tuple[str, ...]
    carried_by: tuple[str, ...]
    description: str
    scoring_note: str
    provenance: dict
    review: Review
    #: The distinctive tokens a briefing must actually contain for this fact
    #: to count as stated: figures, identifiers, serial numbers. Authored by
    #: the reviewer. Live examples from the packets now on disk: `lot 27-D`,
    #: `MAB-FMX-OI-26-074`, `44,000`, `Lot 44-C`, `HF-MQC-26-0187`, `0450K`.
    #: (The examples here used to be 12,000 / ITEM-42 / ITEM-42, all legacy
    #: E01-E03 material deleted 2026-08-26.)
    #:
    #: Empty means "not yet reviewed", and `effective_anchors()` falls back to
    #: auto-derivation so the scorer works before the review completes. The
    #: fallback is explicitly second-best — see `derive_anchors`.
    anchors: tuple[str, ...] = ()
    #: Reviewer-authored formation boundary, adopted from reviewer-c-branch on
    #: 2026-08-21. Conjunctive across groups, disjunctive within: every group
    #: must be satisfied by at least one of its alternatives. Empty means the
    #: fact has no authored boundary and falls back to relational scoring.
    #: Provenance: authored by Reviewer C, reviewed by Reviewer A.
    formation_groups: tuple[tuple[str, ...], ...] = ()

    def effective_anchors(self) -> tuple[str, ...]:
        """Authored anchors when present, auto-derived otherwise."""
        return self.anchors or derive_anchors(self)

    @property
    def anchors_are_authored(self) -> bool:
        return bool(self.anchors)

    @property
    def is_atomic(self) -> bool:
        return self.fact_class == "atomic"

    @property
    def is_derived(self) -> bool:
        return self.fact_class == "derived"

    @property
    def is_decoy(self) -> bool:
        return self.fact_class == "decoy"

    def for_monitor(self) -> MonitorFact:
        return MonitorFact(fact_id=self.fact_id, description=self.description.strip())

    def carried_by_in(self, packet_id: str) -> tuple[str, ...]:
        return tuple(r for r in self.carried_by if r.startswith(packet_id + "-"))


#: Figures the reports state, e.g. 44,000 · 700 · 0450K · 0605K · 2312K.
_FIGURE_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?K?\b")
#: Identifiers, e.g. BF-14, KL-9, KRC-2, MAB-TO-26-1188, HF-MQC-26-0187.
_IDENT_RE = re.compile(r"\b[A-Z]{1,5}[-–]?\d{1,5}(?:[-–][A-Z0-9]{1,5})?\b")


def derive_anchors(fact: Fact) -> tuple[str, ...]:
    """Best-effort anchors for a fact whose reviewer has not authored them.

    Pulls figures and identifiers out of the scoring note and the description.
    This is a fallback, not a design: a reviewer looking at the reports knows
    which tokens actually distinguish a fact, and an extractor guessing from
    prose does not. Facts with no authored anchors are reported by
    `validate_vocabulary` so the gap is visible rather than silently papered
    over.
    """
    text = f"{fact.scoring_note} {fact.description}"
    found = set(_FIGURE_RE.findall(text)) | set(_IDENT_RE.findall(text))
    # Bare small integers are noise ("two systems", "three reports").
    return tuple(sorted(
        a for a in found
        if not (a.isdigit() and len(a) <= 2)
    ))


@dataclass(frozen=True)
class VocabError:
    fact_id: str
    code: str
    message: str


@dataclass(frozen=True)
class VocabWarning:
    fact_id: str
    code: str
    message: str


@dataclass(frozen=True)
class FactVocabulary:
    version: str
    facts: tuple[Fact, ...]
    source_path: Path | None = None

    @property
    def is_reviewed(self) -> bool:
        """Both conditions: the version string is off `draft-`, AND every
        fact is individually cleared."""
        return (DRAFT_MARKER not in self.version.lower()
                and all(f.review.is_cleared for f in self.facts))

    @property
    def draft_facts(self) -> tuple[Fact, ...]:
        return tuple(f for f in self.facts if not f.review.is_cleared)

    def by_id(self, fact_id: str) -> Fact:
        for f in self.facts:
            if f.fact_id == fact_id:
                return f
        raise KeyError(fact_id)

    def for_packet(self, packet_id: str) -> tuple[Fact, ...]:
        return tuple(f for f in self.facts if packet_id in f.packets)

    def ids_for_packet(self, packet_id: str) -> frozenset[str]:
        return frozenset(f.fact_id for f in self.for_packet(packet_id))

    def packet_ids(self) -> tuple[str, ...]:
        return tuple(sorted({p for f in self.facts for p in f.packets}))

    def total_facts(self) -> int:
        return len(self.facts)

    # -- the only rendering path ------------------------------------------
    def monitor_facts(self, packet_id: str) -> tuple[MonitorFact, ...]:
        return tuple(f.for_monitor() for f in self.for_packet(packet_id))

    def render_for_monitor(self, packet_id: str) -> str:
        """ID + neutral description only. Built from MonitorFact, which has
        no scoring_note to leak."""
        return "\n".join(f"{m.fact_id}: {m.description}"
                         for m in self.monitor_facts(packet_id))

    def allowed_fact_refs(self, packet_id: str) -> list[str]:
        return sorted(self.ids_for_packet(packet_id))

    def to_key_fragment(self) -> dict:
        """What build_answer_key.py embeds. Key-side, so it carries the
        classification — but never the scoring notes, which are for human
        scorers and code, not for any artifact that could be rendered."""
        return {
            "fact_vocabulary_version": self.version,
            "fact_vocabulary_reviewed": self.is_reviewed,
            "facts": {
                f.fact_id: {
                    "class": f.fact_class,
                    "packets": list(f.packets),
                    "constituents": list(f.constituents),
                    "carried_by": list(f.carried_by),
                    "description": f.description.strip(),
                }
                for f in self.facts
            },
            "allowed_fact_refs": {
                pid: self.allowed_fact_refs(pid) for pid in self.packet_ids()
            },
        }


def load_fact_vocabulary(path: str | Path) -> FactVocabulary:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    facts = []
    for entry in data["facts"]:
        review = entry.get("review") or {}
        facts.append(Fact(
            fact_id=entry["fact_id"],
            fact_class=entry["class"],
            packets=tuple(entry.get("packets") or []),
            constituents=tuple(entry.get("constituents") or []),
            carried_by=tuple(entry.get("carried_by") or []),
            description=entry.get("description", ""),
            scoring_note=entry.get("scoring_note", ""),
            provenance=entry.get("provenance") or {},
            review=Review(status=review.get("status", "draft"),
                          reviewer=review.get("reviewer"),
                          date=review.get("date")),
            anchors=tuple(entry.get("anchors") or []),
            formation_groups=tuple(
                tuple(g) for g in (entry.get("formation_groups") or [])
            ),
        ))
    return FactVocabulary(version=data["version"], facts=tuple(facts),
                          source_path=path)


# ---------------------------------------------------------------- checks ---

def _norm_anchor(a: str) -> str:
    """Same normalisation the scorer applies, kept local so this module does not
    import from scoring -- the dependency would run the wrong way."""
    return re.sub(r"[^a-z0-9]", "", a.lower())


def _shortcut_anchors(vocab: FactVocabulary, fact: Fact) -> list[str]:
    """`fact`'s anchors that are NOT also constituent anchors.

    These are the ones the scorer reads as computed values, so these are the
    ones whose absence from the source reports has to hold.
    """
    known = {x.fact_id for x in vocab.facts}
    constituent = {
        _norm_anchor(a)
        for cid in fact.constituents
        for a in (vocab.by_id(cid).effective_anchors() if cid in known else ())
    }
    return [a for a in fact.effective_anchors()
            if _norm_anchor(a) not in constituent]


def computed_anchor_violations(vocab: FactVocabulary,
                               packet_texts: dict[str, str]) -> list[VocabError]:
    """A derived fact's COMPUTED anchors must not appear in its source reports.

    `scoring.facts._authored_formation` treats any anchor of a derived fact that
    is not also a constituent anchor as a COMPUTED value, and returns FORMED on
    its presence alone -- skipping the formation groups entirely. That shortcut is
    sound ONLY when the anchor cannot appear unless the derivation was performed.

    The shipped derived facts use formation groups and leave anchors empty.
    This guard remains active because adding an anchor later would re-enable
    the shortcut. A qualifying anchor must be a value that cannot appear unless
    the derivation was performed; a value printed in a source report does not
    qualify.

    This is a PRECONDITION of the shortcut, not a convention, so it is enforced
    at load time rather than remembered by whoever authors the next fact.
    """
    out: list[VocabError] = []
    for f in vocab.facts:
        if not f.is_derived or not f.formation_groups:
            continue
        for anchor in _shortcut_anchors(vocab, f):
            for pid in f.packets:
                text = packet_texts.get(pid)
                if text and anchor.lower() in text.lower():
                    out.append(VocabError(
                        f.fact_id, "COMPUTED_ANCHOR_IN_SOURCE",
                        f"anchor {anchor!r} is not a constituent anchor, so the scorer "
                        f"treats it as a computed value and returns FORMED on its "
                        f"presence alone -- but it appears verbatim in {pid}'s reports. "
                        f"Either make it a constituent anchor or remove it."))
                    break
    return out


def validate_vocabulary(vocab: FactVocabulary,
                        packets: dict[str, tuple[str, ...]] | None = None,
                        *, require_reviewed: bool = False,
                        packet_texts: dict[str, str] | None = None,
                        ) -> tuple[list[VocabError], list[VocabWarning]]:
    """Errors block preflight. Warnings surface in the review sheet and
    require a reviewer's sign-off.

    `packet_texts` maps packet id to its concatenated report text. When given,
    the computed-anchor precondition is enforced; when omitted it cannot be
    checked, which is why the callers that have the text pass it.
    """
    errors: list[VocabError] = []
    warnings: list[VocabWarning] = []
    seen: set[str] = set()
    known = {f.fact_id for f in vocab.facts}

    for f in vocab.facts:
        fid = f.fact_id

        if fid in seen:
            errors.append(VocabError(fid, "DUPLICATE_ID", "fact_id appears more than once"))
        seen.add(fid)

        if f.fact_class not in CLASSES:
            errors.append(VocabError(fid, "BAD_CLASS", f"unknown class {f.fact_class!r}"))
        if not f.packets:
            errors.append(VocabError(fid, "NO_PACKETS", "fact belongs to no packet"))

        # --- derived-fact structure ---
        if f.is_derived:
            if len(f.constituents) < 2:
                errors.append(VocabError(
                    fid, "DERIVED_TOO_FEW_CONSTITUENTS",
                    f"derived fact has {len(f.constituents)} constituent(s); a fact that "
                    "holds across reports needs at least 2"))
            if f.carried_by:
                errors.append(VocabError(
                    fid, "DERIVED_HAS_CARRIER",
                    f"derived fact lists carried_by={list(f.carried_by)}; a derived fact "
                    "appears in NO report, which is what makes it derived"))
        else:
            if not f.carried_by and not f.is_decoy:
                errors.append(VocabError(fid, "ATOMIC_NO_CARRIER",
                                         "atomic fact cites no carrying report"))

        for c in f.constituents:
            if c not in known:
                errors.append(VocabError(fid, "UNKNOWN_CONSTITUENT",
                                         f"constituent {c!r} is not a fact in this vocabulary"))

        # --- carried_by must sit inside the declared packets ---
        for rid in f.carried_by:
            m = _PACKET_ID_RE.match(rid)
            if not m:
                errors.append(VocabError(fid, "BAD_REPORT_ID", f"malformed report id {rid!r}"))
            elif m.group(1) not in f.packets:
                errors.append(VocabError(
                    fid, "CARRIER_OUTSIDE_PACKETS",
                    f"carried_by {rid!r} is not in this fact's packets {list(f.packets)}"))

        # --- description hygiene (monitor-facing) ---
        leaked = _REPORT_ID_RE.findall(f.description)
        if leaked:
            errors.append(VocabError(
                fid, "DESCRIPTION_NAMES_REPORT",
                f"monitor-facing description names {sorted(set(leaked))}; naming a report "
                "tells the monitor which report matters"))
        if f.description.strip() and f.description.strip() == f.scoring_note.strip():
            errors.append(VocabError(fid, "DESCRIPTION_EQUALS_SCORING_NOTE",
                                     "description and scoring_note are identical (copy-paste)"))
        # The monitor sees fact IDs. An ID naming its own class tells the
        # monitor which facts are decoys — the answer key, in the identifier.
        for cls in CLASSES:
            if cls in fid.lower():
                errors.append(VocabError(
                    fid, "ID_NAMES_CLASS",
                    f"fact_id contains its class {cls!r}; the monitor sees fact IDs, "
                    "so an ID that names its class leaks the classification"))
        if not f.description.strip():
            errors.append(VocabError(fid, "NO_DESCRIPTION", "description is empty"))
        if not f.scoring_note.strip():
            errors.append(VocabError(fid, "NO_SCORING_NOTE", "scoring_note is empty"))

        lowered = f.description.lower()
        hits = [w for w in NEUTRALITY_LINT if re.search(rf"\b{re.escape(w)}\b", lowered)]
        if _BARE_KEY_RE.search(f.description):
            hits.append("key")
        if hits:
            warnings.append(VocabWarning(
                fid, "NEUTRALITY_LINT",
                f"description contains importance-signalling term(s) {sorted(set(hits))}"))

        if require_reviewed and not f.review.is_cleared:
            errors.append(VocabError(fid, "NOT_REVIEWED",
                                     f"review.status is {f.review.status!r}; this stage "
                                     "requires a cleared vocabulary"))

    if packets is not None:
        valid = {pid: set(rids) for pid, rids in packets.items()}
        for f in vocab.facts:
            for p in f.packets:
                if p not in valid:
                    errors.append(VocabError(f.fact_id, "UNKNOWN_PACKET",
                                             f"packet {p!r} does not exist"))
            for rid in f.carried_by:
                m = _PACKET_ID_RE.match(rid)
                if m and m.group(1) in valid and rid not in valid[m.group(1)]:
                    errors.append(VocabError(f.fact_id, "UNKNOWN_REPORT",
                                             f"{rid!r} is not a report in {m.group(1)}"))

        # --- structural sanity: the SS/MS asymmetry should be visible ---
        for event in sorted({p.split("-")[0] for p in valid}):
            ss, ms = f"{event}-SS", f"{event}-MS"
            if ss not in valid or ms not in valid:
                continue
            # A packet on the declared-uncovered list has no facts on purpose;
            # every coverage comparison against it is vacuous. See 64.
            if ss in DECLARED_UNCOVERED or ms in DECLARED_UNCOVERED:
                continue
            ss_d = sum(1 for f in vocab.for_packet(ss) if f.is_derived)
            ms_d = sum(1 for f in vocab.for_packet(ms) if f.is_derived)
            ss_k = sum(1 for f in vocab.for_packet(ss) if f.is_decoy)
            ms_k = sum(1 for f in vocab.for_packet(ms) if f.is_decoy)
            # An event the vocabulary does not cover yields 0 vs 0, and 0 <= 0
            # fires the inversion warning on a comparison that carries no
            # information, so uncovered events are skipped rather than
            # reported as a phantom inversion. A genuine inversion still needs
            # at least one side to be non-zero.
            #
            # All three released events intentionally have one derived fact in
            # each form. The warning therefore remains visible rather than
            # being silenced by authoring extra facts to satisfy the lint.
            if ms_d == 0 and ss_d == 0 and ms_k == 0 and ss_k == 0:
                continue
            if ms_d <= ss_d:
                warnings.append(VocabWarning(
                    event, "DERIVED_COUNT_INVERTED",
                    f"{ms} has {ms_d} derived facts, {ss} has {ss_d}. The multi-source "
                    "packet should carry more: its case exists only after cross-referencing."))
            if ss_k <= ms_k:
                warnings.append(VocabWarning(
                    event, "DECOY_COUNT_INVERTED",
                    f"{ss} has {ss_k} decoys, {ms} has {ms_k}. The single-source packet "
                    "should carry more: its surrounding material is exculpatory."))

    if packet_texts:
        errors.extend(computed_anchor_violations(vocab, packet_texts))
    else:
        # Skipping silently is how this check went missing: preflight called
        # without packet_texts for a day and reported "0 error(s)" while the
        # precondition went unenforced. If there is a derived fact whose
        # shortcut depends on the precondition, say we could not check it.
        unchecked = [f.fact_id for f in vocab.facts
                     if f.is_derived and f.formation_groups
                     and _shortcut_anchors(vocab, f)]
        if unchecked:
            errors.append(VocabError(
                unchecked[0], "COMPUTED_ANCHOR_UNCHECKED",
                f"{len(unchecked)} derived fact(s) carry a non-constituent anchor that "
                f"short-circuits formation, and no packet text was supplied to verify "
                f"the anchor is absent from the source reports. Pass packet_texts. "
                f"Affected: {', '.join(unchecked)}"))

    return errors, warnings


def validate_against_packets(vocab: FactVocabulary,
                             packets: dict[str, tuple[str, ...]],
                             packet_texts: dict[str, str] | None = None) -> list[str]:
    """Back-compatible flat-string view, for callers that only want a count."""
    errors, _ = validate_vocabulary(vocab, packets, packet_texts=packet_texts)
    return [f"{e.fact_id}: {e.code}: {e.message}" for e in errors]
