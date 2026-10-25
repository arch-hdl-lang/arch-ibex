#!/usr/bin/env python3
"""Per-rising-edge table of VCD signals whose hierarchical name matches.

    vcd_table.py <w.vcd> <clock_path_regex> <signal_regex>... [--hex]
Values are sampled just before each rising edge of the clock (the value the
flops see).
"""
import re
import sys


def main():
    path, clk_re, *sig_res = sys.argv[1:]
    scope, ids, order = [], {}, []
    clk_id = None
    with open(path) as fh:
        for line in fh:
            t = line.split()
            if not t:
                continue
            if t[0] == "$scope":
                scope.append(t[2])
            elif t[0] == "$upscope":
                scope.pop()
            elif t[0] == "$var":
                full = ".".join(scope + [t[4]])
                if clk_id is None and re.search(clk_re, full):
                    clk_id = t[3]
                for r in sig_res:
                    if re.search(r, full) and full not in order:
                        ids.setdefault(t[3], []).append(full)
                        order.append(full)
            elif t[0] == "$enddefinitions":
                break
        short = {f: f.split(".")[-1] for f in order}
        print(" | ".join(short[f] for f in order))
        val, clk = {}, 0
        for line in fh:
            line = line.strip()
            if not line or line[0] == "#" or line[0] == "$":
                continue
            if line[0] == "b":
                v, i = line[1:].split()
            else:
                v, i = line[0], line[1:]
            if i == clk_id:
                nv = 1 if v == "1" else 0
                if nv == 1 and clk == 0:
                    print(" | ".join(val.get(f, "?") for f in order))
                clk = nv
            for f in ids.get(i, []):
                try:
                    val[f] = format(int(v, 2), "x")
                except ValueError:
                    val[f] = v


if __name__ == "__main__":
    main()
