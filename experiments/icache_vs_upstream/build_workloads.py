#!/usr/bin/env python3
"""Build the icache-vs-upstream workloads as .vmem images for the mini SoC.

    build_workloads.py <out_dir> [--ibex-root ~/github/ibex]

Every image uses simple_system's crt0.S + link.ld (as the CoreMark harness in
tests/test_coremark_compare.py does) and is built twice, for rv32im and
rv32imc:

  coremark_<isa>   CoreMark with exactly the flags, patches and defaults of
                   tests/test_coremark_compare.py (ITERATIONS=1,
                   TOTAL_DATA_SIZE=1200, PROFILE_RUN, COREMARK_EXEC_MASK=7);
                   only -march differs between the two builds.
  rt_<bench>_<isa> riscv-tests benchmarks (vendor/riscv-tests/benchmarks),
                   compiled with the suite's own RISCV_GCC_OPTS and its
                   common/syscalls.c, patched so output goes to simulator_ctrl
                   and exit() halts the simulation (rt_shim.c). The timed
                   region is the suite's own setStats(1)..setStats(0)
                   (mm: its own last-repetition mcycle delta).

Writes <out_dir>/<name>.{elf,bin,vmem,dis} and <out_dir>/manifest.json; a
benchmark that does not build is recorded with its compiler error.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
BIN2VMEM = REPO / "tests" / "sw" / "bin2vmem.py"
COMPAT = HERE / "compat"
SHIM = HERE / "rt_shim.c"

GCC = "riscv64-elf-gcc"
OBJCOPY = "riscv64-elf-objcopy"
OBJDUMP = "riscv64-elf-objdump"

ISAS = {"rv32im": "rv32im_zicsr", "rv32imc": "rv32imc_zicsr"}
# Single-core, bare-metal benchmarks. mt-* need several harts and pmp needs
# a trap-handling environment; neither fits this SoC.
RT_BENCHES = ["median", "qsort", "rsort", "towers", "vvadd", "multiply",
              "mm", "spmv", "dhrystone"]


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)


def finish(elf: Path, out: Path, name: str) -> Path:
    bin_path = out / f"{name}.bin"
    vmem = out / f"{name}.vmem"
    with (out / f"{name}.dis").open("w") as fh:
        subprocess.run([OBJDUMP, "-d", str(elf)], check=True, stdout=fh)
    subprocess.run([OBJCOPY, "-O", "binary", str(elf), str(bin_path)], check=True)
    subprocess.run([sys.executable, str(BIN2VMEM), str(bin_path), str(vmem)], check=True)
    return vmem


def text_size(elf: Path) -> int:
    r = run(["riscv64-elf-size", "-A", elf])
    for line in r.stdout.splitlines():
        f = line.split()
        if f and f[0] == ".text":
            return int(f[1])
    return -1


def build_coremark(ibex: Path, out: Path, isa: str) -> dict:
    """Mirror of tests/test_coremark_compare.py::built_coremark (defaults)."""
    coremark_dir = ibex / "vendor" / "eembc_coremark"
    port_dir = ibex / "examples" / "sw" / "benchmarks" / "coremark" / "ibex"
    simple_dir = ibex / "examples" / "sw" / "simple_system" / "common"
    name = f"coremark_{isa}"
    work = out / f"{name}.src"
    (work / "compat" / "sys").mkdir(parents=True, exist_ok=True)
    (work / "compat" / "sys" / "types.h").write_text(
        "#ifndef ARCH_IBEX_COREMARK_SYS_TYPES_H\n"
        "#define ARCH_IBEX_COREMARK_SYS_TYPES_H\n"
        "typedef unsigned int size_t;\n"
        "#endif\n"
    )
    exec_mask = 7
    portme = work / "core_portme.c"
    portme.write_text((port_dir / "core_portme.c").read_text().replace(
        "volatile ee_s32 seed5_volatile = 0;",
        "volatile ee_s32 seed5_volatile = COREMARK_EXEC_MASK;"))
    main = work / "core_main.c"
    main.write_text((coremark_dir / "core_main.c").read_text().replace(
        "results[0].execs=get_seed_32(5);",
        "results[0].execs=COREMARK_EXEC_MASK;"))
    sources = [main, coremark_dir / "core_list_join.c", coremark_dir / "core_matrix.c",
               coremark_dir / "core_state.c", coremark_dir / "core_util.c", portme,
               port_dir / "ee_printf.c", simple_dir / "simple_system_common.c",
               simple_dir / "crt0.S"]
    cflags = [f"-march={ISAS[isa]}", "-mabi=ilp32", "-static", "-mcmodel=medlow",
              "-mtune=sifive-3-series", "-O3", "-falign-functions=16",
              "-funroll-all-loops", "-finline-functions", "-falign-jumps=4",
              "-nostdlib", "-nostartfiles", "-ffreestanding", "-mstrict-align",
              "-DTOTAL_DATA_SIZE=1200", "-DMAIN_HAS_NOARGC=1", "-DPROFILE_RUN=1",
              "-DITERATIONS=1", f"-DCOREMARK_EXEC_MASK={exec_mask}", "-DHAS_FLOAT=0",
              "-DSUPPRESS_PCOUNT_DUMP=1",
              "-DCOMPILER_FLAGS=\"arch-ibex coremark compare\"",
              f"-I{work / 'compat'}", f"-I{simple_dir}", f"-I{port_dir}", f"-I{coremark_dir}"]
    elf = out / f"{name}.elf"
    r = run([GCC, *cflags, "-o", elf, *sources, f"-Wl,-T,{simple_dir / 'link.ld'}",
             "-Wl,--no-relax", f"-Wl,-Map={out / (name + '.map')}", "-lgcc"])
    if r.returncode != 0:
        return {"name": name, "ok": False, "error": r.stderr[-3000:]}
    vmem = finish(elf, out, name)
    return {"name": name, "ok": True, "vmem": str(vmem), "kind": "coremark",
            "isa": isa, "text_bytes": text_size(elf)}


def patched_syscalls(src: Path, dst: Path) -> None:
    s = src.read_text()
    # syscall(): only SYS_write is used (printstr / putchar); send the bytes
    # to simulator_ctrl's output register instead of Spike's tohost.
    s, n = re.subn(
        r"static uintptr_t syscall\(uintptr_t which.*?\n}\n",
        "static uintptr_t syscall(uintptr_t which, uint64_t arg0, uint64_t arg1, uint64_t arg2)\n"
        "{\n"
        "  if (which == SYS_write) {\n"
        "    const char *p = (const char *)(uintptr_t)arg1;\n"
        "    for (uint64_t k = 0; k < arg2; k++)\n"
        "      *(volatile uint32_t *)0x20000 = (unsigned char)p[k];\n"
        "  }\n"
        "  return arg2;\n"
        "}\n",
        s, count=1, flags=re.S)
    assert n == 1, "syscall() not found"
    s, n = re.subn(
        r"void __attribute__\(\(noreturn\)\) tohost_exit\(uintptr_t code\)\n{.*?\n}\n",
        "void __attribute__((noreturn)) tohost_exit(uintptr_t code)\n"
        "{\n"
        "  printf(\"rt_exit_code=%d\\\\n\", (int)code);\n"
        "  *(volatile uint32_t *)0x20008 = 1;\n"
        "  while (1);\n"
        "}\n",
        s, count=1, flags=re.S)
    assert n == 1, "tohost_exit() not found"
    # Single hart, no TLS segment in simple_system's link.ld: __thread is
    # compiled away (-D__thread=) and init_tls() becomes a no-op.
    s, n = re.subn(r"static void init_tls\(\)\n{.*?\n}\n",
                   "static void init_tls()\n{\n}\n", s, count=1, flags=re.S)
    assert n == 1, "init_tls() not found"
    # printf/sprintf/putchar are used before their definitions in tohost_exit.
    s = s.replace('#include "util.h"', '#include "util.h"\nint printf(const char* fmt, ...);', 1)
    dst.write_text(s)


def build_rt(ibex: Path, out: Path, bench: str, isa: str) -> dict:
    rt = ibex / "vendor" / "riscv-tests" / "benchmarks"
    simple_dir = ibex / "examples" / "sw" / "simple_system" / "common"
    env_dir = ibex / "vendor" / "riscv-test-env"
    name = f"rt_{bench}_{isa}"
    work = out / f"{name}.src"
    work.mkdir(parents=True, exist_ok=True)
    patched_syscalls(rt / "common" / "syscalls.c", work / "syscalls.c")
    arch = [f"-march={ISAS[isa]}", "-mabi=ilp32"]
    crt0 = work / "crt0.o"
    r = run([GCC, *arch, "-Dmain=rt_entry", f"-I{simple_dir}", "-c", "-o", crt0,
             simple_dir / "crt0.S"])
    if r.returncode != 0:
        return {"name": name, "ok": False, "error": r.stderr[-3000:]}
    # The suite's RISCV_GCC_OPTS (benchmarks/Makefile), minus -mcmodel=medany
    # (medlow, as CoreMark: the image lives at 0x100000).
    opts = ["-DPREALLOCATE=1", "-mcmodel=medlow", "-static", "-std=gnu99", "-O2",
            "-ffast-math", "-fno-common", "-fno-builtin-printf",
            "-fno-tree-loop-distribute-patterns",
            "-ffreestanding", "-nostdlib", "-nostartfiles", "-D__thread=",
            # GCC 15 rejects dhrystone's K&R C by default.
            "-Wno-error=implicit-int", "-Wno-error=implicit-function-declaration"]
    incs = [f"-I{COMPAT}", f"-I{env_dir}", f"-I{rt / 'common'}", f"-I{rt / bench}"]
    srcs = sorted((rt / bench).glob("*.c")) + [work / "syscalls.c", SHIM, crt0]
    elf = out / f"{name}.elf"
    r = run([GCC, *arch, *opts, *incs, "-o", elf, *srcs,
             f"-Wl,-T,{simple_dir / 'link.ld'}", "-Wl,--no-relax",
             f"-Wl,-Map={out / (name + '.map')}", "-lgcc"])
    if r.returncode != 0:
        return {"name": name, "ok": False, "error": r.stderr[-3000:]}
    vmem = finish(elf, out, name)
    return {"name": name, "ok": True, "vmem": str(vmem), "kind": "rt", "bench": bench,
            "isa": isa, "text_bytes": text_size(elf)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--ibex-root", type=Path, default=Path.home() / "github" / "ibex")
    a = ap.parse_args()
    for t in (GCC, OBJCOPY, OBJDUMP):
        if shutil.which(t) is None:
            sys.exit(f"missing {t}")
    a.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for isa in ISAS:
        manifest.append(build_coremark(a.ibex_root, a.out, isa))
        for b in RT_BENCHES:
            manifest.append(build_rt(a.ibex_root, a.out, b, isa))
    for m in manifest:
        print(f"{m['name']:24s} {'ok' if m['ok'] else 'BUILD FAILED'}"
              f"{'  text=' + str(m['text_bytes']) if m['ok'] else ''}")
        if not m["ok"]:
            print("   " + m["error"].strip().splitlines()[-1][:200] if m["error"].strip() else "")
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
