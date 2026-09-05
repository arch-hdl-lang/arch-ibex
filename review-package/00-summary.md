# 00 — Summary: ARCH port of Ibex vs. hand-written SystemVerilog

Evidence package for Reviewer 1, comment 2. **This file is the single
source of truth as of 2026-09-04**; it supersedes the 2026-09-03 first
pass (whose numbers are listed at the end under "Superseded"). Every
number is traceable to a file under `reports/` or a command named in
the numbered files (`01`–`04` first pass, `10`–`15` this pass); those
files carry the caveats in full. Numbers are reported as measured; no
judgement about which lane is "better" is made here.

**Design under comparison.** lowRISC Ibex (`eede2fb`, 2026-04-10)
configured RV32IMC, `RV32MFast`, 2-stage pipeline (no writeback stage),
instruction cache on (2 ways × 256 lines), PMP on (4 regions), FF
register file, no branch predictor, no security features, RVFI off. 18
Ibex RTL modules were ported to ARCH (23 ARCH files including 4 icache
helper constructs and one shared package); `ibex_pkg`, `ibex_csr`, the
`prim_*` cells and the simulation wrappers are reused from upstream;
`ibex_cs_registers` is a hand-written SV fork. Both lanes run inside
the same hand-written test SoC for simulation and are synthesised as
`ibex_top` with identical parameter overrides, constraints and tools.

**Source state.** Branch `review-package` on top of `8c4b3ca`
(2026-06-29): the port sources carry the Phase 1–2 changes of
`11-port-changes.md` (one compiler-compatibility rewrite; the icache
arbiter handshake fix and its follow-ups), and the unit tests changed
with them. No other design source was touched.

**Toolchain (`10-toolchain.md`).** ARCH compiler: arch-com release
`v0.72.0` (2026-09-05), which contains PR #993 and PR #994; the
measurements were run on the equivalent local merge `89ec0522` (main
`f4569890` + those two PRs) and v0.72.0 regenerates byte-identical SV
for all 23 files. Verilator 5.048
(assertions **on** everywhere in this pass), cocotb 2.0.1, Yosys
0.67+post, sv2v 0.0.13, OpenSTA 3.1.0, OpenROAD 26Q2, nextpnr-ecp5
`8dbcee5` + prjtrellis 1.4, riscv64-elf-gcc 15.2.0. No Vivado.

## Functional (assertions on, final pin) — `12-icache-handshake.md` §8

| Suite | Result | Lane | Report |
|---|---|---|---|
| Per-module unit suites (34 collectors, cocotb) | all pass | Arch | `reports/gate_make_test.junit.xml` |
| 10 CPU programs (ISRs, PMP faults, icache bench), end-to-end | 10 / 10 | Arch (SV lane: 10 / 10, `02-functional.md`) | same; `reports/functional_sv_lane.junit.xml` |
| RISC-V arch tests rv32i_m I/M/C, signatures vs upstream-generated references | 74 / 74 bit-identical | Arch vs SV | `reports/gate_arch_tests.junit.xml` |
| CoreMark (one run, both lanes in one test) | Arch 112,855 ticks vs SV 111,651 (ratio 1.0108; 8.861 vs 8.956 CoreMark/MHz) | both | `reports/gate_coremark.log` |
| `make test` overall (249 items) | 162 passed / 12 failed / 75 skipped | Arch | `reports/gate_make_test.log` |
| `make lint` (SoC, `-Wall`, project waivers) | FAIL, 3 warnings (2 × `PROCASSINIT` compiler pattern, 1 × `SYNCASYNCNET` reset-tracking flops); SV lane fails on the same `SYNCASYNCNET` | both | `reports/gate_make_lint.log` |

The 12 `make test` failures are all toolchain/repo drift, none in a
design suite: the SoC lint above (1), `arch sim --pybind` wrapper
compile error on the current compiler (6 modules, arch-com#996), HARC
0.2.0 rejecting the checked-in runner's `--codegen` flag (4), and a test
reading plan files that were never committed (1). Every design suite is
green with the generated protocol checkers enabled — the state the first
pass could only reach with `--no-assert`.

**What was fixed to get there.** The first pass found every Arch-lane
simulation stopping at 140 ns on a compiler-generated valid/ready
assertion in the icache's fill-buffer arbiter. Diagnosis
(`12-icache-handshake.md` §1–6): the port drove a level-sensitive
request mask into a channel declared `valid_ready`, and, unlike upstream
(`ibex_icache.sv:763-774`), did not hold a presented request until
grant. Fix: the arbiter lanes are now `valid_only` (needing an arch-com
fix, PR #994), the icache holds a presented request until `instr_gnt_i`
(R-EXT-2), stale-but-allocating lines complete their fill (R-FB-6), plus
three consequential fixes the full gate surfaced (stale FB never an
output candidate; bus-pick FB never released early; lookups never
coalesce onto a stale FB). Eleven source hunks in two files; two new
unit tests; five re-stimulated (`11-port-changes.md`, Phase 2 table).

## Lines of code (ported module set only) — `03-source-metrics.md`, recounted

| Lane | Files | Total | Blank | Comment | Code | Report |
|---|---|---|---|---|---|---|
| Upstream Ibex SV | 18 | 13,816 | 1,885 | 2,506 | **9,425** | `reports/loc_upstream.txt` |
| ARCH source, all 23 files (after Phase 1–2) | 23 | 10,374 | 882 | 3,139 | **6,353** | `reports/loc_arch_phase2.txt` |
| ARCH source, the 18 direct ports only | 18 | 9,740 | 819 | 3,016 | **5,905** | same (helpers excluded) |
| ARCH-generated SV, all 23 (final pin) | 23 | 10,460 | 109 | 3,399 | **6,952** | `reports/loc_generated_pin.txt` |
| ARCH-generated SV, 18 direct ports only | 18 | 9,671 | 82 | 3,264 | **6,325** | same |

Phase 1–2 changed the ARCH code line count by +10 (6,343 → 6,353;
`IbexIcache.arch` 676 → 686, `FbAgeArb.arch` unchanged at 34). Counter:
20-line Python (`cloc` not installed). Caveat: the upstream files are
parametric over every Ibex configuration and carry SVA; the port
hard-codes one configuration.

## Compile-time diagnostics — `13-lint.md`

| Check | Upstream SV | Arch lane | Report |
|---|---|---|---|
| `arch check`, final pin, 23 files | n/a | 23 / 23 pass, 1 warning (suppressed comb SCC) | `reports/arch_check_pinned.log` |
| Verilator `-Wall`, `ibex_top`, with upstream `.vlt` waivers | 3 (`UNOPTFLAT`) | **141** (`UNUSEDPARAM` 73, `UNUSEDSIGNAL` 54, `DECLFILENAME` 6, `IMPORTSTAR` 4, `WIDTHEXPAND` 2, `PROCASSINIT` 2) | `reports/lint_sv_lane_ibex_top.log`, `reports/lint_arch_lane_ibex_top.log` |
| Verilator `-Wall`, no waivers on either lane | 339 | 490 | `reports/lint_*_nowaiver.log` |
| Verilator errors | 0 | 0 | same |

Arch-lane-only warnings, classified (`13-lint.md` §2, per-warning list in
`reports/lint_arch_lane_classification.txt`): **(i) single-configuration
hard-coding 80** (declared-but-unread parameters and disabled-feature
inputs), **(ii) compiler-emitted patterns 21** (thread state init
`PROCASSINIT`, filed as arch-com#995; `$unit`-scope `import`;
CamelCase-vs-filename; 1-bit `int` parameters; unused arbiter/thread
helpers; sync-reset RDC tracking flops), **(iii) other 40** (unused
bit-slices and aliases upstream would sink with its `unused_*` idiom).
None is an error; none changes generated logic.

## sky130 (open PDK, `sky130_fd_sc_hd` tt 25 °C 1.80 V), `ibex_top`, both lanes identical flow — `14-sky130.md`

### Logic synthesis (Yosys, flattened; §4.3)

| Metric | SV lane | Arch lane | Arch / SV | Report |
|---|---|---|---|---|
| Cell area (µm²) | 1,736,611 | 1,896,047 | **1.092×** | `reports/{sv,arch}_sky130_synth_area.rpt` |
| Cells | 102,079 | 126,389 | 1.238× | same |
| Flip-flops (all) / of which RAM-array enable flops | 46,719 / 44,784 | 47,650 / 45,590 | +931 / +806 | same |
| Area excluding the RAM-array flops (≈ control + datapath) | ≈ 0.40 M µm² | ≈ 0.53 M µm² | ≈ 1.3× | derived from same |
| Unmapped / black-boxed cells | 0 | 0 | | `flow/out/*/sky130/sta.log` |
| Synthesis-netlist STA (no buffering) | WNS −805 ns | WNS −26,490 ns | **not usable** (unbuffered 11k-fanout RAM enables) | `reports/*_sky130_sta_wns_tns.rpt` |

### Post-place-and-route (OpenROAD regression flow, 10 ns clock, 25 % die utilisation rule; §4.4)

| Metric | SV lane | Arch lane | Arch / SV | Report |
|---|---|---|---|---|
| Design area after P&R (µm², fillers excluded) | 2,277,607 | 2,600,940 | **1.142×** | `reports/{sv,arch}_openroad_final_area.rpt` |
| Die / final utilisation | 2,656 µm square / 32.8 % | 2,774 µm square / 34.3 % | | `reports/*_openroad_final_metrics.txt` |
| Setup WNS / TNS at 10 ns (extracted parasitics) | −9.660 ns / −197,688 ns | −17.987 ns / −932,797 ns | | `reports/*_openroad_final_timing.rpt` |
| **fmax = 1 / (10 ns − WNS)** | **50.9 MHz** | **35.7 MHz** | **0.70×** | derived |
| Hold WNS (input-port paths, 2 ns input delay) | −0.237 ns | −1.737 ns | | same |
| DRC / antenna violations | 0 / 3 | 0 / 0 | | `reports/*_openroad_final_checks.rpt` |
| Power, default activity (W) | 0.442 | 0.426 | 0.96× | `reports/*_openroad_final_power.rpt` |
| Global-route wirelength (µm) | 12.97 M | 16.87 M | 1.30× | `flow/out/*/openroad/openroad.log` |

Critical path on both lanes: register-to-register into the icache RAM
arrays' enable flops through the buffered 11 k-fanout enable nets; the
Arch lane's version adds an adder carry chain in front of it
(`14-sky130.md` §4.4).

## ECP5 FPGA (LFE5U-85F, speed 6, Yosys `synth_ecp5` + nextpnr-ecp5, 50 MHz constraint, 3 seeds) — `15-ecp5.md`

| Metric | SV lane | Arch lane | Arch / SV | Report |
|---|---|---|---|---|
| LUT4 after packing (logic + carry) | 11,055 | 16,867 | 1.53× | `reports/{sv,arch}_ecp5_nextpnr_seed1.log` |
| Flip-flops | 2,534 | 3,430 | 1.35× | same |
| Block RAM (DP16KD) / multiplier (MULT18X18D) | 6 / 1 | 6 / 1 | identical mapping | `reports/{sv,arch}_ecp5_synth.stat` |
| fmax, mean of seeds 1–3 [min–max] (MHz) | 33.56 [33.13–34.36] | 29.14 [28.60–30.06] | 0.87× | `reports/{sv,arch}_ecp5_report_seed{1,2,3}.json` |
| Meets 50 MHz | no | no | | same |
| Critical path (both lanes) | tag-bank block RAM read → tag compare / IF data path → ID-stage instruction register | | | `reports/*_ecp5_nextpnr_seed1.log` |

Substitutions applied identically to both lanes: the generic clock
gate is a pass-through (`clk_o = clk_i`; no fabric clock-gate cell),
and the core is placed out-of-context (787 / 2,000 top-level IO bits
exceed any ECP5 package; no IO buffers, no bitstream). Details
`15-ecp5.md` §5.3.

## Development-effort proxies (git; no hours inferred) — `01-inventory.md`

| Proxy | Value |
|---|---|
| Port history at `8c4b3ca` | 205 commits, 2026-04-28 → 2026-06-29 |
| Commits touching `src/*.arch` | 92, 2026-04-29 → 2026-06-24 |
| Commits by area | src 93, tests 67, changes 32, specs 21, scripts 8, soc 3 |
| Most-revised ARCH file | `IbexIcache.arch`, 35 commits |
| This pass (branch `review-package`) | 8 commits, 2026-09-03 → 09-05: 2 source files changed (Phase 1–2 hunks), 2 test files, 17 files under `flow/` added, 2 arch-com PRs + 3 issues |
| Learning-store `arch check` failure records for this repo | 0 — the store only starts 2026-06-24, after the port was written |

## Not measured / not available

- Xilinx (Vivado / `synth_xilinx`) results, either lane (out of scope).
- Simulation-annotated power; the post-P&R power figures are OpenSTA's
  default-activity estimates.
- A per-module attribution of the Arch lane's extra flops and LUTs.
- Post-P&R at any other die size / utilisation, or with ORFS itself.
- riscv-dv / Spike co-simulation (not present in the repo).
- ECP5 with real clock gating or with IO buffers (design cannot fit any
  ECP5 package's IO count).

## Caveats

1. **Compiler pin.** The repo pins no compiler. The port compiles and
   links on arch-com `v0.72.0` and later (which carry #993 stub
   mangling and #994 arbiter `valid_only` lowering); release v0.71.0
   and earlier do not, and v0.71.0 also emits SV that sv2v/Yosys
   reject. Rebuild recipe in `10-toolchain.md`.
2. **Design fix in this pass.** The functional numbers are for the
   Phase 2 icache, which now holds bus requests until grant and
   completes allocating fills like upstream. The pre-fix design fails
   every assertions-on simulation (`02-functional.md`).
3. **Configuration breadth.** Upstream SV is fully parametric; the port
   is single-configuration. LOC and unused-parameter counts reflect that.
4. **RVFI ports.** The ported top exposes its 38 RVFI outputs
   (1,213 bits) unconditionally, tied to constants; upstream hides them
   behind `ifdef RVFI`. Out-of-context on ECP5 they vanish; on sky130
   they add top-level pins and tie cells to the Arch lane.
5. **Sky130 P&R** uses OpenROAD's regression flow, not ORFS, and a
   25 % utilisation die (a 50 % die failed detailed placement under the
   flow's placement padding). Numbers depend on that die and the
   default sky130hd knobs; both lanes share them exactly.
6. **Reused and forked pieces.** `ibex_pkg`, `ibex_csr`, `prim_*`,
   tracer, and the CSR-file fork are identical on both lanes.
7. **Waivers.** "With waivers" applies lowRISC's path-matched `.vlt`
   files, which by construction match the upstream files and not the
   generated ones; the "no waivers" row is the symmetric comparison.

## Superseded (first pass, 2026-09-03; kept for traceability)

| First-pass number | Status |
|---|---|
| Arch lane 0 / 10 CPU programs as-is, 10 / 10 with `--no-assert` (`02-functional.md`) | superseded by 10 / 10 with assertions on, after the Phase 2 fix |
| Compiler `arch 0.70.0 @ 2ffcc60b` as the working compiler | superseded by the final pin (`10-toolchain.md`) |
| Arch-lane Verilator `-Wall` 150 / 499 warnings (`03-source-metrics.md`) | superseded by 141 / 490 (`13-lint.md`; Phase 2 removed the arbiter ready wires and a `WIDTHEXPAND`) |
| ARCH LOC 6,343 code lines | superseded by 6,353 (Phase 1–2 edits) |
| May-2026 sky130 numbers from committed notes (+1.7 % / +5.1 % SoC, +15.2 % icache module, 1.14× power) (`04-synthesis.md`) | superseded by the reproducible `ibex_top` flow in `14-sky130.md`; not directly comparable (different scope, Yosys version, and icache) |
| "FPGA: not measured", "post-P&R: not measured" | superseded by `15-ecp5.md` and `14-sky130.md` §4.4 |

## Commands run, in order (this pass)

Paths: `<scratch>` is a session temp directory outside the repo;
`ARCH_BIN` is the pinned compiler; pytest is the anaconda one
(`/opt/homebrew/anaconda3/bin/pytest`, the Python with cocotb).

```
# Phase 0-1: pin and compile (10-toolchain.md, 11-port-changes.md)
git -C ~/github/arch-com worktree add --detach <scratch>/arch-com-pin-main f4569890; git merge a814dc62 7844c021; cargo build --release   # ≡ v0.72.0 (byte-identical SV)
git clean -fXq -- src/ build/; ARCH_BIN=<scratch>/arch-com-pin-main/target/release/arch make build      # 23/23
for f in src/*.arch; do $ARCH_BIN check $f; done                                                          # reports/arch_check_pinned.log
# Phase 2: gate with assertions on (12-icache-handshake.md §8)
make lint; make test (pytest tests/ -n auto --dist=loadfile); pytest tests/test_arch_tests.py; RUN_COREMARK_COMPARE=1 pytest tests/test_coremark_compare.py
# Phase 3: lint delta (13-lint.md)
verilator --lint-only -Wall -Wno-fatal --unroll-count 72 --top-module ibex_top -G<12 params> -f <lane>[_nowaiver].vc
# Phase 4: sky130 (14-sky130.md)
python3 flow/make_filelists.py <fusesoc .vc>; ./flow/sv2v.sh; ./flow/sky130_synth.sh sv arch; ./flow/openroad/run.sh sv & ./flow/openroad/run.sh arch
# Phase 5: ECP5 (15-ecp5.md)
./flow/ecp5_pnr.sh synth; ./flow/ecp5_pnr.sh pnr
# Phase 6: LOC recount, sanitize
python3 <scratch>/loc.py src/*.arch > reports/loc_arch_phase2.txt; python3 <scratch>/loc.py build/*.sv > reports/loc_generated_pin.txt
sed -i '' 's|<worktree>|${REPO_ROOT}|g; s|/Users/<user>|~|g; …' reports/*   # see 06-sanitize.md
```
