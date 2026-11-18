"""A DRAFT twin must not reach a scored run.

WHY THIS EXISTS. Every twin file carried
`"status": "DRAFT - awaiting criterion-level human review (PREREGISTRATION 46)"`
and **nothing read it**. `resolve_packet` loaded the file, the run started, and
54 episodes were scored against stimuli whose own metadata said they were not
cleared.

The documentation asserted the gate existed --
`docs/twins/CRITERION_TABLE_FOR_SIGNOFF.md` said "Preflight blocks on
`review.status: draft` by design. Nothing runs against these until this table is
signed off." That claim was false, and it was worse than having no gate at all,
because the claim was the stated reason it was safe to proceed.

THE CONTRACT:
  * a twin whose status starts DRAFT raises;
  * a twin with NO recorded status raises too -- "never reviewed" and "review
    state lost" are indistinguishable, so neither is assumed cleared;
  * the threat packets are untouched by any of this;
  * review tooling that must read a draft in order to review it sets
    `variants.ALLOW_DRAFT_TWINS`, and a scored run never does.
"""
from __future__ import annotations

import json

import pytest

from sedition.packets import variants

#: There are no draft twins in the released E01-E03 set. The synthetic refusal
#: tests below keep the DRAFT path exercised even when every shipped twin has
#: completed review.
TWINS: tuple[str, ...] = ()

#: The live twins, with the reviewer and date their status must name.
#:
#: Attribution is checked per twin, not as one shared string, because E02's
#: pair carries a different reviewer and review date from E01 and E03.
REVIEWED_TWINS = {
    "E01-SS": ("Reviewer A", "2026-08-25"),
    "E01-MS": ("Reviewer A", "2026-08-25"),
    "E02-SS": ("Reviewer B", "2026-08-27"),
    "E02-MS": ("Reviewer B", "2026-08-27"),
    "E03-SS": ("Reviewer A", "2026-08-25"),
    "E03-MS": ("Reviewer A", "2026-08-25"),
}

@pytest.fixture(autouse=True)
def _clear_cache():
    """`control_packet` is lru_cached, so a status change is invisible until the
    cache is dropped. Without this the tests below pass on stale entries."""
    variants.control_packet.cache_clear()
    yield
    variants.control_packet.cache_clear()


def _write(tmp_path, monkeypatch, status, packet_id="E01-SS"):
    src = variants.TWINS_DIR / f"{packet_id}-control.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    if status is None:
        data.pop("status", None)
        data.pop("review", None)
    else:
        data["status"] = status
        data["review"] = {"status": status}
    (tmp_path / f"{packet_id}-control.json").write_text(
        json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(variants, "TWINS_DIR", tmp_path)
    return packet_id


def test_every_twin_on_disk_is_accounted_for_in_one_of_the_three_registries():
    """No review-artifact twin may sit outside TWINS / REVIEWED_TWINS.

    The failure this catches is the one the rename made easy: a twin file
    added or renamed without anyone deciding what its review state is, which
    would leave it unasserted in either direction.
    """
    on_disk = {p.name.replace('-control.json', '')
               for p in variants.TWINS_DIR.glob("*-control.json")}
    known = set(TWINS) | set(REVIEWED_TWINS)
    unaccounted = on_disk - known
    assert not unaccounted, f"twins with no declared review state: {sorted(unaccounted)}"


# THE REFUSAL PATH LIVES BELOW, NOT HERE, AND MUST NOT BE DELETED.
#
# `test_a_draft_twin_is_refused` and `test_a_twin_with_no_status_is_refused`
# build their subjects in a tmp dir with `_write`, so they exercise the gate
# whether or not any shipped twin is draft. Every released twin is reviewed,
# so those two synthetic tests are the thing keeping the
# refusal executed. An assertion ranging over the shipped files would pass
# over the empty set and prove nothing.

@pytest.mark.parametrize("pid,reviewer,date",
                         [(p, r, d) for p, (r, d) in REVIEWED_TWINS.items()])
def test_the_signed_off_twins_are_reviewed_and_therefore_load(pid, reviewer, date):
    """The counterpart to the refusal test, for every twin that was cleared.

    Pinned the same way the 73.6 withdrawal is: if one of these ever reverts
    to DRAFT, or is cleared without a named reviewer and a date, this fails
    and somebody has to say why.

    The attribution is checked, not just the absence of "DRAFT". A status of
    "REVIEWED" with nobody's name on it is the failure mode that produced
    73.6. The reviewer and date are checked PER TWIN rather than against one
    shared string, because the six live twins were not cleared together: E02's
    pair carries a different reviewer and a different date from E01's and
    E03's, and a single shared assertion would have let either sign-off stand
    in for the other.

    The released metadata also states that public identifier normalization did
    not alter the report content that was reviewed.
    """
    data = json.loads((variants.TWINS_DIR / f"{pid}-control.json")
                      .read_text(encoding="utf-8"))
    status = data.get("status", "")
    assert status.upper().startswith("REVIEWED"), (
        f"{pid} is no longer REVIEWED ({status!r}). If the sign-off was "
        f"withdrawn, move it into TWINS in the same commit and say why.")
    assert reviewer in status, (
        f"{pid} is cleared but does not name {reviewer}: {status!r}. An "
        f"unattributed clearance cannot be told from one nobody made.")
    assert date in status, (
        f"{pid} is cleared but does not carry {date}: {status!r}.")
    assert len(variants.resolve_packet(pid, "control").reports) == 12


def test_the_gate_can_say_yes(tmp_path, monkeypatch):
    """A gate that can only refuse is an obstacle, not a check. Uses a synthetic
    reviewed twin rather than the shipped ones, which are correctly DRAFT."""
    src = variants.TWINS_DIR / "E01-SS-control.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    data["status"] = "REVIEWED 2026-01-01 - signed off by a human"
    data["review"] = {"status": data["status"]}
    (tmp_path / "E01-SS-control.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(variants, "TWINS_DIR", tmp_path)
    assert len(variants.control_packet("E01-SS").reports) == 12


@pytest.mark.parametrize("status", [
    "DRAFT - awaiting criterion-level human review (PREREGISTRATION 46)",
    "DRAFT",
    "draft - not ready",
    "  draft  ",
])
def test_a_draft_twin_is_refused(tmp_path, monkeypatch, status):
    pid = _write(tmp_path, monkeypatch, status)
    with pytest.raises(ValueError, match="DRAFT"):
        variants.control_packet(pid)


def test_a_twin_with_no_status_is_refused(tmp_path, monkeypatch):
    """A missing status is not a pass. 'never reviewed' and 'review state lost'
    look identical from here, so neither is assumed cleared."""
    pid = _write(tmp_path, monkeypatch, None)
    with pytest.raises(ValueError, match="no review status"):
        variants.control_packet(pid)


def test_a_nested_review_status_is_also_read(tmp_path, monkeypatch):
    """The twins use a top-level `status`. If a later edit nests it under
    `review`, the gate must not silently stop checking."""
    src = variants.TWINS_DIR / "E01-SS-control.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    data.pop("status", None)
    data["review"] = {"status": "DRAFT - nested"}
    (tmp_path / "E01-SS-control.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(variants, "TWINS_DIR", tmp_path)
    with pytest.raises(ValueError, match="DRAFT"):
        variants.control_packet("E01-SS")


def test_the_escape_hatch_works_and_is_off_by_default(tmp_path, monkeypatch):
    """Review tooling has to read the file the gate blocks. That is the only
    legitimate bypass, and it must be OFF in the committed state."""
    assert variants.ALLOW_DRAFT_TWINS is False, (
        "ALLOW_DRAFT_TWINS is committed as True; every scored run would accept "
        "draft stimuli")
    pid = _write(tmp_path, monkeypatch, "DRAFT - x")
    with pytest.raises(ValueError):
        variants.control_packet(pid)
    variants.control_packet.cache_clear()
    monkeypatch.setattr(variants, "ALLOW_DRAFT_TWINS", True)
    assert len(variants.control_packet(pid).reports) == 12


@pytest.mark.parametrize("pid", sorted(REVIEWED_TWINS))
def test_threat_packets_are_untouched_by_the_gate(pid):
    """Repointed 2026-08-26 from TWINS, which is now empty.

    Parametrizing over an emptied registry collects ZERO cases and reports as
    a skip, which is how a guard stops guarding without anything turning red.
    The subject here is the live packet ids, which is what it always meant:
    the DRAFT gate applies to twins and must never touch a threat packet.
    """
    assert len(variants.resolve_packet(pid, "threat").reports) == 12
