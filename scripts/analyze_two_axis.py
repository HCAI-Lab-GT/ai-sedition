"""Summarise a scripts/run_two_axis.py log root: one row per (cell, variant).

Reads every .eval under <log_root>/<cell>__<variant>/ and reports, per job:
validity and flags, officer decisions, the scorer means on valid episodes,
the strategic ATTACK/ABSTAIN split, and token usage per model. Descriptive
only -- no inference, no pooling across jobs.

    .venv/bin/python scripts/analyze_two_axis.py logs/two-axis-01
    .venv/bin/python scripts/analyze_two_axis.py logs/two-axis-01 --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inspect_ai.log import read_eval_log  # noqa: E402

SCORERS = ("atomic_facts", "derived_facts", "officer_decision", "target_partition", "monitor_drs")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def summarise_job(job_dir: Path, patches: list[Path] = ()) -> dict:
    by_id: dict[str, dict] = {}
    usage: dict[str, dict[str, int]] = defaultdict(lambda: {"input": 0, "output": 0})
    statuses: Counter = Counter()
    files = [f for d in (job_dir, *patches) for f in sorted(d.glob("*.eval"))]
    for f in files:
        lg = read_eval_log(str(f))
        statuses[lg.status] += 1
        for m, u in (lg.stats.model_usage or {}).items():
            usage[m]["input"] += u.input_tokens
            usage[m]["output"] += u.output_tokens
        for s in lg.samples or []:
            st = s.store or {}
            if s.id in by_id and not by_id[s.id]["error"]:
                continue  # a patch only replaces an errored episode
            by_id[s.id] = ({
                "id": s.id,
                "packet": s.metadata.get("packet_id"),
                "block": s.metadata.get("block_index"),
                "error": s.error.message if s.error else None,
                "invalid": bool(st.get("EpisodePublic:invalid")),
                "refused": bool(st.get("EpisodePublic:refused")),
                "flags": tuple(st.get("EpisodePublic:flags") or ()),
                "words": st.get("EpisodePublic:briefing_word_count"),
                "decision": st.get("EpisodePublic:wo_final_decision") or st.get("EpisodePublic:wo_decision") or None,
                "clarified": bool(st.get("EpisodePublic:clarification_requested")),
                "attack": st.get("AnalystPrivate:attack_decision") or None,
                "scores": {k: (_num(s.scores[k].value) if s.scores and k in s.scores else None) for k in SCORERS},
            })
    rows = list(by_id.values())
    valid = [r for r in rows if not r["error"] and not r["invalid"]]
    flags: Counter = Counter(fl for r in rows for fl in r["flags"])
    means = {}
    for k in SCORERS:
        vals = [r["scores"][k] for r in valid if r["scores"][k] is not None]
        means[k] = {"mean": round(sum(vals) / len(vals), 3) if vals else None, "n": len(vals)}
    return {
        "episodes": len(rows),
        "errors": sum(1 for r in rows if r["error"]),
        "invalid": sum(1 for r in rows if r["invalid"] and not r["error"]),
        "valid": len(valid),
        "refused": sum(1 for r in rows if r["refused"]),
        "log_status": dict(statuses),
        "decisions": dict(Counter(str(r["decision"]) for r in valid)),
        "clarified": sum(1 for r in valid if r["clarified"]),
        "attack": dict(Counter(str(r["attack"]) for r in rows if r["attack"])),
        "flags": dict(flags.most_common()),
        "words_mean": round(sum(r["words"] for r in valid if r["words"]) / max(1, sum(1 for r in valid if r["words"]))),
        "scores": means,
        "per_packet_decisions": {p: dict(Counter(str(r["decision"]) for r in valid if r["packet"] == p))
                                 for p in sorted({r["packet"] for r in rows})},
        "usage": dict(usage),
        "error_messages": dict(Counter((r["error"] or "")[:80] for r in rows if r["error"])),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("log_root")
    p.add_argument("--patch", action="append", default=[],
                   help="extra log root(s) whose episodes replace same-id errored ones (repeatable)")
    p.add_argument("--json", default=None, help="also write the full summary here")
    a = p.parse_args()
    root = Path(a.log_root)
    out = {}
    for job_dir in sorted(d for d in root.iterdir() if d.is_dir() and "__" in d.name):
        patches = [pr / job_dir.name for pr in map(Path, a.patch) if (pr / job_dir.name).is_dir()]
        out[job_dir.name] = summarise_job(job_dir, patches)

    print(f"{'job':32s} {'eps':>4s} {'err':>4s} {'inv':>4s} {'valid':>5s} {'words':>5s}  "
          f"{'notify':>6s} {'clar':>5s} {'routine':>7s}  {'atomic':>6s} {'derived':>7s} {'drs':>5s}  attack/abstain")
    for job, r in out.items():
        d, sc, att = r["decisions"], r["scores"], r["attack"]
        line = (f"{job:32s} {r['episodes']:4d} {r['errors']:4d} {r['invalid']:4d} {r['valid']:5d} {r['words_mean']:5d}  "
                f"{d.get('NOTIFY_IMMEDIATELY', 0):6d} {d.get('REQUEST_MORE_INFORMATION', 0):5d} "
                f"{d.get('INCLUDE_IN_ROUTINE_UPDATE', 0):7d}  "
                f"{str(sc['atomic_facts']['mean']):>6s} {str(sc['derived_facts']['mean']):>7s} "
                f"{str(sc['monitor_drs']['mean']):>5s}")
        if att:
            line += f"  {att.get('ATTACK', 0)}/{att.get('ABSTAIN', 0)}"
        print(line)
    print()
    for job, r in out.items():
        if r["flags"] or r["error_messages"]:
            print(f"{job}: flags={r['flags']} errors={r['error_messages']}")
    tot_in = sum(u["input"] for r in out.values() for u in r["usage"].values())
    tot_out = sum(u["output"] for r in out.values() for u in r["usage"].values())
    print(f"\ntokens: input={tot_in:,} output={tot_out:,}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
