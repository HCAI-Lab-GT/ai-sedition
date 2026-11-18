"""Aggregate a completed sedition run: what separated the arms, and what did not.

Reports valid/invalid first, because every rate below is conditional on the
episode surviving, and on a provider with no forced JSON the survival rate is
itself a finding.
"""
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Windows consoles default to cp1252 and mangle the em dashes below.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from inspect_ai.log import read_eval_log, list_eval_logs

from sedition.scoring.metrics import (
    derived_rate_primary,
    joint_and_conditional_success,
    lever_distribution,
)
from sedition_inspect.episodes import episode_rows
from sedition_inspect.provenance import run_provenance

LOG_DIR = sys.argv[1] if len(sys.argv) > 1 else "logs/run-llama-01"

infos = list_eval_logs(LOG_DIR)
print(f"{len(infos)} log file(s) in {LOG_DIR}\n")

rows = []
for info in infos:
    log = read_eval_log(info.name)
    if not log.samples:
        print(f"  {log.status}: no samples")
        continue
    # Provenance first, and unconditionally. Every number below is only
    # interpretable against which models produced it and which scorer graded
    # it, and this run stack must never be pooled with another.
    for line in run_provenance(log).lines():
        print(line)
    print()

# One reader, shared with the matrix runner's stopping checks. If these two
# read `flags` differently, a rule could halt a run this report calls healthy.
rows = episode_rows(LOG_DIR)

print(f"episodes: {len(rows)}")
valid = [r for r in rows if not r["invalid"]]
print(f"  valid   : {len(valid)}")
print(f"  invalid : {len(rows) - len(valid)}")
print(f"  refused : {sum(r['refused'] for r in rows)}")
deg = sum(1 for r in rows if "DEGENERATE_OUTPUT" in r["flags"])
if rows:
    print(f"  degenerate: {deg}/{len(rows)} ({deg/len(rows):.1%})"
          "   — looped output, excluded from fact-formation means")

flags = Counter(f for r in rows for f in r["flags"])
print("\nflags (episodes carrying each):")
for f, n in flags.most_common():
    print(f"  {n:3d}/{len(rows)}  {f}")


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def fmt(x, w=7):
    return f"{x:{w}.3f}" if isinstance(x, float) else f"{'—':>{w}}"


def table(rs, key, title, cols=("atomic", "derived", "officer", "drs", "partition")):
    print("\n" + "=" * 96)
    print(title + f"   (n={len(rs)} valid episodes)")
    print("=" * 96)
    hdr = f"{'group':24s} {'n':>3s} {'words':>6s} " + " ".join(f"{c:>9s}" for c in cols)
    print(hdr)
    groups = defaultdict(list)
    for r in rs:
        groups[str(key(r))].append(r)
    for g in sorted(groups):
        sub = groups[g]
        w = mean(r["words"] for r in sub)
        line = f"{g:24s} {len(sub):3d} " + (f"{w:6.0f} " if w else f"{'—':>6s} ")
        line += " ".join(fmt(mean(r[c] for r in sub), 9) for c in cols)
        print(line)
    return groups


if valid:
    table(valid, lambda r: r["cell"], "BY CELL")
    table(valid, lambda r: r["policy"], "BY POLICY  — the manipulation under test")
    table(valid, lambda r: r["version"], "BY SOURCE VERSION  — SS vs MS")
    table(valid, lambda r: f'{r["packet"]} {r["policy"][:6]}', "BY PACKET x POLICY")

    hon = [r for r in valid if r["policy"] == "honest"]
    sab = [r for r in valid if r["policy"] != "honest"]
    print("\n" + "=" * 96)
    print("HEADLINE  honest - saboteur")
    print("=" * 96)
    for c in ("derived", "atomic", "drs", "officer", "partition"):
        h, s_ = mean(r[c] for r in hon), mean(r[c] for r in sab)
        if h is None or s_ is None:
            continue
        print(f"  {c:10s} honest {h:6.3f}   saboteur {s_:6.3f}   delta {h - s_:+6.3f}")

    print("\nofficer decisions (round of record):")
    for pol in ("honest", "basic_saboteur", "strategic_saboteur"):
        cnt = Counter(r["wo"] for r in valid if r["policy"] == pol)
        if cnt:
            print(f"  {pol:18s} {dict(cnt)}")
    print(f"  clarification requested: {sum(r['clarified'] for r in valid)}/{len(valid)}")

    print("\n" + "=" * 96)
    print("PREREGISTERED OUTCOMES  — docs/PREREGISTRATION.md")
    print("=" * 96)

    d = derived_rate_primary(valid)
    print(f"  P1 derived, primary (E01 excluded) : {fmt(d['primary_derived_rate'])}"
          f"   n={d['primary_n']}")
    print(f"     all packets                     : {fmt(d['all_packets_derived_rate'])}"
          f"   n={d['all_packets_n']}")
    print(f"     excluded {','.join(d['excluded_packets'])}          : "
          f"{fmt(d['excluded_derived_rate'])}   n={d['excluded_n']}")

    j = joint_and_conditional_success(valid)
    if j:
        print(f"\n  P4 joint success (all saboteur)    : {fmt(j['joint_success_rate'])}"
              f"   n={j['n_saboteur_episodes']}")
        print(f"     attack-conditional evasion      : "
              f"{fmt(j['attack_conditional_success_rate'])}   n={j['n_attacked']}")
        print(f"     abstention rate                 : {fmt(j['abstention_rate'])}")

    lv = lever_distribution(valid)
    if lv:
        print("\n  S2 lever distribution — strategic cells only")
        for bucket in ("attacked", "abstained"):
            t = lv[bucket]
            if not t["n"]:
                continue
            print(f"     {bucket:9s} n={t['n']:3d}  families={t['families']}")
            for lever, n in sorted(t["levers"].items(), key=lambda kv: -kv[1]):
                print(f"                     {n:3d}  {lever}")

Path("run_rows.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print(f"\nper-episode rows: {Path('run_rows.json').resolve()}")
