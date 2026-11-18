"""Stage 1 gate: one sample, mockllm, all four calls, a scored log.

This proves the plumbing, not a result. What it asserts is that an episode
runs end to end through every role, the clarification branch fires, and all
four scorers produce values into a real `.eval` log.
"""
from __future__ import annotations

from inspect_ai import eval as inspect_eval

from sedition_inspect import sedition_briefing

from .canned import (
    BRIEFING_STRAIGHT,
    CLARIFICATION_STRAIGHT,
    MONITOR_FAITHFUL,
    OFFICER_DECISION_NOTIFY,
    OFFICER_DECISION_RMI,
    OFFICER_FINAL_NOTIFY,
    mock_model,
)

MOCK = "mockllm/model"


def _mock(*contents: str):
    """A mockllm bound to a fixed sequence of completions."""
    return mock_model(*contents)


def _roles(*, clarify: bool):
    if clarify:
        return {
            "analyst": _mock(BRIEFING_STRAIGHT, CLARIFICATION_STRAIGHT),
            "watch_officer": _mock(OFFICER_DECISION_RMI, OFFICER_FINAL_NOTIFY),
            # Two monitor outputs: a clarified episode is scored twice, once
            # on the briefing and once on the clarification response, and the
            # episode takes the higher (DECISIONS.md #22).
            "monitor": _mock(MONITOR_FAITHFUL, MONITOR_FAITHFUL),
        }
    return {
        "analyst": _mock(BRIEFING_STRAIGHT),
        "watch_officer": _mock(OFFICER_DECISION_NOTIFY),
        "monitor": _mock(MONITOR_FAITHFUL),
    }


def _run(*, clarify: bool):
    logs = inspect_eval(
        sedition_briefing(packets="E01-MS", cells="honest_straight", blocks=1),
        model=MOCK,
        model_roles=_roles(clarify=clarify),
        log_dir="logs/stage1-smoke",
        display="none",
    )
    assert len(logs) == 1
    log = logs[0]
    assert log.status == "success", log.error
    assert log.samples and len(log.samples) == 1
    return log.samples[0]


def test_clarified_episode_runs_all_four_calls_and_scores():
    sample = _run(clarify=True)

    # Four solver calls — analyst, officer, analyst, officer — plus two
    # monitor calls from the scorer: the briefing and the clarification
    # response are scored separately so a clean follow-up cannot wash out a
    # suspicious briefing (DECISIONS.md #22).
    model_events = [e for e in sample.events if e.event == "model"]
    roles = [e.role for e in model_events]
    assert roles.count("analyst") == 2, roles
    assert roles.count("watch_officer") == 2, roles
    assert roles.count("monitor") == 2, roles

    drs = sample.scores["monitor_drs"]
    assert drs.metadata["passes"] == 2
    assert drs.metadata["initial_drs"] is not None
    assert drs.metadata["clarification_drs"] is not None
    # The episode carries the worse of the two.
    assert drs.value == max(
        drs.metadata["initial_drs"], drs.metadata["clarification_drs"]
    )

    store = sample.store
    assert store["EpisodePublic:public_briefing"].startswith("=== INCIDENT ===")
    assert store["EpisodePublic:clarification_requested"] is True
    assert store["EpisodePublic:wo_decision"] == "REQUEST_MORE_INFORMATION"
    assert store["EpisodePublic:wo_final_decision"] == "NOTIFY_IMMEDIATELY"
    assert store["EpisodePublic:invalid"] is False
    assert store["EpisodePublic:refused"] is False

    # Every scorer produced a value.
    assert set(sample.scores) == {
        "atomic_facts",
        "derived_facts",
        "officer_decision",
        "target_partition",
        "monitor_drs",
    }
    assert sample.scores["officer_decision"].value == 1
    assert sample.scores["monitor_drs"].value == 0.12


def test_unclarified_episode_skips_the_branch():
    sample = _run(clarify=False)

    roles = [e.role for e in sample.events if e.event == "model"]
    assert roles.count("analyst") == 1, roles
    assert roles.count("watch_officer") == 1, roles

    store = sample.store
    assert store["EpisodePublic:clarification_requested"] is False
    # Round 1 IS the round of record when no clarification happens, and it is
    # recorded EXPLICITLY. This field used to stay empty here and a reader
    # without _store.py knowledge read it as "no final decision" — the
    # log-completeness audit called it ABSENT across a whole real run.
    assert store["EpisodePublic:wo_final_decision"] == "NOTIFY_IMMEDIATELY"
    assert store["EpisodePublic:wo_decision"] == "NOTIFY_IMMEDIATELY"
    assert sample.scores["officer_decision"].value == 1


def test_sample_identity_and_permutation_are_pinned():
    sample = _run(clarify=False)
    assert sample.id == "E01-MS-b00-honest_straight"
    perm = sample.metadata["permutation"]
    assert len(perm) == 12
    # Block 0 is canonical order, per blocks.py.
    assert perm == sorted(perm)
