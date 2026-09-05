# 13 — Lint delta (TASK2 Phase 3)

Re-run 2026-09-04 on the Phase 2 generated SV (branch `review-package`
at the Phase 2 commit; compiler pin `fa4c864f` = v0.71.0 + 2 patches;
Verilator 5.048). Same method as `03-source-metrics.md` §2b(ii): core
only, top = `ibex_top`, identical fusesoc filelist and `-G` parameter
values on both lanes (ICache=1, PMPEnable=1, PMPNumRegions=4,
DbgTriggerEn=1, DbgHwBreakNum=1, everything else 0), `-Wall -Wno-fatal`,
no `-Wno-*` waivers; the Arch lane replaces the 18 upstream files with
the 23 generated ones. "With waivers" applies the upstream `.vlt`
lint-waiver files that ship in the Ibex tree (their path patterns match
upstream files only); "no waivers" removes them from both lanes.

Logs (overwriting the first-pass files of the same name; the first-pass
numbers stay recorded in `03-source-metrics.md`):
`reports/lint_sv_lane_ibex_top.log`, `reports/lint_arch_lane_ibex_top.log`,
`reports/lint_sv_lane_ibex_top_nowaiver.log`,
`reports/lint_arch_lane_ibex_top_nowaiver.log`; per-warning
classification: `reports/lint_arch_lane_classification.txt`.

## 1. Counts

| Warning class | SV lane, waivers | Arch lane, waivers | SV lane, no waivers | Arch lane, no waivers | Arch lane, waivers, first pass (03-source-metrics) |
|---|---|---|---|---|---|
| `UNUSEDPARAM` | 0 | 73 | 251 | 360 | 74 |
| `UNUSEDSIGNAL` | 0 | 50 | 0 | 50 | 61 |
| `PINCONNECTEMPTY` | 0 | 0 | 85 | 61 | 0 |
| `UNOPTFLAT` | 3 | 0 | 3 | 0 | 0 |
| `DECLFILENAME` | 0 | 6 | 0 | 6 | 6 |
| `IMPORTSTAR` | 0 | 4 | 0 | 4 | 4 |
| `WIDTHEXPAND` | 0 | 2 | 0 | 2 | 3 |
| `PROCASSINIT` | 0 | 2 | 0 | 2 | 2 |
| `SYNCASYNCNET` | 0 | 0 | 0 | 1 | 1 (no-waiver) |
| **Total** | **3** | **137** | **339** | **486** | 150 |
| Errors | 0 | 0 | 0 | 0 | 0 |

Change since the first pass (Phase 2 source changes): −11 `UNUSEDSIGNAL`
(the icache's unused `bus_ready_*`/`wb_ready_*` wires are gone; +1 for
the arbiter's now-internal `request_ready`), −1 `UNUSEDPARAM`, −1
`WIDTHEXPAND` (`inval_ctrl.sv` state compare; codegen difference between
the 2026-05-14 compiler and the pin, not a source change).

## 2. Classification of the Arch-lane-only warning classes (with waivers)

Every warning present on the Arch lane and absent on the SV lane was put
in one of the three TASK2 bins. Per-warning detail with file and line is
in `reports/lint_arch_lane_classification.txt`.

| Bin | Count | Classes | What it is |
|---|---|---|---|
| **(i) single-configuration hard-coding** | **80** | `UNUSEDPARAM` 64, `UNUSEDSIGNAL` 16 | Parameters the port declares to keep upstream's parameter surface but never reads because the configuration is fixed (`MemECC` 5, `WritebackStage` 4, `ResetAll` 4, `RV32M` 4, `RV32E` 4, `RV32B` 4, `DummyInstructions` 4, `BranchPredictor` 4, `BranchTargetALU` 3, `PCIncrCheck`, `ICacheECC`, `DataIndTiming` 2 each, 19 singletons); and input ports of disabled features that are wired but unread (`branch_not_set_i`, `instr_bp_taken_i`, `instr_exec_i`, `mem_resp_intg_err_i`, `stall_wb_i`, `bt_a_mux_sel`, `bt_b_mux_sel`, `mult_sel_i`, …, plus `clk_i`/`rst_ni` on the purely combinational `ibex_decoder` and `ibex_wb_stage` — upstream has the same unused clocks and waives them in its `.vlt`). |
| **(ii) compiler-emitted pattern** | **17** | `DECLFILENAME` 6, `IMPORTSTAR` 4, `PROCASSINIT` 2, `WIDTHEXPAND` 2, `UNUSEDSIGNAL` 3, (`SYNCASYNCNET` 1, no-waiver run only) | See §3; each has the exact generated-SV pattern recorded for filing. |
| **(iii) other / design-level** | **40** | `UNUSEDPARAM` 9, `UNUSEDSIGNAL` 31 | Unused bit-slices of address / operand signals (`fb_addr_wb_sel[2:0]`, `if_instr_addr[31:2,0]`, `raw_fb_addr[31:2,0]`, `alu_adder_ext_i[33,0]`, `shift_out_ext[32]`, `instr_rdata_alu_i[24:15,11:7]`, …), per-FB alias lets the icache no longer reads (`fb*_alloc_flag`, `fb*_err`, `fb_empty`, `fb_wants_out`, `lookup_throttle`, `lookup_branch_ic1_q`), the multdiv thread's `port reg` outputs that are only written (`op_numerator_q`, `op_quotient_q`, `div_by_zero_q`), and 9 local parameters of the icache/output stage. Upstream hand-written SV avoids the equivalent warnings with its explicit `logic unused_* = …` sink idiom; the port has no such idiom. Candidates for source clean-up; none changes the generated logic. |

The SV lane's 3 `UNOPTFLAT` (upstream `ibex_ex_block` ALU↔multdiv adder
sharing, `ibex_id_stage`, `ibex_controller`) do not appear on the Arch
lane: the same intended combinational loop is present (the compiler
reports it as "1 comb SCC, suppressed by pragma") but Verilator's
analysis does not flag it across the thread-helper module boundary.

## 3. Compiler-emitted patterns (bin ii) — exact generated-SV shape, for filing against arch-com

Not fixed in the generated SV, as instructed.

| Class | Count | Generated pattern | Where | Status |
|---|---|---|---|---|
| `PROCASSINIT` | 2 | `thread` lowering declares the state register and any loop counter with an initializer **and** assigns them procedurally: `logic [3:0] _t0_state = 0;` / `logic [4:0] _t0_loop_cnt_0 = 0;` then `_t0_state <= …` inside `always_ff @(posedge clk_i or negedge rst_ni)`. Minimal reproducer: a 10-line `thread` with one `wait until` and one `do … until` (`<scratch>/smoke/thread_procassinit.arch`) → 1 `PROCASSINIT` on v0.70.6, v0.71.0 and main `f4569890`. | `build/ibex_multdiv_fast.sv:102,104` | **filed: [arch-com#995](https://github.com/arch-hdl-lang/arch-com/issues/995)** |
| `SYNCASYNCNET` (no-waiver run; at SoC level it surfaces on `IO_RST_N`) | 1 | For every register declared `guard <valid>` / `reset none` the compiler emits a `_<reg>_written` tracking flop in `always_ff @(posedge clk_i)` with a **synchronous** `if (!rst_ni) … <= 1'b0;` while the design's other flops reset `rst_ni` asynchronously (`always_ff @(posedge clk_i or negedge rst_ni)`), so `rst_ni` is "flopped as both synchronous and async". 12 such blocks in `build/ibex_icache.sv` and `build/ibex_icache_output_stage.sv` (e.g. `_bus_hold_fb_q_written`, `_ic1_hold_line_q_written`). | `build/ibex_top.sv:130` (`rst_ni` port) | recorded; to file (RDC instrumentation should use the same reset style as the design, or be gated behind a sim-only `ifdef`) |
| `DECLFILENAME` | 6 | Construct name ≠ file basename: CamelCase `FbAgeArb`, `InvalCtrl`, `RamPortArb`, `IbexIcacheOutputStage`, package `IbexCoreSharedPkg` emitted into the snake_case files chosen by `scripts/build.sh`; and the compiler's own `_ibex_multdiv_fast_threads` helper module co-emitted into `ibex_multdiv_fast.sv`. | `build/{fb_age_arb,inval_ctrl,ram_port_arb,ibex_icache_output_stage,ibex_core_shared_pkg,ibex_multdiv_fast}.sv` | recorded; repo-side naming for five of them (`build.sh` could emit CamelCase files), compiler-side for the `_threads` helper |
| `IMPORTSTAR` | 4 | `import IbexCoreSharedPkg::*;` emitted at `$unit` scope (before the `module` keyword) instead of inside the module header. | `build/{ibex_controller,ibex_core,ibex_id_stage,ibex_if_stage}.sv` | recorded; to file (emit the import inside the module) |
| `WIDTHEXPAND` | 2 | A 1-bit ARCH parameter `param RV32E[0:0]: const = 1'd0` is emitted as `parameter int RV32E = 1'h0` (32-bit `int` with a 1-bit literal). | `build/ibex_register_file_ff.sv:27,29` | recorded; to file (emit `parameter logic RV32E = 1'h0` or size the literal) |
| `UNUSEDSIGNAL` | 3 | `request_ready` (the arbiter's internal ready one-hot after the `valid_only` fix of PR #994 — expected, nothing reads it), `last_grant_r` (arbiter state register emitted for every policy, unused by `policy <custom fn>`), `_t0_cnt` (thread cycle counter emitted but unused by this thread). | `build/fb_age_arb.sv`, `build/ibex_multdiv_fast.sv` | recorded; to file (suppress unused helpers or mark them `/* verilator lint_off UNUSED */`) |

Related compiler issues filed in this task for completeness:
[arch-com#996](https://github.com/arch-hdl-lang/arch-com/issues/996)
(`arch sim --pybind` reference-member binding; the two `test_archsim_units`
gate failures) and
[arch-com#997](https://github.com/arch-hdl-lang/arch-com/issues/997)
(`pipe_reg` tap reads rejected by the operand-latency check; the
`IbexIcache.arch:551` rewrite in Phase 1).

## 4. Commands

```
# filelists derived from the harness's fusesoc output (snapshot in <scratch>/lint-verilator-snapshot):
#   upstream_core.vc          = fusesoc .vc minus --top-module/--exe/-G lines
#   arch_core_p2.vc           = upstream_core.vc minus the 18 ported files, plus build/*.sv (package first)
#   *_nowaiver.vc             = same minus every .vlt line
cd <scratch>/lint-verilator-snapshot
verilator --lint-only -Wall -Wno-fatal --unroll-count 72 --top-module ibex_top \
  -GICache=1 -GPMPEnable=1 -GPMPNumRegions=4 -GDbgTriggerEn=1 -GDbgHwBreakNum=1 -GRV32E=0 \
  -GBranchTargetALU=0 -GWritebackStage=0 -GBranchPredictor=0 -GSecureIbex=0 -GICacheECC=0 -GICacheScramble=0 \
  -f <list>.vc > reports/lint_<lane>_ibex_top[_nowaiver].log
python3 (classification script, output = reports/lint_arch_lane_classification.txt)
```
