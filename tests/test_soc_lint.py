"""Phase 6.1 — Ibex + CLINT + PLIC SoC elaboration check.

Runs Verilator in `--lint-only` mode against the full SoC filelist
(`ibex_mini_soc` + real Ibex core + our generated CLINT/PLIC). Purpose:
prove the HDL we emit composes with a real RISC-V core — port widths,
hwif struct field names, bus directions, etc. — without needing a test
program to actually execute (that's Phase 6.2).

The fusesoc-generated .vc files use paths relative to the build dir,
so we `cd` there before invoking Verilator.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


def test_ibex_mini_soc_lints(
    verilator_bin: str,
    ibex_soc_filelist: dict,
) -> None:
    vc_path: Path = ibex_soc_filelist["vc_path"]
    extra_sv: list[Path] = ibex_soc_filelist["extra_sv"]
    build_dir: Path = ibex_soc_filelist["build_dir"]

    cmd = [
        verilator_bin,
        "--lint-only",
        "-Wall",
        "-Wno-UNUSEDSIGNAL",   # Ibex ties a lot of observability ports off
        "-Wno-UNUSEDPARAM",
        "-Wno-PINMISSING",     # we don't connect every tracing port
        "-Wno-WIDTHEXPAND",    # $readmemh vs. sized vectors — benign
        "-Wno-IMPORTSTAR",     # arch-com emits `import Pkg::*;` at $unit
        "-Wno-DECLFILENAME",   # our in-tree Ibex forks keep upstream module names
        # Verilator counts a concurrent assertion's `disable iff (<reset>)` as a
        # *synchronous* read of the reset net, even though no flop is involved.
        # Every ARCH-emitted module carries auto-generated SVA (guard contracts,
        # bounds checks, handshake-stability), so one assertion is enough to have
        # the design's async reset reported as "flopped as both synchronous and
        # async". Reproducible in plain hand-written SV, nothing ARCH-specific:
        #
        #   always_ff @(posedge clk or negedge rst) begin
        #     if (!rst) q <= 1'b0; else q <= a;
        #   end
        #   chk: assert property (@(posedge clk) disable iff (!rst) a |=> a);
        #
        # arch-com wraps each auto-SVA region in `/* verilator lint_off
        # SYNCASYNCNET */` (arch-com#1043), which clears the warning when a module
        # is linted on its own — but Verilator drops a leaf's lint_off once the
        # leaf is inlined into a parent, and then attributes BOTH the "async
        # usage" and the "sync usage" to the parent's top-level port
        # (`ibex_mini_soc.sv:67`, `IO_RST_N`). Both locations collapsing onto the
        # port declaration is the tell that Verilator has lost the real sites;
        # there is no per-site waiver left to apply at SoC level.
        #
        # IO_RST_N is NOT genuinely flopped both ways — see
        # `test_no_sync_async_reset_mix` below, which enforces that directly on
        # the source and is not fooled by `disable iff`. Do not widen this
        # waiver, and do not drop that test.
        "-Wno-SYNCASYNCNET",
        "-Wno-UNOPTFLAT",      # upstream ibex_ex_block.sv has an intended ALU↔multdiv
                               # combinational loop on alu_adder_result_ext (the
                               # multdiv shares the ALU's adder/comparator). With
                               # the FSM-based multdiv Verilator's analysis
                               # resolved it; the thread-based multdiv's nested
                               # `_threads` submodule boundary makes Verilator
                               # more conservative. The loop is functionally
                               # identical and safe in practice.
        "--unroll-count", "72",  # required by prim_secded per Verilator#1266
        "-f", str(vc_path),
        "--top-module", "ibex_mini_soc",
    ]
    cmd.extend(str(p) for p in extra_sv)

    result = subprocess.run(
        cmd, cwd=str(build_dir),
        capture_output=True, text=True,
    )
    # Useful context on failure.
    if result.returncode != 0:
        pytest.fail(
            "verilator --lint-only failed:\n"
            f"CMD:\n  {' '.join(cmd)}\n"
            f"STDERR:\n{result.stderr}\nSTDOUT:\n{result.stdout}"
        )


# ── SYNCASYNCNET's real subject, checked at the source ──────────────────
#
# The Verilator warning above is waived at SoC level because it fires on
# assertion `disable iff` clauses rather than on flops. The condition it is
# actually meant to catch — one reset net driving both a synchronous and an
# asynchronous flop, which glitches on reset release and is a genuine RDC bug —
# still has to be enforced, so we enforce it here.
#
# The check is deliberately dumb and lexical: find every edge-triggered
# `always` block whose sensitivity list has NO reset in it, and fail if the
# block body reads a reset-ish net. That is exactly a synchronous reset. Any
# module in the SoC that also resets asynchronously (all of them do) then makes
# the pair a real mixed-reset net.
#
# Two compiler-side sources of this were live until arch-com#1043: the
# `pipe_reg` cascade (which also had the reset *polarity* inverted, so the
# delay line read as a constant zero) and the `guard`-contract shadow flop.

_ALWAYS_HDR = re.compile(r"always(?:_ff|_latch)?\s*@\s*\(([^)]*)\)")
_RESET_WORD = re.compile(r"\b\w*(?:rst|reset)\w*\b", re.IGNORECASE)
_BLOCK_TOK = re.compile(
    r"\bbegin\b|\bend\b|\bcase\b|\bendcase\b|\bfunction\b|\bendfunction\b"
)


def _first_statement(src: str, pos: int) -> str:
    """Text of the single statement starting at `pos` — a balanced
    `begin`..`end` group, or everything up to the next `;`."""
    begin = src.find("begin", pos)
    semi = src.find(";", pos)
    if begin < 0 or (0 <= semi < begin):
        return src[pos : semi + 1] if semi >= 0 else src[pos : pos + 200]
    depth = 0
    for m in _BLOCK_TOK.finditer(src, begin):
        if m.group(0) in ("begin", "case", "function"):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return src[begin : m.end()]
    return src[begin:]


def _soc_source_files(ibex_soc_filelist: dict) -> list[Path]:
    """Every RTL file Verilator sees for the SoC: the fusesoc-resolved
    tree plus our generated / hand-written additions."""
    vc_path: Path = ibex_soc_filelist["vc_path"]
    build_dir: Path = ibex_soc_filelist["build_dir"]
    files: list[Path] = []
    for line in vc_path.read_text().splitlines():
        s = line.strip()
        if s.endswith((".sv", ".v")) and not s.startswith("-"):
            p = Path(s)
            files.append(p if p.is_absolute() else build_dir / p)
    files.extend(ibex_soc_filelist["extra_sv"])
    return [p for p in files if p.is_file()]


def test_no_sync_async_reset_mix(ibex_soc_filelist: dict) -> None:
    offenders: list[str] = []
    for path in _soc_source_files(ibex_soc_filelist):
        src = path.read_text(errors="replace")
        for m in _ALWAYS_HDR.finditer(src):
            sens = m.group(1)
            if "edge" not in sens:
                continue                      # always @(*) — combinational
            if _RESET_WORD.search(sens):
                continue                      # async: reset is in the sens list
            body = _first_statement(src, m.end())
            reads = sorted(set(_RESET_WORD.findall(body)))
            if reads:
                line = src[: m.start()].count("\n") + 1
                offenders.append(f"{path}:{line} @({sens.strip()}) reads {reads}")

    assert not offenders, (
        "synchronous reset inside an otherwise async-reset SoC "
        "(this is what SYNCASYNCNET is for; the -Wno- waiver in "
        "test_ibex_mini_soc_lints only covers assertion `disable iff` clauses):\n"
        + "\n".join(offenders)
    )
