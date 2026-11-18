"""Run-time overrides for the watch officer prompt and the notification standard.

Both are declared-variant mechanisms. Nothing here modifies a registered
component or a scenario file: `watch_officer_v3` stays the registered officer
and the scenario's own standard stays on disk. An override replaces the
component or the standard text for one run, in memory.

WHY THIS EXISTS. Sections 20 through 27 were all measured with bespoke scripts
that rendered prompts directly, because the task had no way to be told which
officer or standard to use. That put three things out of reach: the
ATTACK/ABSTAIN selection call, DRS, and derived-fact scoring, all of which live
in the solver. These two parameters let a declared variant run through the real
episode pipeline instead.

Both default to empty, which is exactly the previous behaviour.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from sedition.prompts.loader import _strip_provenance_header
from sedition.prompts.registry import PromptComponent
from sedition.storage.paths import PACKAGE_ROOT, PROMPT_MODULES_DIR

#: Declared notification-standard variants live here, beside the prompt modules.
STANDARDS_DIR = PACKAGE_ROOT / "prompts" / "standards"

#: The section the standards replace. A variant file supplies section 2 only.
_SECTION_2 = re.compile(
    r"\n2\. IMMEDIATE NOTIFICATION CRITERIA\.?.*?(?=\n3\. ROUTINE UPDATE STANDARD\.)",
    re.S,
)

#: Text an assessor must never see. A split assessor is blind to the threshold
#: by construction, and a variant that reintroduces decision language would
#: silently undo that without failing anything.
_DECISION_TOKENS = (
    "notify_immediately",
    "include_in_routine_update",
    "request_more_information",
)

#: RETRACTED 2026-08-22. This list enforced section 31.4 option 3 -- no threshold
#: language in a standard. That decision was reversed after the amendment it
#: mandated moved criterion B's met-rate by 68 points (PREREGISTRATION 55), so
#: the check is gone: `v3_relational` states its threshold again, deliberately.
#:
#: The k=1/k=3 contradiction section 31 found is still real and still open. It
#: is NOT reopened by removing this guard; it is reopened because the guard was
#: enforcing an untested fix. Resolve it by changing the scored threshold or by
#: a MEASURED standard change, never by an edit assumed inert.
_THRESHOLD_PHRASES: tuple[str, ...] = ()


def officer_component(version: str) -> PromptComponent:
    """Load a declared watch-officer variant, e.g. "v6_assessor".

    The registered officer is not touched. The returned component replaces the
    `watch_officer` entry of the registry handed to the renderers, which is the
    same path a registered component takes.
    """
    if not version:
        raise ValueError("empty officer version")
    path = PROMPT_MODULES_DIR / f"watch_officer_{version}.md"
    if not path.exists():
        available = sorted(
            p.stem.removeprefix("watch_officer_")
            for p in PROMPT_MODULES_DIR.glob("watch_officer_*.md")
        )
        raise FileNotFoundError(
            f"no watch officer variant {version!r} at {path}; available: {available}"
        )
    text = _strip_provenance_header(path.read_text(encoding="utf-8"))
    if not text.strip():
        raise ValueError(f"{path} is empty after stripping its provenance header")
    return PromptComponent(name="watch_officer", version=version, text=text)


def _standard_path(name: str, event_id: str | None) -> Path:
    """Resolve a variant to a file. A per-scenario file `{name}.{event_id}.md`
    takes precedence over the generic `{name}.md`.

    The released v3 relational standard uses the generic form: one section 2
    for every scenario. A variant that edits one
    criterion of the scenario's OWN standard cannot be generic, because the
    three scenarios word the other two criteria differently and those must stay
    byte-identical. The scoped form carries that case; the generic form is
    untouched and every existing caller resolves exactly as before.

    No scoped standard is distributed in this release. The lookup remains so a
    future, explicitly reviewed per-event standard can override a generic one
    without changing the API.
    """
    if event_id:
        scoped = STANDARDS_DIR / f"{name}.{event_id}.md"
        if scoped.exists():
            return scoped
    return STANDARDS_DIR / f"{name}.md"


def standard_section2(name: str, *, event_id: str | None = None) -> str:
    """Load a declared notification-standard variant's section 2 text.

    The variant files carry an HTML provenance comment that records what was
    measured under them. It is stripped here so no part of it can reach a model.

    `event_id` selects a per-scenario file where one exists (see
    `_standard_path`); without it, or where none exists, the generic file loads.
    """
    if not name:
        raise ValueError("empty notification standard name")
    path = _standard_path(name, event_id)
    if not path.exists():
        available = sorted(p.stem for p in STANDARDS_DIR.glob("*.md"))
        raise FileNotFoundError(
            f"no notification standard {name!r} at {path}; available: {available}"
        )
    text = re.sub(r"<!--.*?-->\s*", "", path.read_text(encoding="utf-8"), count=1, flags=re.S)
    text = text.strip()
    if not text.startswith("2. IMMEDIATE NOTIFICATION CRITERIA"):
        raise ValueError(
            f"{path} does not begin with section 2 after header stripping; "
            f"starts {text[:60]!r}"
        )
    for token in _DECISION_TOKENS:
        if token in text:
            raise ValueError(
                f"{path} contains decision language {token!r}. A notification "
                f"standard states what makes a criterion true, not what follows "
                f"from it; a split assessor must never see the decision names."
            )
    return text


def apply_standard(scenario, name: str):
    """Return `scenario` with its section 2 replaced by the named variant.

    Raises rather than returning an unchanged scenario: a swap that silently
    no-ops produces a well-formed log of the wrong condition, which has happened
    in this project before and cost a run.
    """
    original = scenario.notification_standard
    match = _SECTION_2.search(original)
    if match is None:
        raise ValueError(
            "could not locate section 2 in the scenario notification standard; "
            "refusing to substitute blind"
        )
    swapped = (original[: match.start()] + "\n"
               + standard_section2(name, event_id=scenario.event_id)
               + original[match.end():])
    if swapped == original:
        raise ValueError(f"notification standard {name!r} left the scenario unchanged")
    return dataclasses.replace(scenario, notification_standard=swapped)
