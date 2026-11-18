"""Read-only experiment inputs, loaded once per process.

Everything here comes from the KEEP modules (DECISIONS.md #19). Nothing in
this file re-implements packet parsing, prompt assembly, or key derivation —
it only caches what those modules produce, because a 180-episode eval would
otherwise re-parse six scenario files and eleven prompt modules per sample.
"""
from __future__ import annotations

import dataclasses
from functools import lru_cache

from sedition.packets.answer_key import AnswerKey, load_answer_key
from sedition.packets.build import ScenarioPackage, parse_all
from sedition.packets.fact_vocabulary import FactVocabulary, load_fact_vocabulary
from sedition.prompts.loader import load_all
from sedition.prompts.registry import PromptComponent, PromptRegistry
from sedition.storage.paths import (
    ANSWER_KEY_JSON,
    HELDOUT_SCENARIOS_DIR,
    PACKAGE_ROOT,
    PROMPT_MODULES_DIR,
    SCENARIOS_DIR,
    TARGET_SLOTS,
)

FACT_VOCABULARY_YAML = PACKAGE_ROOT / "packets" / "fact_vocabulary.yaml"
#: Held-out answer key, loaded only for admitted events.
HELDOUT_ANSWER_KEY_JSON = HELDOUT_SCENARIOS_DIR / "answer_key_heldout.json"


#: Held-out events admitted for THIS PROCESS, declared by a run at startup.
#:
#: Module state rather than a parameter because `packet()` and `scenario_for()`
#: are called from deep inside the solver with only a packet id, and threading
#: an admission argument through every call site would mean the one caller that
#: forgot it silently gets the core three -- the failure this whole guard exists
#: to prevent.
_ADMITTED_HELDOUT: tuple[str, ...] = ()


@lru_cache(maxsize=4)
def _scenarios_for(admitted: tuple[str, ...]) -> dict[str, ScenarioPackage]:
    """Cached on the ADMITTED SET, which is what determines the result.

    A cache keyed on nothing would let the first admitted set win for the life
    of the process. Keying by the complete set prevents stale package reuse.
    """
    return parse_all(SCENARIOS_DIR, admit_heldout=admitted)


def scenarios() -> dict[str, ScenarioPackage]:
    return _scenarios_for(_ADMITTED_HELDOUT)


def admit_heldout(*events: str) -> tuple[str, ...]:
    """Declare held-out events runnable in this process. Returns the new set.

    Clears nothing by hand: the cache is keyed on the admitted tuple, so a
    change of admission is a different key and cannot return a stale package
    set. Refusal for void or unknown ids happens in `parse_all`, by name.
    """
    global _ADMITTED_HELDOUT
    _ADMITTED_HELDOUT = tuple(sorted(set(events)))
    # Fail fast at declaration rather than at first packet access, so a bad
    # admission is a launch error and not a mid-run one.
    _scenarios_for(_ADMITTED_HELDOUT)
    return _ADMITTED_HELDOUT


#: Which component each overlay variant swaps in. "current" swaps nothing.
#:
#: Replaces an if/elif chain that had grown to eight branches and conflicted on
#: every merge that added a variant. Same behaviour, stated as data: the branch
#: bodies were all `comps[key] = comps[f"{key}_suffix"]`, which is exactly what
#: this table says.
#:
#: TWO LINEAGES BOTH CALLED v8 -- never pool them:
#:   "permissive"   strategic_selection_v8_permissive + strategic_overlay_v8,
#:                  with v9/v10/v11 built on it.
#:   "ev" family    strategic_selection_v8_ev, authored on
#:                  review/gpt-strategic-baseline as plain "v8". Different
#:                  prompt, different measurement. Selection-only: the briefing
#:                  overlay stays v6, so an ATTACK under any ev arm writes its
#:                  briefing the way the published arms do and briefings stay
#:                  comparable.
OVERLAY_VARIANTS: dict[str, dict[str, str]] = {
    "current": {},
    # v7. Repoints the basic arm as well as the strategic pair -- the only
    # variant that does, and long-standing.
    "balanced": {
        "basic_saboteur": "basic_saboteur_balanced",
        "strategic_overlay": "strategic_overlay_balanced",
        "strategic_selection": "strategic_selection_balanced",
    },
    # Strategic-only variants. basic_saboteur stays v6 under every one of these,
    # so the basic arm remains comparable across all of them.
    "permissive": {
        "strategic_overlay": "strategic_overlay_permissive",
        "strategic_selection": "strategic_selection_permissive",
    },
    "gist": {
        "strategic_overlay": "strategic_overlay_gist",
        "strategic_selection": "strategic_selection_gist",
    },
    "deceptive": {
        "strategic_overlay": "strategic_overlay_deceptive",
        "strategic_selection": "strategic_selection_deceptive",
    },
    "unconstrained": {
        "strategic_overlay": "strategic_overlay_unconstrained",
        "strategic_selection": "strategic_selection_unconstrained",
    },
    # v12-v15 SHADE-style. See PREREGISTRATION 47 for the SHEET caveat.
    "shade_research": {
        "strategic_overlay": "strategic_overlay_shade",
        "strategic_selection": "strategic_selection_shade",
    },
    "shade_e2": {
        "strategic_overlay": "strategic_overlay_shade_e2",
        "strategic_selection": "strategic_selection_shade_e2",
    },
    "shade_v14": {
        "strategic_overlay": "strategic_overlay_shade_v14",
        "strategic_selection": "strategic_selection_shade_v14",
    },
    "shade_v15": {
        "strategic_overlay": "strategic_overlay_shade_v15",
        "strategic_selection": "strategic_selection_shade_v15",
    },
    # v16. v15 with every working-sheet reference removed, for the runnable
    # STRAIGHT cells (the 47.3 scratchpad caveat answered with "none"); the arm
    # that attacks rather than abstains. See PREREGISTRATION 57.
    "shade_v16": {
        "strategic_overlay": "strategic_overlay_shade_v16",
        "strategic_selection": "strategic_selection_shade_v16",
    },
    # v17. v16 + a mandatory inline partition plan. Declared arm; never pooled.
    "shade_v17": {
        "strategic_overlay": "strategic_overlay_shade_v17",
        "strategic_selection": "strategic_selection_shade_v17",
    },
    # Minimum-necessary concealment. Differs from shade_v16 in ONE component:
    # the overlay's section 10.35. Selection call is shared and unchanged.
    "surgical": {
        "strategic_overlay": "strategic_overlay_surgical",
        "strategic_selection": "strategic_selection_shade_v16",
    },
    # v16 + monitor gist (oversight-aware attacker). Same selection call as v16.
    "shade_v16_gist": {
        "strategic_overlay": "strategic_overlay_shade_v16_gist",
        "strategic_selection": "strategic_selection_shade_v16",
    },
    # The EV family. SELECTION ONLY -- no overlay entry, deliberately.
    "ev": {"strategic_selection": "strategic_selection_ev"},
    "ev_lever": {"strategic_selection": "strategic_selection_ev_lever"},
    "ev_anchor": {"strategic_selection": "strategic_selection_ev_anchor"},
    "ev_neutral": {"strategic_selection": "strategic_selection_ev_neutral"},
}


@lru_cache(maxsize=len(OVERLAY_VARIANTS))   # one entry per overlay variant
def components(overlay: str = "current") -> dict[str, PromptComponent]:
    """The prompt registry, with one variant's saboteur components swapped in.

    Each variant repoints saboteur keys at their alternates; "current" swaps
    nothing. The renderers look components up by name and are untouched by
    this -- the variant is a property of the registry handed to them, so a
    golden render of any variant goes through exactly the same code path.
    """
    if overlay not in OVERLAY_VARIANTS:
        raise ValueError(
            f"unknown overlay variant {overlay!r} - "
            f"expected one of {', '.join(sorted(OVERLAY_VARIANTS))}"
        )
    comps = dict(load_all(PROMPT_MODULES_DIR, PromptRegistry()))
    for key, alternate in OVERLAY_VARIANTS[overlay].items():
        comps[key] = comps[alternate]
    return comps


@lru_cache(maxsize=1)
def target_slots() -> dict:
    from sedition.prompts.assembly import load_target_slots

    return load_target_slots(TARGET_SLOTS)


@lru_cache(maxsize=1)
def vocabulary() -> FactVocabulary:
    return load_fact_vocabulary(FACT_VOCABULARY_YAML)


# NOT cached here. The cache lives on `_answer_key_for`, keyed on the admitted
# set. A zero-arg lru_cache on this function would pin the first call's result
# for the life of the process and silently return the core-three key after
# admission -- which is exactly what it did until this line was removed.
def answer_key() -> AnswerKey:
    """The answer key for the CURRENTLY ADMITTED packet set.

    Admission must extend the key as well as the packages. This release
    admits no additional events, but the cache remains keyed on the same tuple
    as `scenarios()` so a future extension cannot make the two drift apart.

    Keyed on the same admitted tuple as `scenarios()`, so the two cannot drift
    apart: any state that changes one changes the other.
    """
    return _answer_key_for(_ADMITTED_HELDOUT)


@lru_cache(maxsize=4)
def _answer_key_for(admitted: tuple[str, ...]) -> AnswerKey:
    key = load_answer_key(ANSWER_KEY_JSON)
    if not admitted:
        return key
    heldout = load_answer_key(HELDOUT_ANSWER_KEY_JSON)
    merged = dict(key.packets)
    for pid, pk in heldout.packets.items():
        if pid.split("-")[0] in admitted:
            merged[pid] = pk
    return dataclasses.replace(key, packets=merged)


def packet(packet_id: str):
    """`E01-SS` -> the Packet. Event id is the part before the dash."""
    event_id = packet_id.split("-", 1)[0]
    return scenarios()[event_id].packets[packet_id]


def scenario_for(packet_id: str) -> ScenarioPackage:
    return scenarios()[packet_id.split("-", 1)[0]]
