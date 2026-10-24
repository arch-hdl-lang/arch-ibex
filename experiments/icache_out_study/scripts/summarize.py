#!/usr/bin/env python3
"""summarize.py cfg... -- print measurement table rows from $S/res/<cfg> and logs."""
import os, json, pathlib, re, statistics, sys
S = pathlib.Path(os.environ["STUDY_SCRATCH"])
W = pathlib.Path(os.environ["REPO_ROOT"])

def cells(stat, names):
    t = stat.read_text() if stat.exists() else ""
    out = {}
    for n in names:
        m = re.findall(r"^\s+(\d+)\s+%s\s*$" % re.escape(n), t, re.M)
        out[n] = int(m[-1]) if m else None
    return out

for cfg in sys.argv[1:]:
    R = S / "res" / cfg
    sa = cells(R / "icache_standalone.stat", ["LUT4", "TRELLIS_FF", "PFUMX", "L6MUX21", "CCU2C"])
    fu = cells(R / "ecp5_synth.stat", ["LUT4", "TRELLIS_FF", "PFUMX", "L6MUX21", "CCU2C"])
    fm = []
    for seed in range(1, 11):
        log = W / f"flow/out/arch/ecp5_{cfg}/nextpnr_seed{seed}.log"
        if log.exists():
            m = re.findall(r"Max frequency for clock 'clk_i': ([0-9.]+) MHz", log.read_text())
            if m and "Program finished normally" in log.read_text():
                fm.append(float(m[-1]))
    cm = (S / "logs" / cfg / "coremark.log")
    ticks = cmmhz = None
    if cm.exists():
        m = re.search(r"dut_ticks=(\d+).*dut_cm_mhz=([0-9.]+)", cm.read_text())
        if m: ticks, cmmhz = int(m.group(1)), float(m.group(2))
    area = None
    st = R / "sky130" / "synth.stat"
    if st.exists():
        m = re.search(r"Chip area for module '\\ibex_top': ([0-9.]+)", st.read_text())
        if m: area = float(m.group(1))
    est = R / "estimate" / "est.txt"
    wns = tns = None
    if est.exists():
        m = re.search(r"t3_repaired_lat wns_ns=(-?[0-9.]+) tns_ns=(-?[0-9.]+)", est.read_text())
        if m: wns, tns = float(m.group(1)), float(m.group(2))
    mean = statistics.mean(fm) if fm else None
    sd = statistics.stdev(fm) if len(fm) > 1 else None
    print(f"[{cfg}] standalone {sa}")
    print(f"[{cfg}] full ecp5 {fu}")
    if fm:
        print(f"[{cfg}] fmax n={len(fm)} mean={mean:.2f} sd={sd:.2f} min={min(fm):.2f} max={max(fm):.2f} seeds={fm}")
    print(f"[{cfg}] coremark ticks={ticks} cm/mhz={cmmhz} speed={cmmhz*mean if (cmmhz and mean) else None}")
    print(f"[{cfg}] sky130 area={area} wns(t3_repaired_lat)={wns} tns={tns}")
