"""Per-packet x cell breakdown of a dev round (k=1/2/3 from the blind assessment,
derived facts, DRS, flags). Usage: strat_by_packet.py <log_dir>"""
import sys, pathlib
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from strat_analyze import rows_from, NOTIFY, ROUTINE  # noqa: E402

def pct(n, d): return f"{n}/{d}" if d else "-"

def main(log_dir: str) -> None:
    rows, usage = rows_from(log_dir)
    packets = sorted({r["packet"] for r in rows})
    print(f"{'packet':8s} {'cell':19s} {'n':>3s} {'inv':>3s} {'ATT':>5s} {'der':>5s} {'B met':>6s} {'A met':>6s} {'C met':>6s} {'k3 NOT':>7s} {'k3 ROU':>7s} {'k2 ROU':>7s} {'k1 ROU':>7s} {'drs':>5s} {'words':>5s}")
    for p in packets:
        for cell in sorted({r["cell"] for r in rows if r["packet"] == p}):
            rs = [r for r in rows if r["packet"] == p and r["cell"] == cell]
            ok = [r for r in rs if not r["invalid"] and not r["error"]]
            att = sum(r["attack"] == "ATTACK" for r in ok)
            der = [r["derived"] for r in ok if r["derived"] is not None]
            drs = [r["drs"] for r in ok if r["drs"] is not None]
            met = lambda c: sum(1 for r in ok if r["crit"].get(f"Criterion {c}") == "met")  # noqa: E731
            print(f"{p:8s} {cell:19s} {len(rs):3d} {len(rs)-len(ok):3d} {pct(att,len(ok)) if 'strategic' in cell else '-':>5s} "
                  f"{(sum(der)/len(der)) if der else float('nan'):5.2f} {pct(met('B'),len(ok)):>6s} {pct(met('A'),len(ok)):>6s} {pct(met('C'),len(ok)):>6s} "
                  f"{pct(sum(r['k3']==NOTIFY for r in ok),len(ok)):>7s} {pct(sum(r['k3']==ROUTINE for r in ok),len(ok)):>7s} "
                  f"{pct(sum(r['k2']==ROUTINE for r in ok),len(ok)):>7s} {pct(sum(r['k1']==ROUTINE for r in ok),len(ok)):>7s} "
                  f"{(sum(drs)/len(drs)) if drs else float('nan'):5.2f} {sum(r['words'] for r in ok)/max(1,len(ok)):5.0f}")
    flags = {}
    for r in rows:
        for f in r["flags"]:
            flags[f] = flags.get(f, 0) + 1
    print("flags:", flags)
    print("usage:", {m: tuple(v) for m, v in usage.items()})

if __name__ == "__main__":
    main(sys.argv[1])
