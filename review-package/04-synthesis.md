# 04 — Synthesis and implementation

Collected 2026-09-03. **No synthesis or implementation was run for this
package** (repo owner's instruction: collect existing results only).
Everything below is therefore either (a) a number recorded in a
committed note whose raw reports no longer exist, or (b) a report file
that survives on disk. All of it is **ASIC logic synthesis
(Yosys/ABC, open PDKs), not FPGA, and not post-place-and-route.**

## 0. What the reviewer asked for vs. what exists

| Requested | Status |
|---|---|
| Vivado synthesis + implementation, both lanes, same part and constraints | **Not available.** Vivado is not installed (`which vivado` → none; no `/tools/Xilinx`, no `/Applications/Xilinx`). No `.xdc`, no Vivado project or Tcl, and no `synth_xilinx` script exists in `arch-ibex`, `rdl2arch-riscv`, or `ibex/syn` (`grep -rl 'synth_xilinx\|vivado\|xilinx'` → no hits). |
| Post-P&R LUT / FF / BRAM / DSP / WNS / TNS / fmax per lane | **Not measured** (no FPGA flow has ever been run on this design, on either lane). |
| Yosys `synth_xilinx` estimates | **Not run** (would be a new run). |
| ASIC synthesis area, both lanes | Recorded numbers exist (§1); one upstream-only report survives (§2). |
| ASIC timing | One upstream-only OpenSTA report survives but is not credible (§2.2). No swap-lane timing exists. |
| Power | Recorded OpenSTA estimates with uniform activity exist (§1.3); raw reports gone. |

## 1. Recorded results in the repo (raw reports no longer on disk)

Two committed change notes record sky130 Yosys results for the ARCH
swap against upstream. Both name their scripts and reports under
`/tmp/…`, none of which exist any more (`ls /tmp/ibex-swap-synth
/tmp/ibex-power-compare-struct /tmp/ibex-power-multdiv-gate` → all
missing). The numbers below are quoted verbatim from the notes; they
cannot be re-derived from files in this package.

Flow as described in the notes: Yosys, sky130 `sky130_fd_sc_hd`
(typical corner), `synth -flatten` with a per-module `memory -nomap`
step before flattening (the note documents why:
`changes/2026-05-07-icache-area-restructure/results.md`, "yosys
behaviour discovered"). Upstream lane synthesised through the same
scripts. `IC_NUM_LINES = 256` on both lanes after commit `a43a1b4`.

### 1.1 Area, icache module alone (no RAM macros), sky130

Source: `changes/2026-05-07-icache-area-restructure/results.md:13-18`,
committed 2026-05-08 (`435de8a`).

| Design | Area (µm²) | vs upstream |
|---|---|---|
| upstream `ibex_icache` | 30,170 | — |
| ARCH swap, at start of the area work | 42,355 | +12,185 (+40.4 %) |
| ARCH swap, final (IC_NUM_LINES=256) | **34,771** | **+4,601 (+15.2 %)** |

### 1.2 Area, whole SoC (`ibex_mini_soc`, includes ~1.34 M µm² of identical RAM banks on both lanes), sky130

| Design | Area (µm²) | vs upstream | Source (commit date) |
|---|---|---|---|
| upstream SoC | 1,715,080 | — | both notes |
| ARCH-swap SoC, "hierarchical-memory yosys flow" | 1,743,692 | +28,612 (+1.67 %) | `2026-05-07-icache-area-restructure/results.md:22-25` (2026-05-08) |
| ARCH-swap SoC, "before" multdiv activity gate | 1,812,378 | +97,298 (+5.7 %) | `2026-05-11-multdiv-activity-gate/results.md:19,90-94` (2026-05-11) |
| ARCH-swap SoC, "after" multdiv activity gate | 1,803,009 | +87,929 (+5.1 %) | same |

Discrepancy to note: the two notes, three days apart, give different
swap-SoC areas (1,743,692 vs 1,812,378) against the same upstream
number. The first note calls its flow "hierarchical-memory yosys
flow"; the second says "fresh Yosys sky130 structural full-SoC
netlists". Whether the difference is flow settings or design changes
between 2026-05-08 and 05-11 is not recorded and cannot be checked
without the lost scripts. Do not average them.

### 1.3 Power, whole SoC, OpenSTA with uniform global activity (not simulation-annotated), sky130, 100 MHz

Source: `changes/2026-05-11-multdiv-activity-gate/results.md:66-77`.
The note itself says: "It is not a signoff power result; activity was
OpenSTA uniform global activity, not CoreMark VCD/SAIF annotation."

| Scenario | upstream | ARCH swap before gate | ARCH swap after gate | after / upstream |
|---|---|---|---|---|
| Idle, 5 % activity | 257.3 mW | 288.9 mW | 273.1 mW | 1.061× |
| Active, 30 % activity | 464.2 mW | 625.8 mW | 529.8 mW | 1.141× |
| Peak, 80 % activity | 877.1 mW | 1,299.3 mW | 1,043.3 mW | 1.190× |

### 1.4 What was synthesised (per the notes)

The ARCH lane in those runs is the swap as of 2026-05-08 / 05-11, i.e.
between the last recorded green gate (`dcdbbc8`, 05-13) and the
icache work; the exact `src/` commit is not stated in either note.

## 2. Reports that survive on disk

### 2.1 Upstream `ibex_top`, sky130, lowRISC's own `syn/` flow (2026-05-07)

Location: `~/github/ibex/syn/syn_out/baseline_upstream/` (inside the
upstream checkout, untracked). Produced with lowRISC's experimental
`syn/syn_yosys.sh` flow (sv2v → Yosys 0.64 → ABC → OpenSTA 3.1.0),
with local modifications to the script (copied to
`reports/sv_sky130_syn_yosys.sh.local.diff`) and a local
`syn_setup.sh` pointing at
`~/.volare/sky130A/.../sky130_fd_sc_hd__tt_025C_1v80.lib`
(`reports/sv_sky130_syn_setup.sh`). The flow's own README states it
"does not produce tape-out quality netlists and area/timing numbers it
generates are not representative".

**Configuration of this run is not the arch-ibex configuration.** From
`log/sta.log` "Flow Vars": BranchTargetALU disabled, WritebackStage
disabled, SecureIbex disabled, RV32B = 0 (none), RV32M = 2 (fast),
**RegFile = 2 (latch-based)**; the flow never sets `ICache` or
`PMPEnable`, so both are at upstream default **0**. The arch-ibex port
uses ICache = 1, PMPEnable = 1, RegFile = FF (`01-inventory.md` §1).
This report is therefore not comparable to any ARCH-lane number in §1
and there is no ARCH-lane counterpart to it.

| Metric | Value | Source |
|---|---|---|
| Chip area (`ibex_top`, flattened) | 93,398.33 µm² | `reports/sv_sky130_ibex_top_area.rpt` |
| Cells | 13,294 | same |
| Flip-flops | 710 `dfrtp_1` + 283 `edfxtp_1` + 10 `dfstp_2` = 1,003 | same |
| Latches (register file + clock gate) | 992 `DLH_X1` + 33 `$_DLATCH_N_` — these are un-mapped/foreign cells (a Nangate cell name inside a sky130 run) and carry **no area** in the total | same |
| Clock constraint | 4,000 ps (250 MHz) | `ibex_top_lr_synth_conf.tcl`, `log/sta.log` |

### 2.2 Timing from that run — not usable

`reports/sv_sky130_ibex_top_timing_overall.rpt` reports the worst
register-to-register path with data arrival at **436.45 ns** against a
4 ns clock (slack −473.65 ns, VIOLATED), with single-cell delays of
59.9 ns, 148.5 ns and 203.9 ns on standard cells. `log/sta.log` shows
OpenSTA black-boxing the 992 `DLH_X1` and 33 `$_DLATCH_N_` cells
("module … not found. Creating black box") and rejecting several
endpoints. Those numbers are an artefact of an incomplete STA setup
(missing latch models / no wire-load model), not a property of the
design. **No fmax, WNS, or TNS is derived from this file.**

### 2.3 Pre-port runs (not the ARCH swap; listed so they are not mistaken for it)

| Location | Date | What it is |
|---|---|---|
| `~/github/ibex/syn/syn_out/ibex_hybrid*`, `ibex_21_04_2026_*` (sky130) | 2026-04-21 | `rdl2arch-riscv` "Phase 6.5" SoC: upstream Ibex with the CSR file replaced by a generated one. Predates the first `arch-ibex` commit (2026-04-28). `ibex_top` areas 87,345–89,098 µm². |
| `~/github/rdl2arch-riscv/tests/synth/build/synth.stat` (Nangate45) | 2026-04-27 | Same pre-port hybrid, Nangate45: `ibex_top` 32,895 µm², 18,489 cells. Copied as `reports/prearch_hybrid_nangate45_synth.stat` for provenance only. |

## 3. Files copied to `review-package/reports/`

| File | Lane | Content |
|---|---|---|
| `sv_sky130_ibex_top_area.rpt` | upstream SV | Yosys `stat -liberty` cell/area report (§2.1) |
| ~~`sv_sky130_ibex_top_timing_overall.rpt`, `sv_sky130_ibex_top_timing_reg2reg.rpt`~~ | upstream SV | OpenSTA reports (§2.2, not usable) — **removed in TASK2 before the first commit** (5 MB, no usable number); they remain at `~/github/ibex/syn/syn_out/baseline_upstream/reports/timing/` |
| `sv_sky130_ibex_top.sdc` | upstream SV | The SDC used (drive/load only; clock period comes from the Tcl config) |
| `sv_sky130_syn_setup.sh`, `sv_sky130_syn_yosys.sh.local.diff` | flow | Library path / flow variables, and the local diff against lowRISC's script |
| `prearch_hybrid_nangate45_synth.stat` | neither (pre-port hybrid) | Provenance only |

No `arch_*` synthesis report exists to copy.

## 4. Not measured / not available (explicit)

- FPGA synthesis or implementation of either lane, on any tool.
- Post-P&R area, timing, or utilisation of either lane, on any
  technology (no OpenROAD P&R run exists either; OpenROAD is installed
  but no flow directory or result for this design was found).
- ARCH-lane ASIC synthesis report files (only the quoted numbers in
  §1 survive).
- A like-for-like upstream ASIC synthesis report in the arch-ibex
  configuration (ICache = 1, PMP = 1, RegFile FF).
- Any timing number for either lane.

## 5. Caveats

- All area figures are open-PDK logic-synthesis estimates from a
  flatten-and-map Yosys flow, with no placement, routing, or clock
  tree. They rank designs; they do not predict silicon.
- §1 numbers were produced by scripts that are gone; they are
  reproducible only in principle (the notes describe the flow) and were
  not reproduced for this package.
- The ARCH lane in §1 predates the last recorded green functional gate
  by 2–5 days and the exact source commit is not recorded.
- The one surviving upstream report (§2) is in a different core
  configuration from the port and its timing is invalid.
