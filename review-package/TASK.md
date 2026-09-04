# Task: build a reviewer evidence package for the arch-ibex study

You are working in a private repo that ports the lowRISC Ibex RISC-V core
(hand-written SystemVerilog) to the Arch HDL. The goal of this task is to
collect evidence for a journal reviewer who asked for a comparison of Arch
against hand-written SystemVerilog on the same modules, covering:
development effort, compiler diagnostics, generated RTL quality, and
post-place-and-route FPGA area and timing.

## Ground rules
- Do NOT modify any Arch source, SV source, or flow scripts. This is a
  read-and-measure task. If a script must be changed to run, stop and ask.
- Do NOT push, and do NOT commit unless I ask. Work only on the current
  branch `review-package`.
- Write all outputs under `review-package/`. Nothing else.
- Every number in the summary must come from a file or command you ran;
  cite the source path or command next to it. If something cannot be
  measured, write "not measured" — do not estimate.
- Ask before running anything longer than ~10 minutes (Vivado
  implementation, full regression).

## Step 1 — Inventory (write review-package/01-inventory.md)
1. Which Ibex configuration is ported (RV32I/M/C? branch predictor?
   multiplier variant? PMP? ICache?). Cite the config file or parameters.
2. Which Ibex modules have Arch equivalents, and which are reused as-is
   from upstream SV (e.g., regfile primitives, prim_* cells). Produce a
   two-column table: upstream SV file -> Arch file (or "reused").
3. The upstream Ibex commit/tag the SV reference corresponds to
   (from a submodule, a vendored copy, or a README note).
4. The Arch compiler version used (arch --version and any pin file).

## Step 2 — Functional evidence (write review-package/02-functional.md)
1. Find every test/DV entry point in the repo (Makefiles, scripts, CI).
   List them.
2. State which of these have been run on the Arch-generated SV and what
   the last recorded result was, citing log files. Distinguish:
   - the simple core testbench / example programs,
   - riscv-tests or riscv-arch-test compliance,
   - riscv-dv random instruction streams,
   - any co-simulation against Spike or against the upstream SV.
3. If a fast regression exists (< 10 min), run it now on both the Arch
   lane and the upstream SV lane and record pass/fail counts and wall time.
   If only a long regression exists, do not run it — describe it and stop.

## Step 3 — Source and diagnostics metrics (write review-package/03-source-metrics.md)
1. LOC, three ways, for the ported module set only (not reused primitives):
   - upstream Ibex SV (hand-written),
   - Arch source,
   - Arch-generated SV.
   Use `cloc` if installed, else `wc -l` with blank/comment lines reported
   separately. State the tool and the exact file list.
2. Compile-time diagnostics: run `arch check` (and `arch build` + lint if
   the flow does) on the Arch sources and record every warning/error class
   emitted, with counts. Then run Verilator lint (`verilator --lint-only
   -Wall`) on (a) upstream Ibex SV and (b) Arch-generated SV and record
   warning classes and counts. Present as one table.
3. Development-effort proxies from git history of the port: number of
   commits touching Arch files, first and last commit dates, and the
   count of `arch check` failures recorded in any local learning store
   (`~/.arch/learn/events.jsonl`) that reference this repo, if present.
   Report what exists; do not infer hours.

## Step 4 — Synthesis and implementation (write review-package/04-synthesis.md)
Find the synthesis/implementation flow already in the repo. Then:
1. If Vivado is available and a project/script exists:
   run synthesis AND implementation (place & route) for BOTH the upstream
   Ibex SV and the Arch-generated SV with identical constraints and the
   same part. Ask me before launching. Save:
   - report_utilization (post-implementation) for both,
   - report_timing_summary (post-implementation) for both,
   - the constraint file(s) and part number used.
   Record LUTs, FFs, BRAM, DSP, WNS/TNS, and achieved fmax per lane.
2. If only Yosys is available: run `synth_xilinx` for both lanes and
   label the results clearly as SYNTHESIS ESTIMATES, NOT post-P&R.
3. Copy every report you used into review-package/reports/ with
   lane-prefixed filenames (sv_*, arch_*).

## Step 5 — Summary (write review-package/00-summary.md)
A one-page summary with:
- one table per metric family (functional, LOC, diagnostics, P&R),
- an explicit "Not measured / not available" list,
- an explicit "Caveats" list (e.g., differing config, reused primitives,
  estimate vs post-P&R),
- the exact commands you ran, in order.
Do not editorialize about whether Arch is better; report numbers.

## Step 6 — Sanitize
List every file under review-package/ and flag anything that contains
Arch source code, proprietary flow scripts, or absolute paths with my
username. I will decide what to redact.
