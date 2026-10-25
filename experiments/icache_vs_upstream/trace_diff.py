#!/usr/bin/env python3
"""Attribute the cycle difference between two runs of the same program on
the same core with different icaches, from the Ibex tracer logs.

    trace_diff.py <trace_ref> <trace_dut> [--window lo_pc_cycle..]

Both runs must retire the same instruction sequence (same core RTL, same
binary); the comparison stops at the first PC divergence. For each retired
instruction i, gap = cycle[i] - cycle[i-1]; the extra cycles of the DUT run
(gap_dut - gap_ref) are charged to instruction i and binned by how it was
fetched:

  seq-straddle   sequential, 32-bit, PC % 8 == 6 (spans two 64-bit lines)
  seq-cold       sequential, first execution of its 64-bit line
  seq-xline1     sequential, first instruction of a new line, and the
                 previous line held the last taken-transfer target
                 (@N: byte offset of that target within its line)
  seq-xline2+    sequential, first instruction of a new line, later crossing
  seq-inline     other sequential (same line as the previous instruction)
  tgt-cold       target of a taken control transfer, line first executed
  tgt-straddle   target of a taken transfer, 32-bit at PC % 8 == 6
  tgt            other targets

"first execution" approximates a compulsory miss; capacity/conflict misses
are not modelled. The bins are fetch-side labels only: a delay charged to an
instruction can also be data-side, but both runs share the core and the
data path.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict

LINE = re.compile(r"^\s*(\d+)\s+(\d+)\s+([0-9a-f]{8})\s+([0-9a-f]{4,8})\s+(\S+)")


def load(path):
    out = []
    with open(path) as fh:
        for line in fh:
            m = LINE.match(line)
            if m:
                out.append((int(m.group(2)), int(m.group(3), 16), len(m.group(4)) == 8, m.group(5)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ref")
    ap.add_argument("dut")
    ap.add_argument("--from-pc", type=lambda s: int(s, 16), default=None,
                    help="start counting at the first retirement of this PC")
    ap.add_argument("--to-pc", type=lambda s: int(s, 16), default=None,
                    help="stop at the next retirement of this PC after the start")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()
    r, d = load(a.ref), load(a.dut)
    n = min(len(r), len(d))
    div = next((i for i in range(n) if r[i][1] != d[i][1]), n)
    start = 1
    if a.from_pc is not None:
        start = next(i for i in range(1, div) if r[i][1] == a.from_pc)
    stop = div
    if a.to_pc is not None:
        stop = next((i for i in range(start + 1, div) if r[i][1] == a.to_pc), div)
    seen = set()
    last_tgt_line, last_tgt_off = -1, 0
    for i in range(0, start):
        seen.add(r[i][1] >> 3)
    bins = defaultdict(lambda: [0, 0, 0])  # count, ref cycles, extra
    by_pc = defaultdict(int)
    for i in range(start, stop):
        cyc_r, pc, is32, mn = r[i]
        prev_pc, prev32 = r[i - 1][1], r[i - 1][2]
        seq = pc == prev_pc + (4 if prev32 else 2)
        line = pc >> 3
        cold = line not in seen
        straddle = is32 and (pc & 7) == 6
        if straddle:
            seen.add(line + 1)
        seen.add(line)
        if not seq:
            last_tgt_line, last_tgt_off = line, pc & 7
        kind = ("seq" if seq else "tgt") + ("-straddle" if straddle else "-cold" if cold else "")
        if kind == "seq" and line != (prev_pc >> 3):
            # first instruction of a line reached sequentially: the first
            # line crossing after a taken transfer, or a later one
            kind = (f"seq-xline1@{last_tgt_off}" if (prev_pc >> 3) == last_tgt_line
                    else "seq-xline2+")
        elif kind == "seq":
            kind = "seq-inline"
        g_r = cyc_r - r[i - 1][0]
        g_d = d[i][0] - d[i - 1][0]
        b = bins[kind]
        b[0] += 1
        b[1] += g_r
        b[2] += g_d - g_r
        by_pc[pc] += g_d - g_r
    tot_r = r[stop - 1][0] - r[start - 1][0]
    tot_d = d[stop - 1][0] - d[start - 1][0]
    print(f"instructions compared: {stop - start} (diverge at {div} of {n})")
    print(f"cycles: ref {tot_r}  dut {tot_d}  extra {tot_d - tot_r} ({100.0 * (tot_d - tot_r) / tot_r:+.2f}%)")
    print(f"{'bin':14s} {'instrs':>9s} {'ref cyc':>9s} {'extra':>8s} {'extra/instr':>11s}")
    for k in sorted(bins, key=lambda k: -abs(bins[k][2])):
        c, cr, x = bins[k]
        print(f"{k:14s} {c:9d} {cr:9d} {x:8d} {x / c:11.3f}")
    print(f"top PCs by extra cycles:")
    for pc, x in sorted(by_pc.items(), key=lambda kv: -abs(kv[1]))[: a.top]:
        print(f"  {pc:08x} {x:+d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
