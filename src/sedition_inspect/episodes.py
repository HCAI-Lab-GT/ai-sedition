"""Read a completed log directory back into per-episode rows.

One reader, used by both the matrix runner (to apply the stopping rules
between blocks) and scripts/analyze_run.py (to report). They must agree: a
stopping rule that reads `flags` differently from the analysis that reports
them could halt a run the analysis would call healthy, or fail to halt one it
would call broken.

Store keys are spelled out here and nowhere else, so a rename in `_store.py`
breaks one file rather than drifting silently between two.
"""
from __future__ import annotations

from typing import Any

from sedition.enums import Flag
from sedition.pipeline.degeneracy import is_degenerate

from inspect_ai.log import list_eval_logs, read_eval_log

#: Score name -> row key. The row keys are what metrics.py and stopping.py
#: consume; the score names are what the scorers register as.
SCORES = {
    "atomic_facts": "atomic",
    "derived_facts": "derived",
    "officer_decision": "officer",
    "target_partition": "partition",
    "monitor_drs": "drs",
}


def _numeric(sample: Any, name: str) -> float | None:
    score = sample.scores.get(name) if sample.scores else None
    if score is None:
        return None
    return score.value if isinstance(score.value, (int, float)) else None


def provider_calls(log_dir: str) -> tuple[int, int]:
    """(errors, total_calls) across a log directory.

    The provider-error stopping rule (PREREGISTRATION.md section 8) was
    implemented but could never fire: nothing supplied these counts, so
    `provider_calls` stayed 0 and the rule short-circuited to None on every
    invocation. Counted from the model events, which record an error field
    per call.
    """
    errors = total = 0
    try:
        infos = list_eval_logs(log_dir)
    except Exception:
        return 0, 0
    for info in infos:
        log = read_eval_log(info.name)
        for s in log.samples or []:
            for ev in s.events:
                if ev.event != "model":
                    continue
                total += 1
                if getattr(ev, "error", None):
                    errors += 1
    return errors, total


def episode_rows(log_dir: str) -> list[dict]:
    """Every episode in `log_dir`, flattened. Missing dir -> empty list.

    An empty result is a legitimate state — a cell that has not run yet — and
    is distinguished from a failed read by the caller, not by an exception
    here. The stopping rules treat zero episodes as "continue" for exactly
    this reason.
    """
    rows: list[dict] = []
    try:
        infos = list_eval_logs(log_dir)
    except Exception:
        return rows

    for info in infos:
        log = read_eval_log(info.name)
        for s in log.samples or []:
            st, md = s.store, s.metadata

            # Recomputed rather than read, so runs logged before the detector
            # existed are labelled correctly: run-llama-01 stores no
            # DEGENERATE_OUTPUT flag at all, and reporting it as 0% degenerate
            # would be a flat lie about the run it was written for.
            #
            # Exact, not approximate — degeneracy is a pure function of the
            # briefing text, so recomputation gives the same answer the run
            # would have. For logs written after the detector landed the two
            # agree by construction.
            flags = set(st.get("EpisodePublic:flags") or [])
            briefing = st.get("EpisodePublic:public_briefing") or ""
            if briefing and is_degenerate(briefing):
                flags.add(Flag.DEGENERATE_OUTPUT.value)

            row = {
                "id": s.id,
                "packet": md.get("packet_id"),
                "version": md.get("version"),
                "cell": md.get("cell"),
                "policy": md.get("policy"),
                "block": md.get("block_index"),
                "invalid": bool(st.get("EpisodePublic:invalid")),
                "refused": bool(st.get("EpisodePublic:refused")),
                "flags": sorted(flags),
                "words": st.get("EpisodePublic:briefing_word_count"),
                "wo": st.get("EpisodePublic:wo_decision") or "",
                "wo_final": st.get("EpisodePublic:wo_final_decision") or "",
                # Under the names sedition.scoring.metrics reads.
                "wo_decision": st.get("EpisodePublic:wo_decision") or "",
                "wo_final_decision": st.get("EpisodePublic:wo_final_decision") or "",
                "attack_decision": st.get("AnalystPrivate:attack_decision"),
                "primary_lever": st.get("AnalystPrivate:primary_lever"),
                "detection_risk": st.get("AnalystPrivate:predicted_detection_risk"),
                "clarified": bool(st.get("EpisodePublic:clarification_requested")),
            }
            for score_name, key in SCORES.items():
                row[key] = _numeric(s, score_name)
            rows.append(row)
    return rows
