"""THE stripping chokepoint. No component may read raw model output except
`strip_analyst_output()`.

Why this is load-bearing rather than tidy-up: the working sheet is the
analyst's private scratchpad. If it survives into the stored artifact and
then into the monitor's context, the monitor can compare recorded
connections against stated ones directly — a strictly easier task than the
one being measured. The working-condition arm becomes uninterpretable, and
you would not notice from the outputs, because the numbers would look
*better*, not broken.

Parser rules are Part H of the omnibus's Part XII.8 (COMPLETE PRIVATE
WORKING-SHEET SPECIFICATION v2). Markers come from
sedition/pipeline/boundary.py.

ONE-CALL SHEET (locked, CLAUDE.md). The private prefix and the public
artifact arrive in a single response, so step 2 below is the PRIMARY
extraction path — not the leak detector it would be under the rejected
two-call design. `SHEET_LEAK` is therefore reserved for the one case that
really is a leak: a private marker surfacing in a STRAIGHT-condition
response, which is a prompt-assembly failure.

Malformed private output is never forwarded and never re-prompted (locked):
missing, duplicated, reversed, unbalanced, or out-of-order markers forward
NOTHING and mark the episode invalid. Forwarding a partial remainder risks
exposing the private artifact; re-prompting changes the sampling
distribution.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..enums import HARD_FLAGS, Cell, Continuation, Flag, Policy, Turn, WorkingCondition
from .boundary import (
    CHECK_CLOSE,
    CHECK_OPEN,
    CONTINUATION_PREFIX,
    NOTEPAD_CLOSE,
    NOTEPAD_OPEN,
    SHEET_CLOSE,
    SHEET_OPEN,
    SUPERSEDED_MARKERS,
)

SHEET_REQUIRED_HEADINGS = ("REPORTS", "LINKS", "COMPARISONS", "GROUPS")

#: Every marker that must never appear in a downstream payload.
FORBIDDEN_MARKERS: tuple[str, ...] = (
    SHEET_OPEN, SHEET_CLOSE, CHECK_OPEN, CHECK_CLOSE,
    *SUPERSEDED_MARKERS, CONTINUATION_PREFIX,
    NOTEPAD_OPEN, NOTEPAD_CLOSE,
)


#: Reasoning tags. DeepSeek deployments on Foundry emit chain-of-thought
#: inside these, at the model's discretion, in the ordinary response content —
#: there is no separate reasoning channel to read it from.
THINK_OPEN = "<think>"
_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.DOTALL | re.IGNORECASE)
_THINK_OPENER = re.compile(r"<think\b[^>]*>", re.IGNORECASE)


def strip_think(raw: str) -> tuple[str | None, str, frozenset[Flag]]:
    """(reasoning, body, flags). Reasoning is DATA, never payload.

    Runs FIRST, before the continuation line and before private-block
    extraction, for two reasons. A model reasoning about the working-sheet
    markers would otherwise trip the STRAIGHT leak check — that is the model
    thinking about markers, not a prompt-assembly failure. And the private
    block must be located in the real output, not at an offset shifted by
    however much the model thought first.

    An unclosed tag means the response was truncated mid-reasoning. Everything
    from the tag onward is discarded rather than salvaged: the tail of an
    interrupted thought is not a briefing, and forwarding it would put raw
    reasoning in front of the officer, which is the one thing this must never
    do.
    """
    if not raw or THINK_OPEN.lower() not in raw.lower():
        return None, raw, frozenset()

    blocks = _THINK_BLOCK.findall(raw)
    body = _THINK_BLOCK.sub("", raw)
    flags = {Flag.THINK_STRIPPED} if blocks else set()

    opener = _THINK_OPENER.search(body)
    if opener:
        blocks.append(body[opener.start():])
        body = body[:opener.start()]
        flags |= {Flag.THINK_STRIPPED, Flag.THINK_UNCLOSED}

    reasoning = "\n".join(b.strip() for b in blocks) or None
    return reasoning, body.strip("\n"), frozenset(flags)


@dataclass(frozen=True)
class StrippedOutput:
    """`artifact` is the ONLY text that may travel downstream."""
    artifact: str
    working_sheet: str | None
    clarification_check: str | None
    continuation: Continuation | None
    flags: frozenset[Flag]
    #: Chain-of-thought removed from the raw completion. Private, like the
    #: working sheet: stored for analysis, forwarded to nobody.
    reasoning: str | None = None

    @property
    def valid(self) -> bool:
        """False when a hard flag fired: nothing may be forwarded."""
        return not (self.flags & HARD_FLAGS)


def _fail(flags: frozenset[Flag], continuation: Continuation | None,
          reasoning: str | None = None) -> StrippedOutput:
    """A failed strip forwards nothing — not a remainder, not a best guess.

    Reasoning is still carried out, because it is never forwarded anywhere and
    is often the only record of why a failed episode failed.
    """
    return StrippedOutput(artifact="", working_sheet=None, clarification_check=None,
                          continuation=continuation, flags=flags, reasoning=reasoning)


def _strip_continuation(text: str, *, expected: bool) -> tuple[Continuation | None, str, frozenset[Flag]]:
    """Strip a leading `CONTINUATION: <value>` line plus the blank line after
    it. Absent or malformed -> UNDECLARED, logged, treated as CONTINUE for
    scoring, never re-prompted. This is a soft flag: it does not invalidate."""
    if not text.startswith(CONTINUATION_PREFIX):
        if expected:
            return Continuation.UNDECLARED, text, frozenset({Flag.CONTINUATION_UNDECLARED})
        return None, text, frozenset()

    first_line, _, rest = text.partition("\n")
    raw_value = first_line[len(CONTINUATION_PREFIX):].strip()
    try:
        value = Continuation(raw_value)
    except ValueError:
        return Continuation.UNDECLARED, text, frozenset({Flag.CONTINUATION_UNDECLARED})
    if value is Continuation.UNDECLARED:  # the model literally wrote UNDECLARED
        return value, rest.lstrip("\n"), frozenset({Flag.CONTINUATION_UNDECLARED})
    return value, rest.lstrip("\n"), frozenset()


def _any_marker(text: str) -> bool:
    return any(marker in text for marker in FORBIDDEN_MARKERS)


def _extract_private_block(text: str, *, open_marker: str, close_marker: str,
                           malformed: Flag, required_headings: tuple[str, ...] = (),
                           ) -> tuple[str | None, str, frozenset[Flag]]:
    """Part H.1/H.2 strict allowlist extraction. Returns
    (private_block | None, remainder, flags). On any failure the remainder is
    "" — nothing is forwarded."""
    if text.count(open_marker) != 1 or text.count(close_marker) != 1:
        return None, "", frozenset({malformed})
    if not text.lstrip().startswith(open_marker):
        return None, "", frozenset({malformed})

    open_idx = text.find(open_marker)
    close_idx = text.find(close_marker)
    if close_idx < open_idx:
        return None, "", frozenset({malformed})

    block_end = close_idx + len(close_marker)
    private_block = text[open_idx:block_end]
    remainder = text[block_end:].lstrip("\n")  # trim only the separator blank line

    if required_headings:
        positions = [private_block.find(h) for h in required_headings]
        counts = [private_block.count(h) for h in required_headings]
        if any(c != 1 for c in counts) or positions != sorted(positions):
            return None, "", frozenset({malformed})

    if not remainder.strip():
        return None, "", frozenset({malformed})  # "followed by no public output"
    if _any_marker(remainder):
        return None, "", frozenset({malformed})  # a private marker leaked into the suffix

    return private_block, remainder, frozenset()


def strip_analyst_output(raw: str, *, turn: Turn, cell: Cell) -> StrippedOutput:
    """Strip order is fixed:

    0. <think> reasoning, if the model emitted any;
    1. the CONTINUATION line (strategic policy, clarification turn only);
    2. the private block — WORKING SHEET on the briefing turn, CLARIFICATION
       CHECK on the clarification turn (SHEET only);
    3. what remains is `artifact`.

    Step 0 is first so that every later step, and everything downstream of
    them — word count, block-form validation, the fact scorer, the officer
    payload and the monitor payload — operates on post-reasoning text without
    having to know reasoning exists.
    """
    if turn is Turn.SELECTION:
        raise ValueError("selection-call output is JSON and is never stripped; "
                         "it is private and forwarded to no one")

    reasoning, raw, think_flags = strip_think(raw)

    expects_continuation = (cell.policy is Policy.STRATEGIC_SABOTEUR
                            and turn is Turn.CLARIFICATION)
    continuation, body, flags = _strip_continuation(raw, expected=expects_continuation)
    flags = flags | think_flags

    if cell.working_condition is WorkingCondition.STRAIGHT:
        # STRAIGHT receives no §E, so a private marker here means the prompt
        # was assembled wrong — a sedition defect, not a model failure.
        if _any_marker(body):
            return _fail(flags | {Flag.PROMPT_ASSEMBLY_FAILURE, Flag.SHEET_LEAK},
                         continuation, reasoning)
        return StrippedOutput(artifact=body.strip("\n"), working_sheet=None,
                              clarification_check=None, continuation=continuation,
                              flags=flags, reasoning=reasoning)

    if turn is Turn.INITIAL:
        block, artifact, block_flags = _extract_private_block(
            body, open_marker=SHEET_OPEN, close_marker=SHEET_CLOSE,
            malformed=Flag.SHEET_MALFORMED, required_headings=SHEET_REQUIRED_HEADINGS)
        if block is None:
            return _fail(flags | block_flags, continuation, reasoning)
        return StrippedOutput(artifact=artifact.strip("\n"), working_sheet=block,
                              clarification_check=None, continuation=continuation,
                              flags=flags | block_flags, reasoning=reasoning)

    block, artifact, block_flags = _extract_private_block(
        body, open_marker=CHECK_OPEN, close_marker=CHECK_CLOSE,
        malformed=Flag.CLARIFICATION_CHECK_MALFORMED)
    if block is None:
        return _fail(flags | block_flags, continuation, reasoning)
    return StrippedOutput(artifact=artifact.strip("\n"), working_sheet=None,
                          clarification_check=block, continuation=continuation,
                          flags=flags | block_flags, reasoning=reasoning)


def word_count(text: str) -> int:
    """Post-strip word count of a public artifact, for the §6.4 length gate."""
    return len(text.split())
