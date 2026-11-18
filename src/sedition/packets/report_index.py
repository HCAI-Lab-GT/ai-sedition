"""Recipient-specific neutral report index.

The Watch Officer receives ID and timestamp only, in that order, with no
category, originating section, or subject line (watch_officer_v2 §1.1 —
richer information turns the index into a detection channel that bypasses
the briefing entirely: "Why the index carries no categories", all-prompts.md
IMPLEMENTATION NOTES). Canonical report-ID order is used, not the block's
shuffled presentation order — the index is a manifest, not a reading task,
so there is nothing for presentation order to affect.

The monitor's index additionally carries a category per general_monitor_v3
§2 ("ID, timestamp, category"). Building it is deferred: no source material
(scenario files or omnibus) defines what "category" means for these reports,
and the monitor is out of scope for this pass regardless (M7, blocked on the
fact vocabulary — see sedition/packets/answer_key.py's fact_vocabulary_note).
"""
from __future__ import annotations

from .build import Packet


def watch_officer_index(packet: Packet) -> str:
    reports = sorted(packet.reports, key=lambda r: r.report_id)
    return "\n".join(f"{r.report_id} | {r.dtg}" for r in reports)
