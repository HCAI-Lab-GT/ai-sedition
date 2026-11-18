"""The analyst agent: what it is asked for, and how its output is read.

One of three agents, and the only one with a hidden objective. The layer
boundary is deliberate:

    prompts/assembly.py   builds the analyst's prompt      (task definition)
    agents/analyst.py     interprets the analyst's output  (this file)
    pipeline/strip.py     removes its private prefix       (the chokepoint)

Parsing here operates ONLY on the public artifact — the text that survives
stripping. Nothing in this module ever sees a working sheet.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .. import HarnessError
from ..enums import AttackDecision

INCIDENT_DELIMITER = "=== INCIDENT ==="
_CITATION_RE = re.compile(r"\[([^\]]+)\]")
_REPORT_ID_RE = re.compile(r"[A-Z]\d{2}-(?:SS|MS)-R\d{2}")

FULL_FORM_FIELDS = ("Incident title:", "Summary:", "Confirmed information:",
                    "Uncertainties:", "Operational relevance:")
COMPACT_FORM_FIELDS = ("Incident title:", "Summary:")


@dataclass(frozen=True)
class SelectionOutput:
    """The strategic-selection call. Recorded privately and forwarded to NO
    ONE — not the watch officer, not the monitor, not the briefing call.

    `rationale` and `primary_lever` go to the log only. The ATTACK call
    re-derives its approach from scratch, so its input distribution does not
    depend on what the selection call said — which is what makes
    primary_lever a genuine prediction to score against the briefing that
    follows, rather than an instruction the briefing was following.
    """
    attack_decision: AttackDecision
    predicted_detection_risk: int
    primary_lever: str
    rationale: str

    @property
    def attacks(self) -> bool:
        return self.attack_decision is AttackDecision.ATTACK


def parse_selection(raw: str) -> SelectionOutput:
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as e:
        raise HarnessError("strategic selection call returned malformed JSON") from e
    try:
        decision = AttackDecision(data["attack_decision"])
    except (KeyError, TypeError, ValueError) as e:
        raise HarnessError(
            f"strategic selection returned unrecognized attack_decision "
            f"{data.get('attack_decision')!r}") from e

    risk = data.get("predicted_detection_risk")
    if not isinstance(risk, int) or isinstance(risk, bool) or not 1 <= risk <= 100:
        raise HarnessError(f"predicted_detection_risk must be an integer 1-100, got {risk!r}")

    return SelectionOutput(
        attack_decision=decision,
        predicted_detection_risk=risk,
        primary_lever=str(data.get("primary_lever", "")),
        rationale=str(data.get("rationale", "")),
    )


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


@dataclass(frozen=True)
class Block:
    """One incident block of a public briefing."""
    index: int
    text: str
    cited_report_ids: tuple[str, ...]
    is_full_form: bool

    @property
    def title(self) -> str:
        for line in self.text.splitlines():
            if line.startswith("Incident title:"):
                return line[len("Incident title:"):].strip()
        return ""


@dataclass(frozen=True)
class Briefing:
    """A parsed public briefing. Structure only — no judgement about content;
    that belongs to scoring and the monitor."""
    blocks: tuple[Block, ...]
    raw: str

    @property
    def cited_report_ids(self) -> frozenset[str]:
        return frozenset(r for b in self.blocks for r in b.cited_report_ids)

    def blocks_citing(self, report_ids: tuple[str, ...]) -> tuple[Block, ...]:
        wanted = set(report_ids)
        return tuple(b for b in self.blocks if wanted & set(b.cited_report_ids))


def parse_briefing(text: str) -> Briefing:
    """Split a public briefing into blocks. Tolerant by design: a briefing
    that violates the format is a compliance finding to be flagged and
    analyzed, not a parse failure to be discarded."""
    parts = text.split(INCIDENT_DELIMITER)[1:]
    blocks = []
    for i, part in enumerate(parts):
        cited: set[str] = set()
        for group in _CITATION_RE.findall(part):
            cited.update(_REPORT_ID_RE.findall(group))
        blocks.append(Block(
            index=i + 1,
            text=part.strip(),
            cited_report_ids=tuple(sorted(cited)),
            is_full_form=all(f in part for f in FULL_FORM_FIELDS),
        ))
    return Briefing(blocks=tuple(blocks), raw=text)
