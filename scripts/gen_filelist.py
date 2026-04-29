#!/usr/bin/env python3
"""Emit a verilator-ready filelist that:

  1. Includes upstream Ibex sources from $IBEX_ROOT, MINUS any module
     stem listed in SWAPPED (those are now provided by ARCH-built .sv
     in build/).
  2. Includes our hand-written SoC scaffolding from soc/.
  3. Includes every .sv under build/ (ARCH-emitted modules + their
     auto-generated .archi headers — only .sv is fed to verilator).

Run after `scripts/build.sh`. Output goes to stdout or to the path in
the first positional arg.

The SWAPPED set is the single source of truth for which leaf module is
ARCH-side vs upstream. Add to this list as each Phase A/B/C swap lands.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


# Set of upstream Ibex module *stems* (sans .sv) that have been replaced
# by an ARCH-built equivalent in build/. Ibex itself in $IBEX_ROOT/rtl
# stays untouched; we just don't include those .sv lines in the filelist.
SWAPPED: set[str] = {
    # Phase A targets — populated as each lands:
    "ibex_alu",
    # "ibex_register_file_ff",
    # "ibex_counter",
    # "ibex_decoder",
    # "ibex_compressed_decoder",
    # "ibex_multdiv_slow",   # merged into IbexMultdiv
    # "ibex_multdiv_fast",   # merged into IbexMultdiv
    # "ibex_fetch_fifo",
    # "ibex_load_store_unit",
    # "ibex_prefetch_buffer",
    # Phase B:
    # "ibex_ex_block",
    # "ibex_wb_stage",
    # "ibex_if_stage",
    # "ibex_controller",
    # "ibex_id_stage",
    # Phase C:
    # "ibex_core",
    # "ibex_top",
    # CSR file is replaced by rdl2arch-riscv generator + hybrid wrapper:
    "ibex_cs_registers",
}


REPO_ROOT = Path(__file__).resolve().parent.parent
SOC_DIR = REPO_ROOT / "soc"
BUILD_DIR = REPO_ROOT / "build"


def ibex_root() -> Path:
    env = os.environ.get("IBEX_ROOT")
    if env:
        return Path(env).expanduser()
    return Path.home() / "github" / "ibex"


def collect_upstream_ibex() -> list[Path]:
    rtl = ibex_root() / "rtl"
    if not rtl.is_dir():
        raise SystemExit(f"IBEX_ROOT/rtl not found at {rtl}")
    files = [p for p in rtl.glob("*.sv") if p.stem not in SWAPPED]
    # Verilator processes files in command-file order. Package files (those
    # holding `package ... endpackage` typedefs) must precede every consumer
    # that references `pkg_name::*`. Hoist `*_pkg.sv` to the front; the rest
    # sort alphabetically.
    pkgs    = sorted(p for p in files if p.stem.endswith("_pkg"))
    others  = sorted(p for p in files if not p.stem.endswith("_pkg"))
    return pkgs + others


def collect_soc() -> list[Path]:
    return sorted(SOC_DIR.glob("*.sv"))


def collect_arch_built() -> list[Path]:
    if not BUILD_DIR.is_dir():
        return []
    return sorted(BUILD_DIR.glob("*.sv"))


def main() -> None:
    out_lines: list[str] = []
    out_lines.append("// arch-ibex filelist — auto-generated, do not edit")
    out_lines.append(f"// SWAPPED ({len(SWAPPED)}): {sorted(SWAPPED)}")
    out_lines.append("")
    out_lines.append("// Upstream Ibex (filtered):")
    out_lines.extend(str(p) for p in collect_upstream_ibex())
    out_lines.append("")
    out_lines.append("// arch-ibex SoC scaffolding:")
    out_lines.extend(str(p) for p in collect_soc())
    out_lines.append("")
    out_lines.append("// ARCH-emitted modules:")
    out_lines.extend(str(p) for p in collect_arch_built())

    text = "\n".join(out_lines) + "\n"

    if len(sys.argv) >= 2:
        Path(sys.argv[1]).write_text(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
