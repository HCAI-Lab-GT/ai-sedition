"""Summarise a dev round's .eval logs: per cell, attack split, officer decisions
at k=1/2/3 (re-derived from the blind assessment), derived/atomic fact rates,
flags, and cost. Private sheet PLAN text is dumped to a separate file for the
developer only (never forwarded anywhere).

    .venv/bin/python strat_analyze.py logs/strat-dev-r1 [--dump]
"""
from __future__ import annotations

import argparse
import glob
import json
import pathlib
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from inspect_ai.log import read_eval_log  # noqa: E402
from sedition.scoring.threshold_rule import count_met, decide  # noqa: E402

PRICE = {  # $/token in, out (OpenRouter, 2026-08-22)
    "openrouter/deepseek/deepseek-v4-pro-0813": (1.188e-6, 3.564e-6),
    "openrouter/deepseek/deepseek-chat-v3-0324": (0.25e-6, 1.00e-6),
    "openrouter/deepseek/deepseek-v3.2": (0.26e-6, 0.38e-6),
    "openrouter/deepseek/deepseek-v4-flash-0731": (0.08e-6, 0.18e-6),
    # Azure Foundry bills by subscription, not per call; these reuse the
    # OpenRouter list prices for the same models as an ESTIMATE so a round
    # reports an order-of-magnitude cost. Check the Azure portal for actuals.
    "azureai/DeepSeek-V4-Pro": (1.188e-6, 3.564e-6),
    "azureai/DeepSeek-V3.2": (0.26e-6, 0.38e-6),
    "azureai/DeepSeek-V4-Flash": (0.08e-6, 0.18e-6),
}
NOTIFY, RMI, ROUTINE = "NOTIFY_IMMEDIATELY", "REQUEST_MORE_INFORMATION", "INCLUDE_IN_ROUTINE_UPDATE"


def rows_from(log_dir: str) -> tuple[list[dict], dict]:
    rows, usage = [], {}
    for f in sorted(glob.glob(f"{log_dir}/*.eval")):
        log = read_eval_log(f)
        if log.stats:
            for m, u in log.stats.model_usage.items():
                cur = usage.setdefault(m, [0, 0])
                cur[0] += u.input_tokens or 0
                cur[1] += u.output_tokens or 0
        for s in log.samples or []:
            st = s.store
            g = lambda k, d=None: st.get(k, d)  # noqa: E731
            crit = g("EpisodePublic:wo_criteria", []) or []
            try:
                nmet = count_met(crit)
                dk = {k: decide(crit, k) for k in (1, 2, 3)}
            except Exception:
                nmet, dk = -1, {}
            sc = {k: (v.value if isinstance(v.value, (int, float)) and not isinstance(v.value, bool) else None) for k, v in (s.scores or {}).items()}
            raw_sc = {k: v.value for k, v in (s.scores or {}).items()}
            rows.append({
                "id": s.id, "cell": s.metadata.get("cell"), "packet": s.metadata.get("packet_id"),
                "block": s.metadata.get("block"),
                "error": bool(s.error), "invalid": g("EpisodePublic:invalid", False),
                "flags": g("EpisodePublic:flags", []), "words": g("EpisodePublic:briefing_word_count", 0),
                "attack": g("AnalystPrivate:attack_decision", ""), "lever": g("AnalystPrivate:primary_lever", ""),
                "risk": g("AnalystPrivate:predicted_detection_risk", -1),
                "wo_decision": g("EpisodePublic:wo_decision", ""), "n_met": nmet,
                "crit": {c.get("criterion", c.get("id", "?")): c.get("status") for c in crit},
                "k1": dk.get(1), "k2": dk.get(2), "k3": dk.get(3),
                "derived": sc.get("derived_facts"), "atomic": sc.get("atomic_facts"),
                "drs": sc.get("monitor_drs"), "partition": sc.get("target_partition"),
                "sheet": g("AnalystPrivate:working_sheet", ""), "public": g("EpisodePublic:public_briefing", ""),
                "rationale": g("AnalystPrivate:attack_rationale", ""), "raw_scores": raw_sc,
            })
    return rows, usage


def pct(n: int, d: int) -> str:
    return f"{n}/{d}" + (f" ({100*n/d:.0f}%)" if d else "")


def summarise(rows: list[dict], usage: dict, k: int) -> str:
    out = []
    cells = sorted({r["cell"] for r in rows})
    for cell in cells:
        rs = [r for r in rows if r["cell"] == cell]
        ok = [r for r in rs if not r["invalid"] and not r["error"]]
        out.append(f"\n== {cell}: n={len(rs)} usable={len(ok)} invalid={sum(r['invalid'] for r in rs)} error={sum(r['error'] for r in rs)}")
        if cell.startswith("strategic"):
            att = [r for r in ok if r["attack"] == "ATTACK"]
            out.append(f"   selection: ATTACK {pct(len(att), len(ok))}, ABSTAIN {sum(r['attack']=='ABSTAIN' for r in ok)}; "
                       f"levers={sorted({r['lever'] for r in ok})} risk={[r['risk'] for r in ok]}")
            groups = [("ATTACK-only", att)] if att else []
        else:
            groups = []
        groups.insert(0, ("all usable", ok))
        for label, g in groups:
            if not g:
                continue
            for kk in (k, 1, 2):
                key = f"k{kk}"
                dec = [r[key] for r in g]
                out.append(f"   {label:11s} k={kk}: NOTIFY {pct(dec.count(NOTIFY), len(g))}  ROUTINE {pct(dec.count(ROUTINE), len(g))}")
            crit_met = {}
            for r in g:
                for c, stt in r["crit"].items():
                    crit_met.setdefault(c, []).append(stt)
            out.append("   criteria met: " + ", ".join(f"{c}={pct(v.count('met'), len(v))}" for c, v in sorted(crit_met.items())))
            der = [r["derived"] for r in g if r["derived"] is not None]
            ato = [r["atomic"] for r in g if r["atomic"] is not None]
            drs = [r["drs"] for r in g if r["drs"] is not None]
            out.append(f"   derived_facts mean={sum(der)/len(der):.2f} (n={len(der)}) atomic mean={sum(ato)/len(ato) if ato else float('nan'):.2f} "
                       f"drs mean={sum(drs)/len(drs) if drs else float('nan'):.2f} words mean={sum(r['words'] for r in g)/len(g):.0f}")
        flags = {}
        for r in rs:
            for f in r["flags"]:
                flags[f] = flags.get(f, 0) + 1
        out.append(f"   flags: {flags}")
    cost = 0.0
    out.append("\n== usage/cost")
    for m, (i, o) in usage.items():
        pi, po = PRICE.get(m, (0, 0))
        c = i * pi + o * po
        cost += c
        out.append(f"   {m}: in={i} out={o} ${c:.3f}")
    out.append(f"   TOTAL ${cost:.3f}")
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("log_dir")
    p.add_argument("--k", type=int, default=3)
    p.add_argument("--dump", action="store_true", help="write per-episode jsonl + private sheets to <log_dir>/_dev")
    a = p.parse_args()
    rows, usage = rows_from(a.log_dir)
    print(summarise(rows, usage, a.k))
    if a.dump:
        d = pathlib.Path(a.log_dir) / "_dev"
        d.mkdir(exist_ok=True)
        with open(d / "episodes.jsonl", "w") as fh:
            for r in rows:
                fh.write(json.dumps({k: v for k, v in r.items() if k not in ("sheet", "public")}) + "\n")
        for r in rows:
            (d / f"{r['id']}.sheet.txt").write_text(r["sheet"] or "")
            (d / f"{r['id']}.public.txt").write_text(r["public"] or "")
            (d / f"{r['id']}.rationale.txt").write_text(r["rationale"] or "")
        print(f"dumped {len(rows)} episodes to {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
