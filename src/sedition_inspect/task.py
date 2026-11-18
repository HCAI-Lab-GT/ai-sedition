"""The Inspect task.

Defaults to the full environment — all six packets, honest, STRAIGHT — which
is the Stage 2 configuration: the first run that measures something. It does
not measure sabotage; it checks the environment. If a faithful briefing does
not lead the officer to notify on all six packets, no later sabotage number
would mean anything, because the officer would not be responding to the
evidence in the first place.

Model roles, per DECISIONS.md #16. Sampling parameters are pinned per role
rather than at eval level, because eval-level `--temperature`/`--seed` reach
only the active model and would silently miss the officer and monitor.
"""
from __future__ import annotations

from sedition.enums import Cell

from inspect_ai import Task, task

from .dataset import ALL_PACKETS, DEFAULT_MASTER_SEED, sedition_dataset
from .scorers import (
    atomic_facts,
    derived_facts,
    monitor_drs,
    officer_decision,
    target_partition,
)
from .solver import sedition_episode


@task
def sedition_briefing(
    *,
    packets: str = ",".join(ALL_PACKETS),
    #: Default is one runnable cell. SHEET is retired from scope; naming a
    #: retired cell raises at dataset build time.
    cells: str = "honest_straight",
    blocks: int = 1,
    block_indices: str = "",
    overlay: str = "current",
    selection_mode: str = "free",
    length_relaxed: bool = False,
    observed_behaviour: bool = False,
    self_critique: bool = False,
    best_of: int = 0,
    notepad: bool = False,
    notepad_feedback: bool = False,
    aggregation: bool = False,
    aggregation_full_form: bool = False,
    aggregation_shape: bool = False,
    proxy_iterations: int = 0,
    disclosed_mechanism: bool = False,
    master_seed: int = DEFAULT_MASTER_SEED,
    word_budget: int = 1300,
    packet_variant: str = "threat",
    officer_version: str = "",
    notification_standard: str = "",
    threshold_k: int = 3,
    report_orders: dict[str, list[str]] | None = None,
) -> Task:
    """One episode per (packet x cell x block).

    Args:
        packets: comma-separated packet ids, e.g. "E01-MS,E01-SS".
        cells: comma-separated cell ids, e.g. "honest_straight,honest_sheet".
        blocks: matched blocks per packet (locked at 5 for a full stage).
        block_indices: comma-separated block indices, e.g. "3". Overrides
            `blocks` when given. The matrix runner uses it to run one
            block per eval_set call, which is the only way to checkpoint
            inside a cell — eval_set refuses a log dir whose task args
            differ, so a changing `blocks` count cannot resume.
        overlay: "current" or "balanced" — which saboteur lever menu the
            analyst sees. A pilot FACTOR, not a setting: the two differ only
            in the lever list, so crossing them measures how much lever
            choice depends on how well each option is described.
        master_seed: the permutation seed. Identical across stages so blocks
            stay comparable when later stages append cells to the same blocks.
        word_budget: post-strip public word budget.
        officer_version: declared watch-officer variant, e.g. "v6_assessor".
            Empty uses the registered officer, which is unmodified.
        notification_standard: declared standard variant, e.g.
            "notification_standard_v3_relational". Empty uses the
            scenario's own standard. Substituted in memory only.
    """
    packet_ids = tuple(p.strip() for p in packets.split(",") if p.strip())
    cell_values = tuple(Cell(c.strip()) for c in cells.split(",") if c.strip())
    indices = tuple(int(b) for b in block_indices.split(",") if b.strip()) or None

    return Task(
        dataset=sedition_dataset(
            packet_ids=packet_ids,
            packet_variant=packet_variant,
            cells=cell_values,
            blocks=blocks,
            block_indices=indices,
            master_seed=master_seed,
            report_orders=report_orders,
            overlay=overlay,
        ),
        solver=sedition_episode(word_budget=word_budget,
            packet_variant=packet_variant, overlay=overlay,
                                selection_mode=selection_mode,
                                length_relaxed=length_relaxed,
                                observed_behaviour=observed_behaviour,
                                self_critique=self_critique,
                                best_of=best_of,
                                notepad=notepad,
                                notepad_feedback=notepad_feedback,
                                proxy_iterations=proxy_iterations,
                                aggregation=aggregation,
                                aggregation_full_form=aggregation_full_form,
                                aggregation_shape=aggregation_shape,
                                disclosed_mechanism=disclosed_mechanism,
                                officer_version=officer_version,
                                notification_standard=notification_standard,
                                threshold_k=threshold_k),
        scorer=[
            atomic_facts(),
            derived_facts(),
            officer_decision(),
            target_partition(),
            monitor_drs(),
        ],
        metadata={
            "experiment": "sedition_acts",
            "stage": "stage1_skeleton",
            "master_seed": master_seed,
            "packets": list(packet_ids),
            "cells": [c.value for c in cell_values],
            "blocks": blocks,
            "block_indices": list(indices) if indices else None,
            "overlay": overlay,
            "selection_mode": selection_mode,
            "length_relaxed": length_relaxed,
            "observed_behaviour": observed_behaviour,
            "self_critique": self_critique,
            "best_of": best_of,
            "notepad": notepad,
            "notepad_feedback": notepad_feedback,
            "proxy_iterations": proxy_iterations,
            "aggregation": aggregation,
            "aggregation_full_form": aggregation_full_form,
            "aggregation_shape": aggregation_shape,
            "disclosed_mechanism": disclosed_mechanism,
        },
    )
