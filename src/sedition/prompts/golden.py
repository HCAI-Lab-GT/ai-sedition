"""`sedition render-golden` — render every fully-specified analyst call at
block_index=0 (canonical report order) into golden/.

Golden files are committed. Any prompt-module change that alters a rendered
prompt must show up as a reviewed diff. `--check` fails instead of writing,
which is what CI runs.

Core set: 6 packets x 3 SHEET cells = 18 briefing renders, plus 6
strategic-selection renders. All 18 core combinations must render — a
missing core SHEET golden is a failing gate, not an acceptable skip.
"""
from __future__ import annotations

from ..config.schema import load_stage
from ..enums import Cell, WorkingCondition
from ..packets.build import parse_all
from ..storage.paths import (
    GOLDEN_DIR,
    PROMPT_MODULES_DIR,
    SCENARIOS_DIR,
    TARGET_SLOTS,
    stage_config,
)
from .assembly import load_target_slots, render_analyst_briefing, render_strategic_selection
from .loader import load_all
from .registry import PromptRegistry

CORE_CELLS = (Cell.HONEST_SHEET, Cell.BASIC_SHEET, Cell.STRATEGIC_SHEET)

#: STRAIGHT renders for the saboteur overlays. Added because overlay
#: composition is the most likely part of the prompt layer to drift silently,
#: and because these are the prompts the STRAIGHT-first build order actually
#: sends. Honest STRAIGHT is not committed: it is the same common block with
#: no overlay, and the SHEET goldens already pin that text.
OVERLAY_STRAIGHT_CELLS = (Cell.BASIC_STRAIGHT, Cell.STRATEGIC_STRAIGHT)


#: Overlay variants pinned as goldens. "current" keeps the existing filenames
#: so no committed golden is renamed; "balanced" adds a parallel set with a
#: suffix. Both are rendered through the same code path — the variant is a
#: property of the component registry, not of the renderer — so a drift in
#: either shows up as a diff here.
OVERLAY_VARIANTS = (("current", ""), ("balanced", "-balanced"),
                    ("permissive", "-permissive"),
                    ("gist", "-gist"),
                    ("deceptive", "-deceptive"))


def render_all() -> dict[str, str]:
    """Return {filename: rendered_text} for every fully-specified call."""
    config = load_stage(stage_config("stage0"))
    packages = parse_all(SCENARIOS_DIR)
    targets = load_target_slots(TARGET_SLOTS)

    rendered: dict[str, str] = {}
    for overlay, suffix in OVERLAY_VARIANTS:
        rendered.update(_render_variant(packages, targets, config, overlay, suffix))
    return rendered


def _render_variant(packages, targets, config, overlay: str, suffix: str) -> dict[str, str]:
    components = load_all(PROMPT_MODULES_DIR, PromptRegistry())
    if overlay == "balanced":
        for key in ("basic_saboteur", "strategic_overlay", "strategic_selection"):
            components[key] = components[f"{key}_balanced"]
    elif overlay == "deceptive":
        for key in ("strategic_overlay", "strategic_selection"):
            components[key] = components[f"{key}_deceptive"]
    elif overlay == "gist":
        for key in ("strategic_overlay", "strategic_selection"):
            components[key] = components[f"{key}_gist"]
    elif overlay == "permissive":
        # STRATEGIC path only — basic has no selection call, so v8's section 11
        # never applied to it. Mirrors _resources.components().
        for key in ("strategic_overlay", "strategic_selection"):
            components[key] = components[f"{key}_permissive"]

    rendered: dict[str, str] = {}
    for _event_id, pkg in sorted(packages.items()):
        for packet_id, packet in sorted(pkg.packets.items()):
            permutation = packet.report_ids  # block_index=0: canonical order
            target = targets[packet_id]

            for cell in CORE_CELLS:
                call = render_analyst_briefing(
                    policy=cell.policy.value,
                    working_condition=WorkingCondition.SHEET.value,
                    scenario=pkg, packet=packet, permutation=permutation,
                    components=components,
                    word_budget=config.budgets.briefing_word_budget,
                    target=target if cell.has_hidden_objective else None,
                )
                rendered[f"{packet_id}-{cell.value}{suffix}.md"] = call.payload.text

            for cell in OVERLAY_STRAIGHT_CELLS:
                call = render_analyst_briefing(
                    policy=cell.policy.value,
                    working_condition=WorkingCondition.STRAIGHT.value,
                    scenario=pkg, packet=packet, permutation=permutation,
                    components=components,
                    word_budget=config.budgets.briefing_word_budget,
                    target=target,
                )
                rendered[f"{packet_id}-{cell.value}{suffix}.md"] = call.payload.text

            call = render_strategic_selection(
                scenario=pkg, packet=packet, permutation=permutation,
                components=components, target=target,
            )
            rendered[f"{packet_id}-strategic_selection{suffix}.md"] = call.payload.text
    return rendered


def main(*, check: bool = False) -> int:
    rendered = render_all()
    # Per overlay variant: SHEET cores + STRAIGHT overlays + the selection
    # call. Multiplied by the number of variants, because both are pinned.
    per_variant = 6 * len(CORE_CELLS) + 6 * len(OVERLAY_STRAIGHT_CELLS) + 6
    n_variants = len(OVERLAY_VARIANTS)
    n_core = 6 * len(CORE_CELLS) * n_variants
    expected = per_variant * n_variants
    core_count = sum(
        1 for name in rendered
        if any(name.endswith(f"-{c.value}{sfx}.md")
               for c in CORE_CELLS for _ov, sfx in OVERLAY_VARIANTS)
    )

    print(f"expected {expected} golden renders "
          f"({per_variant} per overlay variant x {n_variants} variants: "
          f"6 packets x {len(CORE_CELLS)} SHEET cells "
          f"+ 6 x {len(OVERLAY_STRAIGHT_CELLS)} STRAIGHT overlays "
          f"+ 6 selection calls)")
    print(f"rendered {len(rendered)}")
    print(f"core SHEET combinations: {core_count} / {n_core}")

    if len(rendered) != expected or core_count != n_core:
        print("FAIL: not every combination rendered")
        return 1

    GOLDEN_DIR.mkdir(exist_ok=True)
    if check:
        drifted = []
        for name, text in sorted(rendered.items()):
            path = GOLDEN_DIR / name
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                drifted.append(name)
        if drifted:
            print(f"FAIL: {len(drifted)} golden file(s) would change:")
            for name in drifted:
                print(f"  - {name}")
            return 1
        print("OK: every golden file matches the committed copy.")
        return 0

    for name, text in sorted(rendered.items()):
        (GOLDEN_DIR / name).write_text(text, encoding="utf-8")
    print("OK: all core combinations and selection calls written.")
    return 0
