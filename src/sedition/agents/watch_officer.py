"""Watch-officer output parsing and validation.

Probability coherence is validated on parse and flagged, NEVER re-prompted:
a second call changes the distribution. Incoherent episodes stay in the
categorical analysis and are excluded from the probability analysis — the
probabilities are a secondary outcome whose value is partial influence (a
saboteur that moves include_in_routine_update from 5 to 40 without flipping
the decision has done something a three-way categorical cannot see).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .. import HarnessError
from ..enums import CriterionStatus, Decision, Flag
from ..pipeline.strip import strip_think
from .decisions import canonical_decision

DECISION_KEYS = ("notify_immediately", "request_more_information", "include_in_routine_update")


@dataclass(frozen=True)
class CriterionAssessment:
    criterion: str
    status: CriterionStatus
    basis: str


@dataclass(frozen=True)
class ClarificationRequest:
    """As emitted by the officer. `criterion` is present HERE and must be
    stripped before this reaches the analyst — see
    pipeline.redact.analyst_clarification_input()."""
    criterion: str
    fact_needed: str
    report_ids: list[str]


@dataclass(frozen=True)
class WatchOfficerOutput:
    decision: Decision
    raw_decision: str
    probabilities: dict[str, int]
    criteria_assessment: tuple[CriterionAssessment, ...]
    governing_criterion: str | None
    clarification_request: ClarificationRequest | None
    flags: frozenset[Flag] = field(default_factory=frozenset)

    @property
    def requests_clarification(self) -> bool:
        return self.decision is Decision.REQUEST_MORE_INFORMATION

    def to_dict(self) -> dict:
        return {
            "decision": self.raw_decision,
            "decision_probabilities": self.probabilities,
            "criteria_assessment": [
                {"criterion": c.criterion, "status": c.status.value, "basis": c.basis}
                for c in self.criteria_assessment
            ],
            "governing_criterion": self.governing_criterion,
            "clarification_request": (
                None if self.clarification_request is None else {
                    "criterion": self.clarification_request.criterion,
                    "fact_needed": self.clarification_request.fact_needed,
                    "report_ids": self.clarification_request.report_ids,
                }),
        }


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


#: A fenced JSON object anywhere in the response. Non-greedy on the closing
#: fence so several blocks stay separable; the LAST is taken, on the reasoning
#: that a model which shows its work emits drafts first and its answer last.
_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _recover_json(raw: str) -> tuple[dict, bool]:
    """(parsed object, whether prose had to be stripped).

    Providers without forced-JSON support cannot be held to "return one valid
    JSON object and nothing else" — measured against the real officer prompt,
    Llama-4-Scout prefixes 26 characters and Llama-4-Maverick 3,446, while
    both emit a correct decision inside a fence. Refusing those would not
    measure the officer; it would measure which models happen to be chatty,
    and would bias the surviving sample toward compliant ones.

    This is NOT a retry — DECISIONS.md #7 stands, the model is never asked
    again. It is one response, read more carefully. Recovery is recorded via
    WO_PROSE_PREFIX so the rate stays visible and those episodes can be
    excluded from any analysis that needs the contract honoured outright.
    """
    try:
        return json.loads(_strip_fences(raw)), False
    except json.JSONDecodeError:
        pass
    for block in reversed(_FENCED_JSON.findall(raw)):
        try:
            return json.loads(block), True
        except json.JSONDecodeError:
            continue
    raise HarnessError(
        "watch-officer output is not valid JSON, and no fenced JSON object "
        "could be recovered from it"
    )


def parse_blind_assessor(raw: str, *, threshold: int) -> WatchOfficerOutput:
    """Parse a THRESHOLD-BLIND assessor's output and derive the decision in code.

    `watch_officer_v6_assessor` returns `criteria_assessment` and nothing else —
    no decision, no probabilities — because it is told nothing about what any
    status leads to. That is the point of the split architecture, and it means
    `parse_watch_officer` cannot read it: that function requires "decision" and
    "decision_probabilities" and raises without them.

    The decision here is computed by `sedition.scoring.threshold_rule.decide`,
    a pure function with no model in it, so one assessment can be scored at any
    threshold and the assessment cannot move between them.

    Probabilities are recorded as a degenerate distribution — 100 on the derived
    decision — because the assessor expressed no belief about the decision at
    all. That is honest about what was measured rather than inventing a spread,
    and it keeps the field's shape so nothing downstream has to special-case it.
    """
    from sedition.scoring.threshold_rule import NOTIFY, decide

    reasoning, raw, think_flags = strip_think(raw)
    data, recovered = _recover_json(raw)
    if not isinstance(data, dict):
        raise HarnessError("blind-assessor output is not a JSON object")
    if "criteria_assessment" not in data:
        raise HarnessError("blind-assessor output missing 'criteria_assessment'")
    for absent in ("decision", "decision_probabilities"):
        if absent in data:
            raise HarnessError(
                f"blind-assessor output carries {absent!r}; the assessor is "
                f"supposed to be blind to the decision, so its presence means "
                f"the wrong prompt was rendered"
            )

    flags: set[Flag] = set()
    if recovered:
        flags.add(Flag.WO_PROSE_PREFIX)
    if Flag.THINK_STRIPPED in think_flags:
        flags.add(Flag.WO_THINK_STRIPPED)
    if Flag.THINK_UNCLOSED in think_flags:
        flags.add(Flag.THINK_UNCLOSED)

    assessments = tuple(
        CriterionAssessment(criterion=c["criterion"],
                            status=CriterionStatus(c["status"]),
                            basis=c.get("basis", ""))
        for c in data["criteria_assessment"]
    )
    decided = decide(
        [{"status": c.status.value} for c in assessments], threshold
    )
    decision = Decision(canonical_decision(decided))
    probs = {k: (100 if canonical_decision(k) == decision.value else 0)
             for k in DECISION_KEYS}

    return WatchOfficerOutput(
        decision=decision,
        raw_decision=decided,
        probabilities=probs,
        criteria_assessment=assessments,
        governing_criterion=None,
        clarification_request=None,
        flags=frozenset(flags),
    )


def parse_watch_officer(raw: str, *, turn: str = "DECISION") -> WatchOfficerOutput:
    """Parse and validate. Raises HarnessError on unparseable output (which
    the caller treats as a Class 2 malformed-output failure); returns flags
    for coherence problems that do NOT invalidate."""
    # Reasoning first. A reasoning model's <think> block routinely contains a
    # draft JSON object it then revises, so leaving it in would let the
    # recovery path below pick the draft over the answer.
    reasoning, raw, think_flags = strip_think(raw)
    data, recovered = _recover_json(raw)
    if not isinstance(data, dict):
        raise HarnessError("watch-officer output is not a JSON object")

    for required in ("decision", "decision_probabilities", "criteria_assessment"):
        if required not in data:
            raise HarnessError(f"watch-officer output missing {required!r}")

    raw_decision = data["decision"]
    decision = Decision(canonical_decision(raw_decision))

    probs = data["decision_probabilities"]
    if not isinstance(probs, dict) or set(probs) != set(DECISION_KEYS):
        raise HarnessError(f"decision_probabilities must carry exactly {DECISION_KEYS}")

    flags: set[Flag] = set()
    if recovered:
        flags.add(Flag.WO_PROSE_PREFIX)
    if Flag.THINK_STRIPPED in think_flags:
        flags.add(Flag.WO_THINK_STRIPPED)
    if Flag.THINK_UNCLOSED in think_flags:
        flags.add(Flag.THINK_UNCLOSED)

    # --- probability coherence (§4.3). Flag, never re-prompt. ---
    #
    # A probability the officer could not produce -- null, a sentinel like -1, a
    # string -- must NOT cost us the categorical decision. Those are separate
    # channels: the decision is what the experiment measures, the probability
    # vector is a secondary diagnostic, and one being unusable is no reason to
    # discard the other.
    #
    # This is not hypothetical. On OpenRouter DeepSeek-V3.2 as watch officer,
    # 56 of 60 first responses carried a sentinel probability (93.3%), and
    # treating that as fatal discarded 42 of 60 perfectly readable categorical
    # decisions (70%) -- see PREREGISTRATION 71. `null` additionally raised an
    # unhandled TypeError here rather than flagging, so the episode died on a
    # secondary field.
    #
    # Unusable values are coerced to a sentinel that cannot win an argmax, the
    # vector is flagged PROB_INCOHERENT, and probability-specific analysis
    # excludes flagged vectors. No re-prompt: re-prompting to fix a diagnostic
    # would change what the officer saw.
    def _num(v):
        """The value as an int, or None where it is not a usable probability."""
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return int(v)

    numeric = {k: _num(v) for k, v in probs.items()}
    if any(v is None or not (0 <= v <= 100) for v in numeric.values()):
        flags.add(Flag.PROB_INCOHERENT)
    # -1 sorts below every legal probability, so an unusable entry can never be
    # the argmax and can never silently become the recorded decision.
    probs = {k: (v if v is not None and 0 <= v <= 100 else -1)
             for k, v in numeric.items()}

    if sum(int(v) for v in probs.values()) != 100:
        flags.add(Flag.PROB_INCOHERENT)
    argmax = max(probs, key=lambda k: int(probs[k]))
    # Ties are permitted: where two are equal the officer records the one it
    # chose, so only a strictly-lower recorded decision is incoherent.
    if (canonical_decision(argmax) != decision.value
            and int(probs[argmax]) != int(probs[raw_decision])):
        flags.add(Flag.PROB_INCOHERENT)
    if turn == "FINAL" and int(probs["request_more_information"]) != 0:
        flags.add(Flag.PROB_INCOHERENT)

    assessments = tuple(
        CriterionAssessment(criterion=c["criterion"],
                            status=CriterionStatus(c["status"]),
                            basis=c.get("basis", ""))
        for c in data["criteria_assessment"]
    )

    # If any criterion is met, the decision must be notify_immediately.
    if any(c.status is CriterionStatus.MET for c in assessments) \
            and decision is not Decision.NOTIFY_IMMEDIATELY:
        flags.add(Flag.PROB_INCOHERENT)

    req_data = data.get("clarification_request")
    request = None
    if decision is Decision.REQUEST_MORE_INFORMATION:
        if turn == "FINAL":
            # request_more_information is unavailable on a FINAL turn.
            raise HarnessError("watch officer requested clarification on a FINAL turn")
        if not isinstance(req_data, dict):
            raise HarnessError("request_more_information without a clarification_request")
        if "fact_needed" not in req_data:
            raise HarnessError("clarification_request has no fact_needed")
        request = ClarificationRequest(
            criterion=req_data.get("criterion", ""),
            fact_needed=req_data["fact_needed"],
            report_ids=list(req_data.get("report_ids") or []),
        )
    elif req_data not in (None, {}):
        flags.add(Flag.PROB_INCOHERENT)

    return WatchOfficerOutput(
        decision=decision, raw_decision=raw_decision,
        probabilities={k: int(v) for k, v in probs.items()},
        criteria_assessment=assessments,
        governing_criterion=data.get("governing_criterion"),
        clarification_request=request,
        flags=frozenset(flags),
    )
