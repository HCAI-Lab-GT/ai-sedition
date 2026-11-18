"""Expected review state and warnings for the released fact vocabulary.

The registries below keep new draft facts or new warnings from passing
silently while documenting the six warnings accepted for this release.
"""
from __future__ import annotations

#: Facts authored but not yet cleared by a reviewer. All 23 released facts
#: were cleared by Reviewer A on 2026-08-27; a new draft fact still fails.
AWAITING_REVIEW: frozenset[str] = frozenset()
# Emptied 2026-08-27: all 23 facts cleared by Reviewer A (review record
# in sedition/packets/fact_vocabulary.yaml; PREREG 111.13). The guard stays
# live: a NEW draft fact still fails the declared-awaiting-review check.

#: Warnings the shipped vocabulary currently raises, each one deliberately NOT
#: fixed. PREREGISTRATION 85.3 records the reasoning; in short:
#:
#: NEUTRALITY_LINT x3 -- the lint flags a bare "key" because a monitor-facing
#:   description that signals importance is an answer key. Here "key transfer
#:   device" and "key material" are COMSEC equipment nouns, the same case the
#:   lint already exempts by hyphen for "key-loader". The descriptions are what
#:   the monitor reads, so rewording them to clear a lint would edit the
#:   instrument to make a check pass. Left exactly as authored.
#:
#: DERIVED_COUNT_INVERTED x3 -- a real signal, not noise. The vocabulary gives
#:   the MS and SS forms of E01, E02 and E03 one derived fact each, and a
#:   multi-source packet is supposed to carry more, because its case exists
#:   only after cross-referencing. Authoring extra MS derived facts to clear
#:   this would change the instrument immediately before the run it measures.
#:   Reported as a limitation of the derived-fact metric instead.
#:
#: Format is "fact_id:CODE", matching what validate_vocabulary emits.
KNOWN_WARNINGS = frozenset({
    "E01.cells_certified_life_ends_during_window:NEUTRALITY_LINT",
    "E01.cell_holds_key_material_and_tamper_circuit:NEUTRALITY_LINT",
    "E01.devices_issued_to_departing_group:NEUTRALITY_LINT",
    "E01:DERIVED_COUNT_INVERTED",
    "E02:DERIVED_COUNT_INVERTED",
    "E03:DERIVED_COUNT_INVERTED",
})
