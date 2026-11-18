"""Every ablated twin declares the packet it resolves.

WHY THIS EXISTS. The twins were authored before `parent_packet_id` and did not
carry it. The 2026-08-23 integration of reviewer-c-branch introduced a loader that
requires the field and rejects a twin without it:

    ValueError: E01-SS-ablated.json: parent_packet_id is None, expected 'E01-SS'

That surfaced as ~200 failures, and it is the kind of schema drift that is
invisible until two branches meet. The field is now mandatory on this side too,
so the two twin families agree before they are merged rather than after.

DELIBERATELY NOT OPTIONAL. A loader that fell back to inferring the parent from
the filename would be a second code path doing the same job, and it would
silently do the WRONG thing the first time a twin's parent was not itself --
which is exactly the case on reviewer-c-branch, where E01-MS-ablated.json resolves
E01-MS. Absent means broken, not "assume the obvious".
"""
from __future__ import annotations

import json

import pytest

from sedition.packets.variants import TWINS_DIR

TWINS = sorted(TWINS_DIR.glob("E0[123]-*-control.json"))


def test_the_twin_set_is_the_expected_six():
    """Guards the parametrisation below from passing vacuously on an empty glob."""
    assert len(TWINS) == 6, f"expected 6 control twins, found {[p.name for p in TWINS]}"


@pytest.mark.parametrize("path", TWINS, ids=lambda p: p.name)
def test_every_twin_declares_its_parent(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    assert "parent_packet_id" in d, (
        f"{path.name} has no parent_packet_id. A twin must name the packet it "
        f"resolves; absent is broken, not 'infer it from the filename'.")
    assert d["parent_packet_id"], f"{path.name}: parent_packet_id is empty"


@pytest.mark.parametrize("path", TWINS, ids=lambda p: p.name)
def test_an_ablated_twin_resolves_its_own_packet(path):
    """These six are resolution twins: the twin of E01-MS *is* E01-MS with its
    decisive elements resolved, so the parent is the packet itself. A twin whose
    parent differs is a different construct and belongs to a different set."""
    d = json.loads(path.read_text(encoding="utf-8"))
    assert d["parent_packet_id"] == d["packet_id"], (
        f"{path.name}: packet_id {d['packet_id']!r} but parent "
        f"{d['parent_packet_id']!r}")


@pytest.mark.parametrize("path", TWINS, ids=lambda p: p.name)
def test_the_filename_agrees_with_the_declared_packet(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == f"{d['packet_id']}-control.json", (
        f"{path.name} declares packet_id {d['packet_id']!r}")


@pytest.mark.parametrize("path", TWINS, ids=lambda p: p.name)
def test_adding_the_field_did_not_disturb_the_reports(path):
    """The field was inserted, not regenerated. Twelve reports, ids matching the
    packet, every required field present."""
    d = json.loads(path.read_text(encoding="utf-8"))
    reports = d["reports"]
    assert len(reports) == 12, f"{path.name}: {len(reports)} reports, expected 12"
    for i, r in enumerate(reports, 1):
        assert r["report_id"] == f"{d['packet_id']}-R{i:02d}", (
            f"{path.name}: report {i} has id {r['report_id']!r}")
        for field in ("serial", "precedence", "dtg", "originator", "subject",
                      "reported_status", "text"):
            assert field in r, f"{path.name}: report {i} missing {field}"
