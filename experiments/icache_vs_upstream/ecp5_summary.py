#!/usr/bin/env python3
"""Summarise the matrix's ECP5 runs: cells and fmax per (design, tag), and
where each seed's critical path starts/ends and whether it crosses the
icache (any cell name containing 'icache').

    ecp5_summary.py <repo>
"""
import glob, re, statistics as st, sys
from collections import defaultdict

repo = sys.argv[1]
rows = defaultdict(list)
for log in sorted(glob.glob(f"{repo}/flow/out/*_rsv/ecp5_*/nextpnr_seed*.log")):
    m = re.search(r"out/(\w+)_rsv/ecp5_(\w+)/nextpnr_seed(\d+)\.log", log)
    des, tag, seed = m.group(1), m.group(2), int(m.group(3))
    txt = open(log).read()
    fm = re.findall(r"Max frequency for clock 'clk_i': ([0-9.]+) MHz", txt)
    rep = txt[txt.rfind("Critical path report for clock 'clk_i'"):]
    rep = rep[: rep.find("\n\n")] if "\n\n" in rep else rep
    cells = re.findall(r"(?:Source|Sink) (\S+)", rep)
    start = cells[0] if cells else "?"
    end = cells[-1] if cells else "?"
    ic = sum("icache" in c for c in cells)
    rows[(des, tag)].append((seed, float(fm[-1]), start, end, ic, len(cells)))

def unit(c):  # coarse block name of a cell
    c = c.split(".")
    keep = [x for x in c if x.endswith(("_i", "_stage")) or x in ("icache_i", "output_stage")]
    return ".".join(keep[:3]) or c[0][:40]

order = ["U", "UAic", "A", "AUic"]
for des in order:
    for tag in ("w40", "def"):
        r = rows.get((des, tag))
        if not r:
            continue
        f = [x[1] for x in r]
        stat = open(f"{repo}/flow/out/{des}_rsv/ecp5_{tag}/synth.stat").read()
        cnt = {k: int(v) for v, k in re.findall(r"^\s+(\d+) +(LUT4|TRELLIS_FF|CCU2C)\s*$", stat, re.M)}
        icp = sum(1 for x in r if x[4])
        print(f"{des:5s} {tag:3s} LUT4={cnt.get('LUT4')} FF={cnt.get('TRELLIS_FF')} CCU2C={cnt.get('CCU2C')} "
              f"fmax n={len(f)} {st.mean(f):.2f}+-{st.stdev(f):.2f} [{min(f):.2f}-{max(f):.2f}] "
              f"crit-path-through-icache {icp}/{len(r)}")
        ends = defaultdict(int)
        for x in r:
            ends[(unit(x[2]), unit(x[3]))] += 1
        for (s, e), n in sorted(ends.items(), key=lambda kv: -kv[1])[:3]:
            print(f"      {n}x  {s}  ->  {e}")
