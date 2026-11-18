"""Watch-officer decision enum handling.

Locked decision #7: the raw model response is stored exactly as emitted
(watch_officer_v2 currently uses lowercase values); a canonical UPPERCASE
derived field is computed by this one tested conversion function. No
case-insensitive comparisons anywhere else in the codebase.
"""
from __future__ import annotations

from .. import HarnessError

RAW_DECISIONS = (
    "notify_immediately",
    "request_more_information",
    "include_in_routine_update",
)

CANONICAL_DECISIONS = (
    "NOTIFY_IMMEDIATELY",
    "REQUEST_MORE_INFORMATION",
    "INCLUDE_IN_ROUTINE_UPDATE",
)


def canonical_decision(raw: str) -> str:
    """Map the raw watch-officer decision string to the canonical enum.

    Accepts exactly the values watch_officer_v2 emits (lowercase) and, for
    robustness against a future prompt version flipping case, their exact
    uppercase forms. Anything else is a malformed output, not a near-miss to
    be repaired here.
    """
    if raw in RAW_DECISIONS:
        return raw.upper()
    if raw in CANONICAL_DECISIONS:
        return raw
    raise HarnessError(f"unrecognized watch-officer decision {raw!r}")
