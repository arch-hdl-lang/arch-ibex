#!/usr/bin/env python3
import os, pathlib, re, sys
S = pathlib.Path(os.environ["STUDY_SCRATCH"])
WANT = ("IbexIcacheOutputStage", "ibex_icache", "FbAgeArb", "BusRespFifo", "RamPortArb", "InvalCtrl", "ibex_top")
for cfg in sys.argv[1:]:
    R = S / "res" / cfg
    t = (R / "ecp5_hier.stat").read_text()
    blocks = re.split(r"^=== (.*?) ===$", t, flags=re.M)
    row = {}
    for name, body in zip(blocks[1::2], blocks[2::2]):
        short = name.split("\\")[-1]
        if any(short == w or short.startswith(w) for w in WANT):
            l = re.search(r"^\s+(\d+)\s+LUT4\s*$", body, re.M)
            f = re.search(r"^\s+(\d+)\s+TRELLIS_FF\s*$", body, re.M)
            row[short] = (int(l.group(1)) if l else 0, int(f.group(1)) if f else 0)
    a = (R / "sky130_hier_area.rpt").read_text()
    areas = {m.group(1).split("\\")[-1]: float(m.group(2)) for m in re.finditer(r"Chip area for module '(.*?)': ([0-9.]+)", a)}
    sel = {k: v for k, v in areas.items() if any(k.startswith(w) for w in ("IbexIcacheOutputStage", "ibex_icache", "ibex_top"))}
    print(cfg, "ecp5 hier (LUT4,FF):", row)
    print(cfg, "sky130 hier area:", sel)
