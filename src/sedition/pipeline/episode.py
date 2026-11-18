"""Episode identity.

The episode id is the unit of reference across the whole experiment: it names
a run directory, a log sample, and a row in the analysis. Its shape encodes
the factorial — event, source version, matched block, cell — so an id sorts
into a readable order and can be parsed back into its factors.

    E01-MS-b00-honest_straight

Under Inspect this becomes `Sample.id`. Ids are explicit rather than
positional because Inspect disables sample reuse on retry when ids are
auto-assigned and the dataset is shuffled (DECISIONS.md #17).

The episode state machine that used to live here went with the orchestrator:
Inspect's `TaskState` owns execution state now, and the terminal conditions it
tracked are recorded as store fields instead (`EpisodePublic.invalid`,
`.refused`).
"""
from __future__ import annotations

__all__ = ["episode_id"]


def episode_id(event: str, version: str, block_index: int, cell_id: str,
               packet_variant: str = "threat") -> str:
    """Human-readable, sortable, unique.

    The variant is part of the identity, not decoration. A variant run and a
    threat run at the same packet, block and cell used to produce byte-identical
    ids, so the two collided in a shared log directory and the second silently
    read as a resume of the first. `threat` is omitted so every id already
    committed keeps its exact spelling.
    """
    base = f"{event}-{version}-b{block_index:02d}-{cell_id}"
    return base if packet_variant == "threat" else f"{base}-{packet_variant}"
