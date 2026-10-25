#!/usr/bin/env python3
"""Merge matrix.py result files into one table (timed-region cycles).

    results_table.py <res.json>...
"""
import json, sys
recs = [r for f in sys.argv[1:] for r in json.load(open(f))]
by = {(r["workload"], r["variant"]): r for r in recs}
wls = sorted({r["workload"] for r in recs if r["kind"] != "mb"},
             key=lambda w: (w.split("_")[-1], not w.startswith("coremark"), w))
print(f"| workload | U | U+Aic | Δ vs U | A | A+Uic | Δ A vs A+Uic | all pass |")
print("|---|---:|---:|---:|---:|---:|---:|:---:|")
for w in wls:
    c = {v: by[(w, v)]["cycles"] for v in ("U", "UAic", "A", "AUic")}
    ok = all(by[(w, v)]["pass"] for v in c)
    print(f"| {w} | {c['U']:,} | {c['UAic']:,} | {100*(c['UAic']/c['U']-1):+.2f}% | "
          f"{c['A']:,} | {c['AUic']:,} | {100*(c['A']/c['AUic']-1):+.2f}% | {'yes' if ok else 'NO'} |")
