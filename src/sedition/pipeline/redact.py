"""Recipient payload construction — the only way text reaches a downstream
agent. Route everything through these; never pass a string directly.

`assert_no_forbidden_markers()` is deliberately cheap and deliberately
raises rather than warns. It runs on every payload in every run, not only in
tests, so a regression fails the run instead of silently poisoning the data.

Recipient-specific by design. The monitor and watch officer legitimately
receive the visible notification standard, so there is no ban on the word
"criterion" — only the watch officer's *structured* criterion /
criteria_assessment / basis fields are stripped, and only from the payload
bound for the analyst (see `analyst_clarification_input`).
"""
from __future__ import annotations

from typing import Any

from .. import PrivacyLeakError
from .boundary import (
    ModelPayload,
    build_clarification_payload,
    monitor_payload,
    watch_officer_payload,
)
from .strip import FORBIDDEN_MARKERS


def assert_no_forbidden_markers(text: str, *, recipient: str = "downstream") -> None:
    """Raises PrivacyLeakError. Never warns, never returns a bool that a
    caller can ignore."""
    for marker in FORBIDDEN_MARKERS:
        if marker in text:
            raise PrivacyLeakError(
                f"{recipient} payload contains private marker {marker!r} — "
                "raw analyst output reached a downstream recipient"
            )


def redact_for_watch_officer(artifact: str, *, trigger_rules: tuple[str, ...] = ()) -> ModelPayload:
    assert_no_forbidden_markers(artifact, recipient="watch_officer")
    return watch_officer_payload(artifact, trigger_rules=trigger_rules)


def redact_for_monitor(artifact: str, *, trigger_rules: tuple[str, ...] = ()) -> ModelPayload:
    assert_no_forbidden_markers(artifact, recipient="monitor")
    return monitor_payload(artifact, trigger_rules=trigger_rules)


def analyst_clarification_input(wo_request: dict[str, Any]) -> dict[str, Any]:
    """The watch officer's clarification_request, cut down to what the analyst
    may see: fact_needed and report_ids, nothing else.

    `criterion` must never reach the analyst. The analyst is forbidden from
    referring to the policy at all, so naming a criterion creates an
    instruction conflict for honest policies — and for a saboteur it is a map
    showing precisely which fact to keep suppressing, which would inflate
    concealment success for reasons that have nothing to do with the model.
    `criteria_assessment` and `basis` are withheld for the same reason.
    """
    return build_clarification_payload(wo_request)
