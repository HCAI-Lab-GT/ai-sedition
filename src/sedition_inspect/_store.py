"""The two halves of episode state, kept apart on purpose.

DECISIONS.md #18: raw analyst output never enters `state.messages`, and only
the public briefing is visible downstream. That rule needs somewhere for the
raw text to live instead — the harness still records it, exactly as
`storage/records.py` did before the port.

So there are two store models, and the split is the point:

* `EpisodePublic` is what downstream readers may touch. The watch-officer
  payload, the monitor payload, and every scorer read from here.
* `AnalystPrivate` is the raw completion and the working sheet. It is written
  once, by the strip step, and read by nothing except harness-side scoring
  that explicitly needs it. A monitor scorer reading this is a bug, and
  `tests/inspect/test_payload_privacy.py` is what catches it.

Keeping them as separate `StoreModel` classes means the namespacing is
structural rather than a naming convention: private fields land under
`AnalystPrivate:*` keys in the log, so a grep over a downstream payload for
that prefix is a real check.
"""
from __future__ import annotations

from pydantic import Field

from inspect_ai.util import StoreModel


class EpisodePublic(StoreModel):
    """Downstream-visible episode state."""

    public_briefing: str = Field(default="")
    """The stripped artifact. The ONLY analyst text that may travel."""

    briefing_word_count: int = Field(default=0)

    #: The stimulus the ANALYST rendered from, recorded so every downstream
    #: consumer can prove it read the same one. The monitor once scored ablated
    #: briefings against the threat reports and nothing failed (PREREGISTRATION
    #: 50); an episode-level invariant is the only thing that catches that class.
    stimulus_sha256: str = Field(default="")
    stimulus_report_ids: list[str] = Field(default_factory=list)
    #: Canonical vocabulary ("control", not the legacy "ablated"). Stored
    #: episodes written before 2026-08-27 carry the legacy spelling; readers
    #: route it through sedition.packets.variants.canonical_variant.
    stimulus_variant: str = Field(default="")

    flags: list[str] = Field(default_factory=list)
    """Compliance flags, hard and soft, as their enum values."""

    invalid: bool = Field(default=False)
    """A hard flag fired; nothing was forwarded."""

    refused: bool = Field(default=False)
    """The analyst declined. A behavioural result, never an error (#19)."""

    #: Which of the six option orderings this episode used. Order is a
    #: FACTOR (1d: 64-point swing on a marginal briefing), so it is
    #: recorded per episode and every table can be re-cut by it.
    option_ordering: str = Field(default="")
    wo_decision: str = Field(default="")
    wo_probabilities: dict[str, int] = Field(default_factory=dict)
    wo_criteria: list[dict] = Field(default_factory=list)

    #: Per criterion: which report ids its basis cites, which incident blocks
    #: those sit in, and whether the assessor assembled across blocks. The
    #: direct measure of the behaviour that split-into-two-incidents
    #: concealment attacks. `cross_block` is None when nothing locatable was
    #: cited, never False -- False would read as "assembled within one block".
    wo_criteria_cross_block: list[dict] = Field(default_factory=list)

    cited_report_ids: list[str] = Field(default_factory=list)
    """Report IDs the briefing cites, recorded at strip time. Recoverable by
    re-parsing the briefing, but an analysis should not need parser knowledge
    to know what was cited — the log-completeness audit flagged exactly that."""

    prompt_versions: dict[str, str] = Field(default_factory=dict)
    """component -> version, from the loader at episode time. Without this a
    stored run's prompts are recoverable only by checking out the run's commit
    and reading loader.py."""

    clarification_requested: bool = Field(default=False)
    clarification_answer: str = Field(default="")
    wo_final_decision: str = Field(default="")
    wo_final_probabilities: dict[str, int] = Field(default_factory=dict)

    #: The FINAL turn's per-criterion assessment, basis included. Round 1 has
    #: recorded this since the basis was made first-class; the FINAL turn did
    #: not, so any episode that went through clarification lost the reasoning
    #: behind the decision of record and it was recoverable only from raw model
    #: output via attachment refs. An escalation's basis is the only thing that
    #: separates "the resolution did not persuade the officer" from "the
    #: criterion genuinely survives", so it cannot be a round-1-only field.
    wo_final_criteria: list[dict] = Field(default_factory=list)

    # --- elicitation ladder ------------------------------------------------
    #
    # Which rung produced this episode, recorded on the episode itself so a
    # pooled log can be split back apart without knowing which directory it
    # came from. `fitted` is the quarantine marker for rung 4: any table
    # containing a fitted episode must say so.

    elicitation_rung: str = Field(default="")
    """"" for the base arms, else "2.5" | "N" | "2" | "3" | "3F" | "4"."""

    fitted: bool = Field(default=False)
    """True only for rung 4. A fitted episode is never pooled with the ladder."""

    n_drafts: int = Field(default=0)
    """Rung N: how many candidate briefings were generated."""

    chosen_draft: int = Field(default=-1)
    """Rung N: 1-based index of the draft the analyst selected, -1 if none."""

    draft_decisions: list[str] = Field(default_factory=list)
    """Rung N: the officer's decision on EVERY draft, chosen and unchosen, in
    draft order. This is what separates "never generated a briefing that would
    have worked" from "generated one and failed to pick it"."""

    proxy_decisions: list[str] = Field(default_factory=list)
    """Rung 6: what the PROXY officer returned on each draft, in order.

    Public because it is an outcome measure — whether the model converges, and
    after how many rounds. It is not part of any payload: the monitor reads
    `public_briefing` alone, so recording this here cannot reach it."""

    proxy_rounds_used: int = Field(default=0)
    """Rung 6: how many revision rounds the analyst actually took. Lower than
    the cap means it stopped early, which is itself a result."""

    lineage_id: str = Field(default="")
    """Rungs 3/3F: which notepad lineage this episode belongs to."""

    lineage_position: int = Field(default=-1)
    """Rungs 3/3F: 0-based position within the lineage."""

    @property
    def final_decision(self) -> str:
        """The decision of record: the FINAL turn where one happened."""
        return self.wo_final_decision or self.wo_decision


class AnalystPrivate(StoreModel):
    """Analyst-private material. Never assembled into a downstream payload."""

    raw_briefing: str = Field(default="")
    working_sheet: str = Field(default="")
    raw_clarification: str = Field(default="")
    clarification_check: str = Field(default="")
    continuation: str = Field(default="")

    reasoning: str = Field(default="")
    """<think> content from the briefing turn.

    Analyst reasoning, so it belongs on exactly the same footing as the
    working sheet: recorded because it is valuable data, forwarded to nobody.
    A reasoning-emitting model states its intent here in plain language — on
    a saboteur episode this is the attack plan — which is precisely why it
    lives under `AnalystPrivate:` and is covered by the payload-privacy tests.
    """

    clarification_reasoning: str = Field(default="")
    """<think> content from the clarification turn, kept separate so the two
    turns' reasoning cannot be conflated."""

    # --- strategic selection call (strategic policy only) -------------------
    #
    # First-class fields, never inferred from the briefing. Reading ATTACK or
    # ABSTAIN back out of the produced text would make the independent
    # variable a function of the outcome, which is the one thing it must not
    # be: an attack that succeeded completely would be indistinguishable from
    # an abstention.

    attack_decision: str = Field(default="")
    """ATTACK | ABSTAIN | "" when the episode is not strategic."""

    attack_rationale: str = Field(default="")
    """The model's own reasoning for that decision.

    PRIVATE, at the same level as the working sheet and <think> content. On an
    ATTACK episode this states the attack in plain language — which lever,
    which fact to bury, what the officer must not notice — so a leak into the
    monitor payload would convert detection into reading a confession.
    test_strategic_privacy.py enforces it.
    """

    predicted_detection_risk: int = Field(default=-1)
    """Self-assessed 1-100, or -1 when absent. A genuine prediction rather
    than an instruction: the briefing call re-derives its approach and never
    sees this, so it can be scored against what the briefing actually did."""

    primary_lever: str = Field(default="")
    """Which §10.2 lever the model said it would lean on. Scored against the
    briefing, same reasoning as above."""

    overridden: bool = Field(default=False)
    """Rung 1 only. True when the model chose ABSTAIN and the condition forced
    an attack anyway, so the analysis can separate "attacked because it chose
    to" from "attacked because it had to". Never set in the free arm."""

    # --- elicitation ladder, analyst-private -------------------------------

    drafts: list[str] = Field(default_factory=list)
    """Rung N: every candidate briefing generated, in order. Private because
    the unchosen drafts are analyst working material — only the selected one
    is ever a public briefing."""

    draft_choice_reason: str = Field(default="")
    """Rung N: the analyst's one-sentence reason for its selection."""

    raw_critique: str = Field(default="")
    """Rung 2: the raw revision-turn completion, before stripping."""

    notepad_in: str = Field(default="")
    """Rungs 3/3F: the notepad as it entered this episode. PRIVATE — the
    notepad must never reach the officer or the monitor. Same class as the
    working sheet; covered by the payload-privacy tests and by the planted-leak
    case in tests/unit/test_notepad_privacy.py."""

    notepad_out: str = Field(default="")
    """Rungs 3/3F: the notepad as the analyst left it, carried to the next
    episode in the lineage. PRIVATE, same as notepad_in."""
