#!/usr/bin/env python3
"""icache swap matrix: build the four SoC models and run the workloads.

    matrix.py build <variant> <model_dir>        one Verilator model
    matrix.py run <models_root> <workload_dir> <out.json> [--jobs N]

Variants (tests/conftest.py ARCH_IBEX_ICACHE_MATRIX):
  U     upstream core + upstream icache
  UAic  upstream core + Arch icache (build/ibex_icache.sv + its helpers)
  A     Arch core + Arch icache (the arch-ibex DUT)
  AUic  Arch core + upstream icache (rtl/ibex_icache.sv)

The model is tests/test_coremark_compare.py's: its DUT filelist (which picks
the swaps through conftest._arch_swap_sv, i.e. the variant hook), its
Verilator flags and its C++ testbench (tests/cpp/ibex_mini_soc_coremark_tb.cpp),
which loads VMEM_PATH and runs to simulator_ctrl's halt. Variant U through
the DUT path is the upstream reference: no swaps, and the same
ibex_cs_registers_hybrid.sv substitution _ref_filelist makes.

`run` expects <models_root>/<variant>/Vibex_mini_soc and the manifest.json
written by build_workloads.py; it writes one record per (variant, workload).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
# MATRIX_REPO: build the models from another arch-ibex checkout (its
# tests/ and build/), e.g. a fix branch, with this checkout's scripts.
REPO = Path(os.environ.get("MATRIX_REPO", HERE.parent.parent)).resolve()
VARIANTS = ["U", "UAic", "A", "AUic"]


def cmd_build(variant: str, model_dir: Path) -> int:
    os.environ["ARCH_IBEX_ICACHE_MATRIX"] = variant
    sys.path.insert(0, str(REPO))
    from tests import conftest as shared
    from tests import test_coremark_compare as cm

    arch_bin = os.environ["ARCH_BIN"]
    ibex_root = Path(os.environ.get("IBEX_ROOT", Path.home() / "github" / "ibex"))
    model_dir.mkdir(parents=True, exist_ok=True)
    fl = cm._dut_filelist(arch_bin, ibex_root, "fusesoc", model_dir / "filelist")
    # Record exactly which icache / core sources went in.
    srcs = [str(p) for p in fl["extra_sv"]]
    vc = Path(fl["vc_path"]).read_text().splitlines()
    picked = {
        "variant": variant,
        "extra_sv": srcs,
        "vc_icache": [l for l in vc if "ibex_icache" in l],
        "vc_core": [l for l in vc if l.strip().endswith(("ibex_core.sv", "ibex_if_stage.sv", "ibex_top.sv"))],
        "shadowed": sorted(shared._SV_SHADOWED_BY_FORKS),
    }
    (model_dir / "sources.json").write_text(json.dumps(picked, indent=1))
    exe = cm._build_model(fl, model_dir / "sim")
    print(f"[{variant}] model: {exe}")
    return 0


def parse(kind: str, log: str, stdout: str) -> dict:
    r: dict = {}
    m = re.search(r"ARCH_IBEX_SIM_CYCLES=(\d+)", stdout)
    r["sim_cycles"] = int(m.group(1)) if m else None
    if kind == "coremark":
        t = re.search(r"^Total ticks\s*:\s*(\d+)", log, re.M)
        i = re.search(r"^Iterations\s*:\s*(\d+)", log, re.M)
        r["cycles"] = int(t.group(1)) if t else None
        r["iterations"] = int(i.group(1)) if i else None
        r["validated"] = "Correct operation validated" in log
        r["errors"] = "Errors detected" in log
        r["pass"] = bool(t and i and r["validated"] and not r["errors"])
        if r["cycles"]:
            r["cm_per_mhz"] = 1e6 * r["iterations"] / r["cycles"]
        return r
    if kind == "mb":
        r["kernels"] = {m.group(1): {"cycles": int(m.group(2)), "instrs": int(m.group(3))}
                        for m in re.finditer(r"^mb (\S+) cycles=(\d+) instrs=(\d+)", log, re.M)}
    mc = re.search(r"^mcycle = (\d+)", log, re.M)
    mi = re.search(r"^minstret = (\d+)", log, re.M)
    if mc is None:  # mm prints its own counters
        mc = re.search(r"^C0: (\d+) cycles", log, re.M)
        mi = re.search(r"^C0: (\d+) instructions", log, re.M)
    ex = re.search(r"rt_exit_code=(-?\d+)", log)
    r["cycles"] = int(mc.group(1)) if mc else None
    r["instret"] = int(mi.group(1)) if mi else None
    r["exit_code"] = int(ex.group(1)) if ex else None
    r["trap"] = (re.search(r"rt_trap=.*", log) or [None])[0]
    r["pass"] = r["exit_code"] == 0 and r["trap"] is None and (
        r["cycles"] is not None or bool(r.get("kernels")))
    return r


def run_one(exe: Path, wl: dict, out_dir: Path) -> dict:
    run_dir = out_dir / f"{wl['variant']}__{wl['name']}"
    run_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["VMEM_PATH"] = wl["vmem"]
    env["COREMARK_MAX_CYCLES"] = str(400_000_000)
    p = subprocess.run([str(exe)], cwd=run_dir, env=env, capture_output=True, text=True)
    (run_dir / "stdout.txt").write_text(p.stdout)
    (run_dir / "stderr.txt").write_text(p.stderr)
    log_path = run_dir / "ibex_mini_soc.log"
    log = log_path.read_text(errors="replace") if log_path.exists() else ""
    rec = {"variant": wl["variant"], "workload": wl["name"], "isa": wl["isa"],
           "kind": wl["kind"], "returncode": p.returncode}
    rec.update(parse(wl["kind"], log, p.stdout))
    if p.returncode != 0:
        rec["pass"] = False
    print(f"{wl['variant']:5s} {wl['name']:24s} cycles={rec.get('cycles')} "
          f"sim_cycles={rec.get('sim_cycles')} pass={rec['pass']}", flush=True)
    return rec


def cmd_run(models: Path, wl_dir: Path, out_json: Path, jobs: int, variants, only) -> int:
    manifest = [w for w in json.loads((wl_dir / "manifest.json").read_text()) if w["ok"]]
    if only:
        manifest = [w for w in manifest if any(re.fullmatch(o, w["name"]) for o in only)]
    tasks = []
    for v in variants:
        exe = models / v / "sim" / "Vibex_mini_soc"
        if not exe.is_file():
            sys.exit(f"missing model {exe}")
        for w in manifest:
            tasks.append((exe, dict(w, variant=v)))
    runs = out_json.parent / (out_json.stem + "_runs")
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        recs = list(ex.map(lambda t: run_one(t[0], t[1], runs), tasks))
    out_json.write_text(json.dumps(recs, indent=1))
    return 0 if all(r["pass"] for r in recs) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("variant", choices=VARIANTS)
    b.add_argument("model_dir", type=Path)
    r = sub.add_parser("run")
    r.add_argument("models", type=Path)
    r.add_argument("workloads", type=Path)
    r.add_argument("out", type=Path)
    r.add_argument("--jobs", type=int, default=8)
    r.add_argument("--variants", nargs="*", default=VARIANTS)
    r.add_argument("--only", nargs="*", default=None, help="workload name regexes")
    a = ap.parse_args()
    if a.cmd == "build":
        return cmd_build(a.variant, a.model_dir)
    return cmd_run(a.models, a.workloads, a.out, a.jobs, a.variants, a.only)


if __name__ == "__main__":
    sys.exit(main())
