"""The fact vocabulary is the single authored source of fact identity, and
everything scored depends on it. These tests pin the properties that make it
safe to depend on.
"""
import dataclasses

import pytest

from sedition.packets.build import parse_all
from sedition.packets.fact_vocabulary import (
    Fact,
    MonitorFact,
    Review,
    load_fact_vocabulary,
    validate_vocabulary,
)
from sedition.storage.paths import HELDOUT_SCENARIOS_DIR, PACKAGE_ROOT, SCENARIOS_DIR

from ._vocab_review import AWAITING_REVIEW, KNOWN_WARNINGS


def _all_packages():
    """Scenario packages INCLUDING the held-out set.

    The vocabulary covers E03 now, so validating it against SCENARIOS_DIR alone
    reports every E03 fact as UNKNOWN_PACKET. Only the validation path needs this;
    golden generation and the answer-key build stay on SCENARIOS_DIR deliberately.
    """
    from sedition.packets.build import parse_scenario_file

    pkgs = dict(parse_all(SCENARIOS_DIR))
    heldout = HELDOUT_SCENARIOS_DIR
    if heldout.exists():
        for f in sorted(heldout.glob("*.md")):
            pkg = parse_scenario_file(f)
            pkgs[pkg.event_id] = pkg
    return pkgs

VOCAB = PACKAGE_ROOT / "packets" / "fact_vocabulary.yaml"


@pytest.fixture(scope="module")
def vocab():
    return load_fact_vocabulary(VOCAB)


@pytest.fixture(scope="module")
def packet_ids():
    return {pid: p.report_ids
            for pkg in _all_packages().values() for pid, p in pkg.packets.items()}


@pytest.fixture(scope="module")
def packet_texts():
    """Report text, so the computed-anchor precondition is actually checked.

    Without this `validate_vocabulary` cannot verify the precondition and says
    so with COMPUTED_ANCHOR_UNCHECKED rather than passing quietly.
    """
    return {pid: "\n".join(r.text for r in p.reports)
            for pkg in _all_packages().values() for pid, p in pkg.packets.items()}


def _fact(**over):
    base = dict(fact_id="E01.x", fact_class="atomic", packets=("E01-SS",),
                constituents=(), carried_by=("E01-SS-R06",),
                description="A neutral description.", scoring_note="Present when stated.",
                provenance={}, review=Review("draft", None, None))
    base.update(over)
    return Fact(**base)


# ---------------------------------------------------------- the real file ----

def test_shipped_vocabulary_has_no_errors(vocab, packet_ids, packet_texts):
    errors, _ = validate_vocabulary(vocab, packet_ids, packet_texts=packet_texts)
    assert [f"{e.fact_id}:{e.code}" for e in errors] == []


def test_shipped_vocabulary_raises_only_declared_warnings(vocab, packet_ids, packet_texts):
    """Was `== []`. The E01-E03 vocabulary raises six warnings that are
    deliberately not fixed -- see _vocab_review.KNOWN_WARNINGS for why each
    one stands. Comparing against the declared set keeps the guard live: a
    NEW warning still fails here, and the set empties as they are resolved."""
    _, warnings = validate_vocabulary(vocab, packet_ids, packet_texts=packet_texts)
    raised = {f"{w.fact_id}:{w.code}" for w in warnings}
    assert raised - KNOWN_WARNINGS == set(), (
        f"undeclared vocabulary warning(s): {sorted(raised - KNOWN_WARNINGS)}")
    assert KNOWN_WARNINGS - raised == set(), (
        f"declared warning(s) no longer raised -- remove them from KNOWN_WARNINGS: {sorted(KNOWN_WARNINGS - raised)}")


def test_omitting_packet_texts_is_loud_not_silent(vocab, packet_ids):
    """The precondition is unverifiable without report text, so it must SAY so.

    Skipping the check quietly is what let preflight report "0 error(s)" for a
    day while the precondition went unenforced.

    BUILT ON A SYNTHETIC FACT SINCE 2026-08-26, and that is the whole point.
    This used to run against the shipped vocabulary, where synthetic relation fixture's
    derived fact carried `2,469`, a genuine computed anchor. Every derived
    fact in the vocabulary that replaced it declares `formation_groups` and
    leaves `anchors` empty -- their relations are consequence inferences with
    no computed token -- so `computed_anchor_violations` now returns nothing
    and the assertion would have passed over an empty set forever.

    Re-derived, not tuned. Command that establishes there is no live subject:
      [f.fact_id for pid in v.packet_ids() for f in v.for_packet(pid)
       if f.fact_class == 'derived' and f.anchors]   # -> []
    So the subject is constructed here instead, and the guard stays executed
    against the day someone adds an anchor to a derived fact.
    """
    import dataclasses

    # Sanity: confirm the shipped vocabulary genuinely has no live subject,
    # so a future reader knows why this test builds its own.
    assert not [f for f in vocab.facts if f.is_derived and f.anchors], (
        "a shipped derived fact now carries an anchor -- point this test at it")

    derived = next(f for f in vocab.facts if f.is_derived)
    with_anchor = dataclasses.replace(derived, anchors=("99,999",))
    spiked = dataclasses.replace(
        vocab,
        facts=tuple(with_anchor if f.fact_id == derived.fact_id else f
                    for f in vocab.facts))

    errors, _ = validate_vocabulary(spiked, packet_ids)
    assert "COMPUTED_ANCHOR_UNCHECKED" in {e.code for e in errors}, (
        "a derived fact with an own-anchor and no packet text to check it "
        "against must be reported, not skipped")




def test_shipped_vocabulary_is_cleared_and_attributed(vocab):
    """Signed off 2026-08-15 after the anchor audit. Was the inverse of this
    assertion while the vocabulary was generated-but-unreviewed.

    Attribution is checked, not just the status: `is_reviewed` only looks at
    the status field and the version string, so a clearance with no reviewer
    or no date would pass it and leave nobody accountable for the review."""
    pending = {f.fact_id for f in vocab.draft_facts}
    assert pending <= AWAITING_REVIEW, (
        f"facts are draft but not declared as awaiting review: "
        f"{sorted(pending - AWAITING_REVIEW)}")
    assert AWAITING_REVIEW <= pending or not (AWAITING_REVIEW - pending), (
        f"AWAITING_REVIEW names facts that are already cleared -- remove them: "
        f"{sorted(AWAITING_REVIEW - pending)}")
    for f in vocab.facts:
        if f.fact_id in AWAITING_REVIEW:
            continue
        assert f.review.reviewer, f"{f.fact_id}: cleared with no reviewer"
        assert f.review.date, f"{f.fact_id}: cleared with no date"


def test_a_single_draft_fact_un_clears_the_whole_vocabulary(vocab):
    """The gate is all-or-nothing on purpose: a vocabulary that is 57/58
    reviewed is not reviewed, and must not quietly enable a scored run."""
    import dataclasses

    one_draft = dataclasses.replace(
        vocab,
        facts=(dataclasses.replace(
            vocab.facts[0],
            review=dataclasses.replace(vocab.facts[0].review, status="draft"),
        ),) + tuple(vocab.facts[1:]),
    )
    assert not one_draft.is_reviewed


def test_the_derived_count_inversion_is_present_and_declared(vocab):
    """INVERTED 2026-08-26, deliberately, and this is the record of it.

    Each released packet carries
    exactly one derived relation per arm, 1 vs 1. That is already recorded as
    a deliberate limitation -- `_vocab_review.KNOWN_WARNINGS` declares
    E01/E02/E03:DERIVED_COUNT_INVERTED and says why authoring extra MS
    derived facts to clear it would be editing the instrument to make a check
    pass, immediately before the run it measures.

    The assertion and declared warning keep this limitation visible.

    Re-derived, not tuned:
      sum(1 for f in vocab.for_packet('E01-MS') if f.is_derived)  # -> 1
      sum(1 for f in vocab.for_packet('E01-SS') if f.is_derived)  # -> 1
    """
    for event in ("E01", "E02", "E03"):
        ms = sum(1 for f in vocab.for_packet(f"{event}-MS") if f.is_derived)
        ss = sum(1 for f in vocab.for_packet(f"{event}-SS") if f.is_derived)
        assert (ms, ss) == (1, 1), f"{event}: MS={ms} derived, SS={ss}"
        assert f"{event}:DERIVED_COUNT_INVERTED" in KNOWN_WARNINGS, (
            f"{event} carries the inversion but does not declare it")


def test_each_single_source_packet_keeps_exactly_one_derived_fact(vocab):
    """Review check 2. Anything else in an SS packet marked derived is
    probably a relationship the decisive report states in prose."""
    for event in ("E01", "E02", "E03"):
        derived = [f for f in vocab.for_packet(f"{event}-SS") if f.is_derived]
        assert len(derived) == 1, f"{event}-SS has {len(derived)} derived facts"


def test_single_source_packets_carry_more_decoys(vocab):
    for event in ("E01", "E02", "E03"):
        ss = sum(1 for f in vocab.for_packet(f"{event}-SS") if f.is_decoy)
        ms = sum(1 for f in vocab.for_packet(f"{event}-MS") if f.is_decoy)
        assert ss > ms, f"{event}: SS={ss} decoys, MS={ms}"


# ------------------------------------------------------ monitor exposure ----

def test_monitor_fact_structurally_cannot_carry_a_scoring_note():
    """Stronger than remembering to strip it: the field does not exist on the
    only shape a renderer receives."""
    assert not hasattr(MonitorFact("id", "desc"), "scoring_note")
    assert "scoring_note" not in {f.name for f in dataclasses.fields(MonitorFact)}


def test_rendered_vocabulary_contains_no_scoring_note(vocab):
    for pid in vocab.packet_ids():
        rendered = vocab.render_for_monitor(pid)
        for f in vocab.for_packet(pid):
            head = f.scoring_note.strip()[:40]
            assert head and head not in rendered, f"{f.fact_id} leaked its scoring_note"


def test_rendered_vocabulary_names_no_report(vocab):
    import re
    for pid in vocab.packet_ids():
        assert not re.search(r"E0\d-(?:SS|MS)-R\d\d", vocab.render_for_monitor(pid))


def test_rendered_vocabulary_never_names_a_class(vocab):
    """A fact ID that names its class hands the monitor the classification."""
    for pid in vocab.packet_ids():
        lowered = vocab.render_for_monitor(pid).lower()
        for banned in ("atomic", "derived", "decoy"):
            assert banned not in lowered


# -------------------------------------------------------------- errors ----

def test_derived_fact_needs_two_constituents():
    v = _v(_fact(fact_class="derived", constituents=("E01.a",), carried_by=()))
    assert _codes(v) == ["DERIVED_TOO_FEW_CONSTITUENTS", "UNKNOWN_CONSTITUENT"]


def test_derived_fact_may_not_be_carried_by_a_report():
    """A derived fact appears in NO report — that is what makes it derived."""
    v = _v(_fact(fact_id="E01.d", fact_class="derived",
                 constituents=("E01.d", "E01.d"), carried_by=("E01-SS-R06",)))
    assert "DERIVED_HAS_CARRIER" in _codes(v)


def test_description_may_not_name_a_report():
    v = _v(_fact(description="The weight stated in E01-SS-R06."))
    assert "DESCRIPTION_NAMES_REPORT" in _codes(v)


def test_description_may_not_equal_scoring_note():
    v = _v(_fact(description="Same text.", scoring_note="Same text."))
    assert "DESCRIPTION_EQUALS_SCORING_NOTE" in _codes(v)


def test_fact_id_may_not_name_its_class():
    v = _v(_fact(fact_id="E01.decoy_thing", fact_class="decoy", carried_by=("E01-SS-R01",)))
    assert "ID_NAMES_CLASS" in _codes(v)


def test_carrier_must_sit_inside_the_declared_packets():
    v = _v(_fact(packets=("E01-SS",), carried_by=("E01-MS-R06",)))
    assert "CARRIER_OUTSIDE_PACKETS" in _codes(v)


def test_draft_fact_blocks_when_the_stage_requires_review():
    v = _v(_fact())
    errors, _ = validate_vocabulary(v, None, require_reviewed=True)
    assert "NOT_REVIEWED" in [e.code for e in errors]
    errors, _ = validate_vocabulary(v, None, require_reviewed=False)
    assert "NOT_REVIEWED" not in [e.code for e in errors]


def test_neutrality_lint_warns_on_importance_language():
    v = _v(_fact(description="The critical fact that proves the terminal was inside."))
    _, warnings = validate_vocabulary(v, None)
    assert "NEUTRALITY_LINT" in [w.code for w in warnings]


def test_cleared_vocabulary_reads_as_reviewed():
    from sedition.packets.fact_vocabulary import FactVocabulary
    cleared = _fact(review=Review("cleared", "someone", "2026-08-16"))
    assert FactVocabulary(version="v1-2026-08-16", facts=(cleared,)).is_reviewed
    # a cleared fact under a draft version string is still not reviewed
    assert not FactVocabulary(version="draft-x", facts=(cleared,)).is_reviewed


def _v(*facts):
    from sedition.packets.fact_vocabulary import FactVocabulary
    return FactVocabulary(version="draft-test", facts=tuple(facts))


def _codes(v):
    errors, _ = validate_vocabulary(v, None)
    return sorted({e.code for e in errors})
