"""Answer-key building, loading, and validation.

The key is derived from the read-only scenario files (Appendix A) plus the
released event trigger-rule file. If the key and the files
disagree, the files win and validation reports the mismatch — the scenario
prose is never edited to make validation pass.

The key is key-side material. Nothing in it may enter a model-facing payload
except the fact vocabulary explicitly designed for the monitor.
"""
from __future__ import annotations

import json
import re
from itertools import combinations
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import SpecViolationError
from ..agents.decisions import CANONICAL_DECISIONS
from .build import REPORTS_PER_PACKET, ScenarioPackage

APPENDIX_SECTION_RE = re.compile(r"^A\.(\d+)\s", re.MULTILINE)
#: Only released E01-E03 packet IDs are valid. Control twins are variants of
#: these packets rather than independent event IDs.
PACKET_ID_RE = re.compile(r"^(E0[1-3]-(?:SS|MS))$")
BRACE_SET_RE = re.compile(r"\{(R\d{2}(?:,\s*R\d{2})*)\}")
ID_LIST_RE = re.compile(r"\bR\d{2}\b")
TRIGGER_RULE_RE = re.compile(
    r"^### 7\.\d (E0[1-9]) — .*?\n+> \*\*(.+?)\*\*", re.MULTILINE | re.DOTALL
)


@dataclass(frozen=True)
class PacketKey:
    packet_id: str
    source_file: str
    packet_sha256: str
    report_ids: tuple[str, ...]
    correct_decision: str
    criteria_satisfied: str                       # prose, from Appendix A.1
    #: From Appendix A.2. STILL NOT USABLE for criterion satisfiability -- A.2
    #: states only the sets its author chose to write down, so a criterion named
    #: in A.1 may have no set here at all. Reading this field as "the criteria
    #: that can be satisfied" wrongly concluded two report drops were unusable
    #: (PREREGISTRATION 42.3). Use `criteria_satisfied` instead;
    #: `minimal_set_coverage_gaps()` reports the gap.
    #:
    #: The released packets are governed by Criterion C and their A.2 sections
    #: state the corresponding set. `minimal_set_coverage_gaps()` verifies this
    #: rather than assuming the hand-authored field is complete.
    minimal_criterion_satisfying_report_sets: tuple[tuple[str, ...], ...]
    noise_report_ids: tuple[str, ...]
    decoy_report_ids: tuple[str, ...]


@dataclass(frozen=True)
class AnswerKey:
    answer_key_version: str
    sources: dict[str, str]                       # path -> sha256
    packets: dict[str, PacketKey]
    trigger_rules: dict[str, str]                 # event -> key-side rule text
    # DERIVED from sedition/packets/fact_vocabulary.yaml — the builder does
    # not declare facts. If the two disagree, validate_answer_key errors.
    fact_vocabulary: dict | None
    fact_vocabulary_note: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)


def _split_appendix_sections(appendix: str) -> dict[str, str]:
    """Split Appendix A text into its A.n sections keyed by section number."""
    matches = list(APPENDIX_SECTION_RE.finditer(appendix))
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(appendix)
        sections[m.group(1)] = appendix[m.start():end].strip()
    return sections


def _qualify(packet_id: str, short_ids: list[str]) -> tuple[str, ...]:
    return tuple(f"{packet_id}-{r}" for r in short_ids)


def _parse_a1(a1: str, source: str) -> dict[str, tuple[str, str]]:
    """A.1 table: packet-id line, then decision line, then criteria prose line."""
    out: dict[str, tuple[str, str]] = {}
    lines = [ln.strip() for ln in a1.splitlines()]
    for i, line in enumerate(lines):
        if PACKET_ID_RE.match(line):
            if i + 2 >= len(lines):
                raise SpecViolationError(f"{source}: A.1 truncated after {line}")
            out[line] = (lines[i + 1], lines[i + 2])
    if not out:
        raise SpecViolationError(f"{source}: no packet rows found in Appendix A.1")
    return out


#: "any two of {R02, R04, ...}" — a THRESHOLD, not a conjunction.
_THRESHOLD_RE = re.compile(r"any\s+(one|two|three|four|five)\s+of\s*$", re.I)
_THRESHOLD_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def _parse_a2_sets(a2: str, packet_id: str) -> tuple[tuple[str, ...], ...]:
    """Minimal sets from the packet's paragraphs of A.2, THRESHOLDS EXPANDED.

    A.2 states two forms and the distinction is load-bearing:

        "Minimal set for Criterion B: {R07, R08}"          -> one set
        "minimal set for Criterion A: any two of {R02,...}" -> every 2-subset

    Reading both as brace-delimited conjunctions — which this did until
    2026-08-19 — silently records a threshold as a single large set. That is
    wrong in both directions at once: it OVERSTATES how many reports must be
    present for the criterion to hold, and it UNDERSTATES how hard the
    criterion is to defeat. A conjunction of five falls when any one report
    goes; "any two of five" survives until four are gone.

    Downstream this fed the difficulty metric, which ranked packets by the
    wrong quantity and produced an ordering that reversed once corrected.

    Expanding the threshold into its C(n, k) subsets keeps the field's type and
    meaning — "the smallest combinations that satisfy an individual visible
    criterion" — and makes every consumer correct without changing any of them.
    """
    sets: list[tuple[str, ...]] = []
    for para in a2.split("\n"):
        if not para.startswith(f"{packet_id} —"):
            continue
        for m in BRACE_SET_RE.finditer(para):
            short = ID_LIST_RE.findall(m.group(1))
            if not short:
                continue
            preamble = para[: m.start()]
            threshold = _THRESHOLD_RE.search(preamble.rstrip())
            if threshold:
                k = _THRESHOLD_WORDS[threshold.group(1).lower()]
                if 0 < k < len(short):
                    for combo in combinations(short, k):
                        sets.append(_qualify(packet_id, list(combo)))
                    continue
            sets.append(_qualify(packet_id, short))
    return tuple(sets)


def _parse_a4_noise(a4: str, packet_id: str) -> tuple[str, ...]:
    lines = [ln.strip() for ln in a4.splitlines()]
    for i, line in enumerate(lines):
        if line == packet_id and i + 1 < len(lines):
            short = ID_LIST_RE.findall(lines[i + 1])
            if short:
                return _qualify(packet_id, short)
    return ()


def _parse_a3_decoys(a3: str, packet_id: str) -> tuple[str, ...]:
    title = a3.splitlines()[0] if a3 else ""
    if packet_id not in title:
        return ()
    body = "\n".join(a3.splitlines()[1:])
    first_ids: list[str] = []
    for sentence in re.split(r"(?<=\.)\s", body):
        first_ids = ID_LIST_RE.findall(sentence)
        if first_ids:
            break
    return _qualify(packet_id, first_ids)


def extract_trigger_rules(omnibus_text: str) -> dict[str, str]:
    rules = {m.group(1): re.sub(r"\s+", " ", m.group(2)).strip()
             for m in TRIGGER_RULE_RE.finditer(omnibus_text)}
    # Every released event must have a non-empty rule.
    required = {"E01", "E02", "E03"}
    missing = required - set(rules)
    if missing:
        raise SpecViolationError(
            f"trigger-rule source has missing trigger rules for {sorted(missing)}; "
            f"found {sorted(rules)}"
        )
    empty = sorted(e for e, r in rules.items() if not (r or "").strip())
    if empty:
        raise SpecViolationError(f"trigger-rule source has empty rules for {empty}")
    return rules


def build_answer_key(packages: dict[str, ScenarioPackage],
                     omnibus_text: str,
                     version: str = "v1-draft-2026-08-14",
                     vocabulary=None) -> AnswerKey:
    """`vocabulary` is a FactVocabulary. The builder owns criteria, trigger
    rules, decoys, noise and packet composition; fact identity comes from the
    vocabulary file and is embedded here so there is exactly one authored fact
    list and one generated artifact."""
    packets: dict[str, PacketKey] = {}
    sources: dict[str, str] = {}
    for _event_id, pkg in sorted(packages.items()):
        source_id = f"scenarios/{pkg.source_path.name}"
        sources[source_id] = pkg.source_sha256
        sections = _split_appendix_sections(pkg.appendix_a)
        a1 = _parse_a1(sections.get("1", ""), pkg.source_path.name)
        for packet_id, packet in sorted(pkg.packets.items()):
            decision, criteria = a1[packet_id]
            packets[packet_id] = PacketKey(
                packet_id=packet_id,
                source_file=source_id,
                packet_sha256=packet.text_sha256,
                report_ids=packet.report_ids,
                correct_decision=decision,
                criteria_satisfied=criteria,
                minimal_criterion_satisfying_report_sets=_parse_a2_sets(
                    sections.get("2", ""), packet_id),
                noise_report_ids=_parse_a4_noise(sections.get("4", ""), packet_id),
                decoy_report_ids=_parse_a3_decoys(sections.get("3", ""), packet_id),
            )
    return AnswerKey(
        answer_key_version=version,
        sources=sources,
        packets=packets,
        trigger_rules=extract_trigger_rules(omnibus_text),
        fact_vocabulary=None if vocabulary is None else vocabulary.to_key_fragment(),
        fact_vocabulary_note=(
            "DERIVED from sedition/packets/fact_vocabulary.yaml. The builder does "
            "not declare facts; edit the vocabulary file and rebuild. "
            "validate_answer_key checks that every fact referenced here resolves "
            "to a vocabulary entry with matching class and carried_by."
        ),
    )


def load_answer_key(path: str | Path) -> AnswerKey:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    packets = {
        pid: PacketKey(
            packet_id=p["packet_id"],
            source_file=p["source_file"],
            packet_sha256=p["packet_sha256"],
            report_ids=tuple(p["report_ids"]),
            correct_decision=p["correct_decision"],
            criteria_satisfied=p["criteria_satisfied"],
            minimal_criterion_satisfying_report_sets=tuple(
                tuple(s) for s in p["minimal_criterion_satisfying_report_sets"]),
            noise_report_ids=tuple(p["noise_report_ids"]),
            decoy_report_ids=tuple(p["decoy_report_ids"]),
        )
        for pid, p in data["packets"].items()
    }
    return AnswerKey(
        answer_key_version=data["answer_key_version"],
        sources=data["sources"],
        packets=packets,
        # OPTIONAL, and absent from the held-out key by construction.
        #
        # The held-out key carries `governing_criterion` (one letter per packet)
        # instead of `trigger_rules` (the per-event notify rule text). Requiring
        # the field would mean either authoring trigger rules for someone else's
        # held-out packets -- forfeiting the independent-authorship property
        # those packets exist to provide -- or not running them at all.
        #
        # Defaulting to empty invents nothing. It does mean a held-out packet
        # carries LESS key-side information than ours, which matters in one
        # place: `boundary.scan` uses trigger rules as forbidden-content
        # patterns, so an empty mapping scans against the universal list only.
        # That is a weaker leak check, not a wrong one, and it is recorded here
        # rather than discovered later.
        trigger_rules=data.get("trigger_rules", {}),
        fact_vocabulary=data.get("fact_vocabulary"),
        fact_vocabulary_note=data.get("fact_vocabulary_note", ""),
    )


def validate_answer_key(key: AnswerKey, packages: dict[str, ScenarioPackage],
                        check_hashes: bool = False, vocabulary=None) -> list[str]:
    """Return a list of mismatch descriptions. Empty list = valid."""
    errors: list[str] = []
    expected_packets = {f"{e}-{v}" for e in packages for v in ("SS", "MS")}
    if set(key.packets) != expected_packets:
        errors.append(f"packet set mismatch: key has {sorted(key.packets)}, "
                      f"files have {sorted(expected_packets)}")

    for pid, pk in sorted(key.packets.items()):
        event = pid.split("-")[0]
        pkg = packages.get(event)
        if pkg is None or pid not in pkg.packets:
            errors.append(f"{pid}: no parsed packet for this key entry")
            continue
        packet = pkg.packets[pid]

        if len(pk.report_ids) != REPORTS_PER_PACKET:
            errors.append(f"{pid}: key lists {len(pk.report_ids)} reports, "
                          f"expected {REPORTS_PER_PACKET}")
        if pk.report_ids != packet.report_ids:
            errors.append(f"{pid}: key report_ids differ from scenario file")
        if pk.correct_decision not in CANONICAL_DECISIONS:
            errors.append(f"{pid}: correct_decision {pk.correct_decision!r} not canonical")
        if check_hashes and pk.packet_sha256 != packet.text_sha256:
            errors.append(f"{pid}: packet hash mismatch — scenario file changed "
                          "since the key was built")
        if check_hashes:
            recorded = key.sources.get(f"scenarios/{pkg.source_path.name}")
            if recorded != pkg.source_sha256:
                errors.append(f"{pkg.source_path.name}: source file hash mismatch")

        valid_ids = set(pk.report_ids)
        for s in pk.minimal_criterion_satisfying_report_sets:
            unknown = set(s) - valid_ids
            if unknown:
                errors.append(f"{pid}: minimal set references unknown reports {sorted(unknown)}")
            if set(s) & set(pk.noise_report_ids):
                errors.append(f"{pid}: minimal set overlaps noise reports: {sorted(set(s) & set(pk.noise_report_ids))}")
        # Reachability, CONDITIONAL ON THE CORRECT ANSWER.
        #
        # This check used to require a satisfying set unconditionally, which
        # compiled "every packet escalates" into the validator — the same
        # assumption the materials carry, sitting in code where nothing
        # surfaced it. A NO-ALARM packet has no satisfying set BY DEFINITION,
        # so the old form rejected the one packet the project most needs as
        # malformed.
        #
        # Conditional is strictly stronger, not weaker. It still catches an
        # unreachable NOTIFY packet, and it additionally catches a ROUTINE
        # packet that secretly satisfies a criterion — a failure the old check
        # could not express at all.
        if pk.correct_decision == "NOTIFY_IMMEDIATELY":
            if not pk.minimal_criterion_satisfying_report_sets:
                errors.append(
                    f"{pid}: correct_decision is NOTIFY_IMMEDIATELY but no "
                    "minimal criterion-satisfying set was extracted — the "
                    "answer is unreachable from the reports")
        elif pk.correct_decision == "INCLUDE_IN_ROUTINE_UPDATE":
            if pk.minimal_criterion_satisfying_report_sets:
                errors.append(
                    f"{pid}: correct_decision is INCLUDE_IN_ROUTINE_UPDATE but "
                    f"{len(pk.minimal_criterion_satisfying_report_sets)} "
                    "criterion-satisfying set(s) were extracted — a no-alarm "
                    "packet must satisfy no criterion")
        if not pk.noise_report_ids:
            errors.append(f"{pid}: no noise reports extracted")
        unknown_noise = set(pk.noise_report_ids) - valid_ids
        if unknown_noise:
            errors.append(f"{pid}: noise references unknown reports {sorted(unknown_noise)}")

    for event in packages:
        if not key.trigger_rules.get(event):
            errors.append(f"{event}: missing trigger rule")
        else:
            # Reachability, per version, and again CONDITIONAL ON THE ANSWER.
            # The matched-pair guarantee is unchanged: both versions of an
            # escalating event must be reachable, or the SS/MS pair has drifted
            # into two different experiments and nothing would say so. A
            # no-alarm event is held to the mirror-image requirement.
            for version in ("SS", "MS"):
                pid = f"{event}-{version}"
                pk = key.packets.get(pid)
                if pk is None:
                    errors.append(f"{event}: no {version} packet for the trigger rule")
                    continue
                reachable = bool(pk.minimal_criterion_satisfying_report_sets)
                if pk.correct_decision == "NOTIFY_IMMEDIATELY" and not reachable:
                    errors.append(
                        f"{pid}: trigger rule is not reachable — no minimal "
                        "criterion-satisfying report set")
                elif pk.correct_decision == "INCLUDE_IN_ROUTINE_UPDATE" and reachable:
                    errors.append(
                        f"{pid}: no-alarm packet is reachable — the trigger "
                        "rule can be satisfied, so the correct answer cannot "
                        "be INCLUDE_IN_ROUTINE_UPDATE")
            # Both versions of one event must agree on the answer, or the pair
            # is not a matched pair.
            answers = {key.packets[f"{event}-{v}"].correct_decision
                       for v in ("SS", "MS") if f"{event}-{v}" in key.packets}
            if len(answers) > 1:
                errors.append(
                    f"{event}: SS and MS disagree on correct_decision "
                    f"({sorted(answers)}) — not a matched pair")

    errors.extend(_validate_vocabulary_consistency(key, vocabulary))
    return errors


def _validate_vocabulary_consistency(key: AnswerKey, vocabulary) -> list[str]:
    """Every fact referenced in the key must resolve to a vocabulary entry,
    with matching class and carried_by. A mismatch is an error: two files that
    can disagree, with one validator, is exactly the failure this prevents."""
    errors: list[str] = []
    embedded = (key.fact_vocabulary or {}).get("facts")
    if embedded is None:
        if vocabulary is not None:
            errors.append("key carries no fact vocabulary but one was supplied — rebuild")
        return errors
    if vocabulary is None:
        return errors  # nothing to compare against

    authored = {f.fact_id: f for f in vocabulary.facts}
    for fact_id, entry in embedded.items():
        source = authored.get(fact_id)
        if source is None:
            errors.append(f"key references fact {fact_id!r} with no vocabulary entry")
            continue
        if entry.get("class") != source.fact_class:
            errors.append(f"{fact_id}: class mismatch — key {entry.get('class')!r} "
                          f"vs vocabulary {source.fact_class!r}")
        if list(entry.get("carried_by") or []) != list(source.carried_by):
            errors.append(f"{fact_id}: carried_by mismatch between key and vocabulary")
    for fact_id in authored:
        if fact_id not in embedded:
            errors.append(f"vocabulary fact {fact_id!r} is absent from the key — rebuild")

    refs = (key.fact_vocabulary or {}).get("allowed_fact_refs", {})
    for packet_id, ids in refs.items():
        for fact_id in ids:
            if fact_id not in authored:
                errors.append(f"{packet_id}: allowed_fact_refs names unknown fact {fact_id!r}")
    return errors


def minimal_set_coverage_gaps(answer_key) -> dict:
    """Reports named by Appendix A.1 that no Appendix A.2 minimal set contains.

    Appendix A.2 is hand-written per packet and records only the sets its author
    chose to write down. Nothing previously compared it against A.1, so a packet
    could name three criteria and carry one set without anything failing.

    The check compares REPORT COVERAGE rather than set counts. A.2's built form
    does not label its sets by criterion, so "which criterion is missing" cannot
    be stated from the artifact -- but "A.1 names this report and no A.2 set
    mentions it" can be. Against the released packets this function returns an
    empty mapping; keeping the check ensures future edits cannot introduce an
    unnoticed gap.

    This does not repair A.2. Completing it is a change to the scenario source,
    which is ground-truth material. It makes the gap explicit and testable so it
    cannot widen unnoticed.

    Returns {packet_id: {"named": (...), "covered": (...), "missing": (...)}}
    for packets with a non-empty gap.
    """
    out: dict[str, dict] = {}
    packets = getattr(answer_key, "packets", answer_key)
    for pid, pk in packets.items():
        prose = pk["criteria_satisfied"] if isinstance(pk, dict) else pk.criteria_satisfied
        sets = (
            pk["minimal_criterion_satisfying_report_sets"]
            if isinstance(pk, dict)
            else pk.minimal_criterion_satisfying_report_sets
        )
        named = {f"{pid}-{m}" for m in re.findall(r"\bR\d\d\b", prose)}
        if not named:
            raise ValueError(f"{pid}: no report ids parsed from criteria_satisfied {prose!r}")
        covered = {r for s in sets for r in s}
        missing = named - covered
        if missing:
            out[pid] = {
                "named": tuple(sorted(named)),
                "covered": tuple(sorted(covered)),
                "missing": tuple(sorted(missing)),
            }
    return out
