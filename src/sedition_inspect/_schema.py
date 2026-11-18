"""The watch officer's response schema.

`watch_officer_v2` §10 specifies the JSON exactly; this mirrors it so the
officer call can pass `response_schema` and get structurally valid output
from providers that support it.

The schema constrains *shape*, not *coherence*. Probability coherence — three
integers summing to 100, the recorded decision being the argmax, zero
`request_more_information` on a FINAL turn — is checked by
`parse_watch_officer`, which flags rather than re-prompts (#7). Deliberate:
a schema that could enforce coherence would silently change the sampling
distribution, and an incoherent officer is a result worth recording.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DecisionProbabilities(BaseModel):
    notify_immediately: int
    request_more_information: int
    include_in_routine_update: int


class CriterionAssessmentSchema(BaseModel):
    criterion: str
    status: Literal["met", "not_met", "uncertain"]
    basis: str


class ClarificationRequestSchema(BaseModel):
    criterion: str
    fact_needed: str
    report_ids: list[str] = Field(default_factory=list)


class WatchOfficerDecision(BaseModel):
    """§10 of watch_officer_v2. `clarification_request` is null unless the
    decision is request_more_information."""

    decision: Literal[
        "notify_immediately",
        "request_more_information",
        "include_in_routine_update",
    ]
    decision_probabilities: DecisionProbabilities
    criteria_assessment: list[CriterionAssessmentSchema]
    governing_criterion: str | None = None
    clarification_request: ClarificationRequestSchema | None = None


class BlindAssessorOutput(BaseModel):
    """§5 of watch_officer_v6_assessor: per-criterion statuses and nothing else.

    The split assessor is blind to the decision by construction, and
    `parse_blind_assessor` RAISES if its output carries `decision` or
    `decision_probabilities`. Forcing `WatchOfficerDecision` on it — which is
    what `_officer_turn` does on every provider that honours a response schema
    — would therefore make the model emit exactly the fields the parser
    refuses. That never surfaced in the preregistered pilots because they ran
    on `azureai`, which cannot force JSON. This is the schema an assessor call
    must be given on a provider that can.
    """

    criteria_assessment: list[CriterionAssessmentSchema]
