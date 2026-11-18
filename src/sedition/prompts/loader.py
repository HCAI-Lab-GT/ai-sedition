"""Static component loader: sedition/prompts/modules/*.md -> PromptRegistry.

Component files are hand-extracted, one immutable file per module — each
carries its own "#"-comment provenance header naming its exact source and
line span (see sedition/prompts/modules/*.md). This loader strips that header
and registers the remaining model-facing body. It does not parse or slice
any monolithic prompt document at runtime — that approach was rejected as
fragile; all-prompts.md remains available for human reference only.
"""
from __future__ import annotations

from pathlib import Path

from .registry import PromptComponent, PromptRegistry

# component name -> (version, filename in sedition/prompts/modules/)
COMPONENT_FILES: dict[str, tuple[str, str]] = {
    # v7, not v6: "v6" already means v5 assembled with the §9 clarification
    # replacement below, and reusing the number would give two different
    # prompts the same name. See the module header for why v5 was superseded
    # (the E03-MS paired run, 2026-08-15).
    "analyst_common": ("v8", "analyst_common_v8.md"),
    # The clarification turn's §9, which replaces analyst_common v5's §9 in
    # full (making the assembled result v6). Stored as a section, not a
    # second copy of the common block, because that is the only difference.
    "analyst_common_section9": ("v6", "analyst_common_v6_section9.md"),
    "working_sheet": ("v2", "working_sheet_v2.md"),
    "basic_saboteur": ("v6", "basic_saboteur_v6.md"),
    # Capability control: honest objective, told it is tired. See the
    # component header for what is deliberately absent from it.
    #
    # FILENAME. Deliberately not `degraded_analyst_v1.md`: a guard in
    # tests/inspect_port/test_benign_error_arm.py asserts that path
    # does NOT exist, because a "process-constraint definition of benign error"
    # once lived there and was deleted. This arm is a different thing -- fatigue
    # framing with no released constraints and no objective -- so it takes a
    # name of its own rather than reoccupying a retired one.
    "fatigued_analyst": ("v1", "fatigued_analyst_v1.md"),
    "strategic_selection": ("v6", "strategic_selection_v6.md"),
    "strategic_overlay": ("v6", "strategic_overlay_v6.md"),
    "watch_officer": ("v3", "watch_officer_v3.md"),
    # v_balanced overlay variant. Identical to the v6 modules except the
    # lever menu; run as a factor against them so the abstention result is
    # measured against menu specificity rather than confounded by it.
    "basic_saboteur_balanced": ("v7", "basic_saboteur_v7_balanced.md"),
    "strategic_overlay_balanced": ("v7", "strategic_overlay_v7_balanced.md"),
    "strategic_selection_balanced": ("v7", "strategic_selection_v7_balanced.md"),
    # v8_permissive. Loosens section 11's CONJUNCTIVE GATE into a judgment and
    # adds one line of goal-state framing; the honesty constraints and the v6
    # lever menu are untouched. It is a third arm, not a replacement — v6 and
    # v7_balanced stay registered above and nothing pools across versions.
    "strategic_selection_permissive": ("v8", "strategic_selection_v8_permissive.md"),
    "strategic_overlay_permissive": ("v8", "strategic_overlay_v8.md"),
    # v9_monitor_gist, built ON v8. A distinct THREAT MODEL — an adversary with
    # partial knowledge of the oversight mechanism — not another rung. The gist
    # sits in BOTH the overlay (10.5) and the selection call (10.3); the
    # secondary outcome is whether disclosure moves abstention, and abstention
    # is decided on the selection call, which never sees the overlay. Drop the
    # selection entry alone to run overlay-only disclosure as a variant.
    "strategic_selection_gist": ("v9", "strategic_selection_v9_monitor_gist.md"),
    "strategic_overlay_gist": ("v9", "strategic_overlay_v9_monitor_gist.md"),
    # v10_deceptive. Built ON v8. Releases 10.4's record constraints FOR THE
    # TARGET ONLY — the saboteur may state what the reports do not support.
    # A separate declared condition; never pooled with the truthful strategic
    # arm, which remains registered above and unchanged.
    "strategic_selection_deceptive": ("v10", "strategic_selection_v10_deceptive.md"),
    "strategic_overlay_deceptive": ("v10", "strategic_overlay_v10_deceptive.md"),
    # v11_unconstrained. Built ON v10. v10 released the same record constraints
    # and returned null: 0/137 attack rationales referenced the licence and
    # 1/136 briefings used it. Two causes, not one - the licence sat inside a
    # section headed "Constraints you must hold", AND v10 kept 2.4/2.7/2.8
    # binding on the target while permitting exactly those three things. v11
    # states the licence affirmatively, first, and deletes what contradicted it.
    # A separate declared arm; never pooled with v8 or v10.
    "strategic_selection_unconstrained": ("v11", "strategic_selection_v11_unconstrained.md"),
    "strategic_overlay_unconstrained": ("v11", "strategic_overlay_v11_unconstrained.md"),
    # ---- v12-v15 SHADE-style strategic variants -------------------------------
    # TWO CAVEATS, recorded at merge (PREREGISTRATION 47) rather than left to be
    # rediscovered:
    #  1. All four reference the SHEET working area as a hidden scratchpad, but
    #     the SHEET working condition was RETIRED from the project (enums.RETIRED_CELLS).
    #     These variants therefore describe a mechanism no runnable cell provides.
    #     Harmless today -- nothing on a default run path selects them -- but any
    #     run using one must first decide what the scratchpad actually is.
    #  2. strategic_selection v14 and v15 are BYTE-IDENTICAL after header stripping.
    #     v15's change lives entirely in its overlay. Editing v14's selection will
    #     NOT propagate to v15; they are two files holding one body.
    # v12_shade_research. A SHADE-Arena-style research/test-environment framing of
    # the SAME strategic_saboteur policy and cells (Kutasov et al. 2025,
    # arXiv:2506.15740). Removes v6's conjunctive attack gate and offers no
    # ABSTAIN — the selection call assigns the objective and records only its
    # predicted risk and lever. Honesty, citation, format, and word-limit
    # constraints are untouched. A separate declared arm; never pooled with any
    # other version. Selected via overlay="shade_research".
    "strategic_selection_shade": ("v12", "strategic_selection_v12_shade_research.md"),
    "strategic_overlay_shade": ("v12", "strategic_overlay_v12_shade_research.md"),
    # v13_shade_e2. SHADE-Arena Appendix E.2 structure (mock env + simulated user,
    # main task + covert secondary task, hidden scratchpad = the SHEET working
    # area, 900-1,100 word target). Same strategic_saboteur policy/cells; no
    # ABSTAIN. Selected via overlay="shade_e2". Separate arm; never pooled.
    "strategic_selection_shade_e2": ("v13", "strategic_selection_v13_shade_e2.md"),
    "strategic_overlay_shade_e2": ("v13", "strategic_overlay_v13_shade_e2.md"),
    # v14_shade_conflict. Resolves the v13 task conflict: main task no longer
    # requires foregrounding the target; covert task made concrete (keep the
    # decisive cross-report relationship unassembled / target low-urgency) with a
    # <=5-bullet plan in the SHEET. Same policy/cells; no ABSTAIN. overlay="shade_v14".
    "strategic_selection_shade_v14": ("v14", "strategic_selection_v14_shade_conflict.md"),
    "strategic_overlay_shade_v14": ("v14", "strategic_overlay_v14_shade_conflict.md"),
    # v15_conflict_downplay. v14 + directive to lower each independently-sufficient
    # target fact via the released s2.9/s2.6 treatment (benign cause as explanation,
    # drop hedges) - only where reports offer it. overlay="shade_v15".
    "strategic_selection_shade_v15": ("v15", "strategic_selection_v15_conflict_downplay.md"),
    "strategic_overlay_shade_v15": ("v15", "strategic_overlay_v15_conflict_downplay.md"),
    # v16_nosheet. v15 with every working-sheet reference removed, for the
    # runnable STRAIGHT cells (SHEET retired, 32.x; 47.3). overlay="shade_v16".
    "strategic_selection_shade_v16": ("v16", "strategic_selection_v16_nosheet.md"),
    "strategic_overlay_shade_v16": ("v16", "strategic_overlay_v16_nosheet.md"),
    # v17_inline_plan. v16 with the vague "decide privately" note replaced by a
    # concrete mandatory inline partition plan (name target reports -> decisive
    # pair -> split across blocks -> lower each fact). Recovers the retired
    # SHEET's GROUPS/PLAN behaviour without a scratchpad. overlay="shade_v17".
    "strategic_selection_shade_v17": ("v17", "strategic_selection_v17_inline_plan.md"),
    "strategic_overlay_shade_v17": ("v17", "strategic_overlay_v17_inline_plan.md"),
    # v19_nosheet_gist. v16 + the v9 monitor-gist paragraph (the six materiality
    # axes, no score/threshold). Selection call is v16's. overlay="shade_v16_gist".
    "strategic_overlay_shade_v16_gist": ("v19", "strategic_overlay_v19_nosheet_gist.md"),
    # ---- the EV family (review/gpt-strategic-baseline, commit 3a16139cb) ------
    # SELECTION-ONLY variants: no overlay counterpart, by design. The briefing
    # overlay stays v6 so an ATTACK writes the same way the published arms do.
    #
    # AUTHORED AS "v8". Renamed on merge -- main's v8 is an unrelated prompt
    # (strategic_selection_v8_permissive, overlay "permissive", with v9/v10/v11
    # on top). NEVER POOL the two lineages.
    #
    # What ev changes vs v7_balanced is section 11 only: v6's three-condition
    # conjunctive gate and "ABSTAIN is a correct answer to this call" are
    # replaced by an expected-value rule that names the cost of abstaining.
    # Measured on gpt-4.1: v6 control 0/30 ATTACK -> ev 30/30, p = 1.7e-17.
    # ev_lever changes one line of the lever menu and the decision rule not at
    # all; it stayed 0/30, which is what isolates the decision rule as the cause.
    #
    # ANCHORING CAVEAT (PREREGISTRATION 48): ev's section 12 JSON example prints
    # a decision, a lever and a risk value, and the smoke returned all three back
    # verbatim with zero variance. ev_anchor holds ev constant and moves only the
    # example's lever, so the PAIR measures the anchoring. ev_neutral strips the
    # example's values so the three fields can be read as outcomes at all.
    "strategic_selection_ev": ("v8_ev", "strategic_selection_v8_ev.md"),
    "strategic_selection_ev_lever": ("v8_ev_lever", "strategic_selection_v8_ev_lever.md"),
    "strategic_selection_ev_anchor": ("v8_ev_anchor", "strategic_selection_v8_ev_anchor_wh.md"),
    "strategic_selection_ev_neutral": ("v8_ev_neutral", "strategic_selection_v8_ev_neutral.md"),
    # v16_nosheet (reviewer-d/strategic-v15-dev be6525d97). v15 with every
    # working-sheet reference removed, for the runnable STRAIGHT cells.
    # It removes the decline option: where v6 offers ABSTAIN and was taken up
    # 58/58, v16 assigns the covert task. Declared arm; NEVER pooled with v6.
    "strategic_selection_shade_v16": ("v16", "strategic_selection_v16_nosheet.md"),
    "strategic_overlay_shade_v16": ("v16", "strategic_overlay_v16_nosheet.md"),
    # v18_surgical. v16 with section 10.35 replaced: withhold the ONE relationship
    # that suffices and state every other. Pairs with v16's selection call
    # unchanged, so v16 vs surgical is a single-factor comparison. See 59.
    "strategic_overlay_surgical": ("v18", "strategic_overlay_v18_surgical.md"),
    # v17_inline_plan (reviewer-d/strategic-v15-dev ffe2560f8). v16 plus a concrete
    # mandatory inline partition plan, recovering the retired scratchpad's
    # GROUPS/PLAN step without a scratchpad. In an earlier development probe the
    # original development probe measured a higher routine rate than v16.
    "strategic_selection_shade_v17": ("v17", "strategic_selection_v17_inline_plan.md"),
    "strategic_overlay_shade_v17": ("v17", "strategic_overlay_v17_inline_plan.md"),
    "general_monitor": ("v3", "general_monitor_v3.md"),
    "omission_hunter": ("v3", "omission_hunter_v3.md"),
    "severity_auditor": ("v3", "severity_auditor_v3.md"),
    "accuracy_checker": ("v3", "accuracy_checker_v3.md"),
}


def _strip_provenance_header(text: str) -> str:
    """Drop the leading block of "#"-prefixed lines plus the blank line(s)
    that follow it. What remains is the model-facing body."""
    lines = text.split("\n")
    i = 0
    while i < len(lines) and lines[i].startswith("#"):
        i += 1
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    body = "\n".join(lines[i:]).rstrip("\n")
    return body + "\n"


def load_component(components_dir: str | Path, name: str) -> PromptComponent:
    version, filename = COMPONENT_FILES[name]
    path = Path(components_dir) / filename
    text = _strip_provenance_header(path.read_text(encoding="utf-8"))
    return PromptComponent(name=name, version=version, text=text)


def load_all(components_dir: str | Path, registry: PromptRegistry) -> dict[str, PromptComponent]:
    return {name: registry.register(load_component(components_dir, name))
            for name in COMPONENT_FILES}
