# IbexCore — test inventory

The basic suite (`tests/cocotb_tests/test_ibex_core_unit.py`,
collected by `tests/test_ibex_core_unit.py`) runs one
`@cocotb.test()` coroutine per spec Requirement (21 tests). Each
test walks the single most representative scenario for that
Requirement. The full regression suite
(`tests/cocotb_tests/test_ibex_core_unit_full.py`, collected by
`tests/test_ibex_core_unit_full.py`) re-runs every basic-suite test,
adds a scenario per remaining Given/When/Then, and covers the
testable Caller-side (CS-N) and Producer-side (PS-N) integration
constraints.

## Basic suite — one test per Requirement

- `req1_reset_and_boot` — Spec §"Requirement 1: Reset and boot".
  After reset release with `boot_addr_i = 32'h0010_0000`, the IF
  stage's first `instr_addr_o` is `32'h0010_0080`.

- `req2_stage_instantiation` — Spec §"Requirement 2: Stage
  instantiation and parameter pinning". Probes WB stage's
  `ready_wb_o = 1` and `rf_write_wb_o = 0` constants under
  WritebackStage=0 (via the `wb_stage_i` hierarchy when exposed,
  otherwise via the absence of an RF write).

- `req3_if_id_handshake` — Spec §"Requirement 3: IF→ID handshake".
  After serving an ADD, IF advances to a new `instr_addr_o` past
  the boot PC, demonstrating ID consumed it via the
  `instr_valid_id_o` / `id_in_ready_o` register pair.

- `req4_id_ex_dispatch_lsu_addr` — Spec §"Requirement 4: ID→EX
  dispatch". An LW with rs1=x5=0x0000_2000 produces
  `data_addr_o = 0x0000_2000` from the EX adder routed
  combinationally into the LSU.

- `req5_imd_val_feedback` — Spec §"Requirement 5: EX→ID multdiv
  intermediate-state feedback". A DIV instruction keeps the core
  busy multi-cycle while no LSU traffic is generated, indirectly
  showing the imd_val_q feedback loop is closed (otherwise multdiv
  would diverge or never complete).

- `req6_branch_redirect` — Spec §"Requirement 6: Branch / jump
  redirect (PC set)". A JAL from boot PC + 8 redirects IF to
  `0x0010_0088`.

- `req7_multdiv_stall` — Spec §"Requirement 7: Multdiv stall". MUL
  in flight keeps `core_busy_o = IbexMuBiOn` and `data_req_o = 0`
  across many cycles.

- `req8_lsu_stall_and_response` — Spec §"Requirement 8: LSU stall
  and response routing". LW emits `data_req_o=1` with
  `data_we_o=0`; after grant + rvalid the WB stage pulses
  `rf_we_wb_o=1` with `rf_waddr_wb_o=6` (rd of the LW).

- `req9_core_busy_reduction` — Spec §"Requirement 9: Core-busy
  reduction". `core_busy_o = IbexMuBiOn` while IF is busy fetching
  the boot instruction.

- `req10_fetch_enable_gating` — Spec §"Requirement 10: Fetch-enable
  gating". Dropping `fetch_enable_i` to `IbexMuBiOff` makes
  `instr_req_o` fall in the same cycle.

- `req11_csr_access_path` — Spec §"Requirement 11: CSR access
  path". A CSRRW(mscratch, x10, x11) produces an RF write to
  rd=x10 via the WB stage, demonstrating the CSR rdata flows
  through `rf_wdata_id` and the op-enable strobe fired.

- `req12_sync_exception_entry` — Spec §"Requirement 12: CSR-driven
  exception entry". An illegal instruction redirects IF to a
  `boot_addr`-prefixed `mtvec`.

- `req13_async_irq_entry` — Spec §"Requirement 13: Asynchronous
  interrupt entry". With mie=0 after reset, asserting
  `irq_external_i=1` does NOT raise `irq_pending_o` (mip & mie
  aggregation per PS-9). Full IRQ-take requires an MIE-programming
  CSRRW sequence and lives in the SoC ISR gate.

- `req14_debug_entry` — Spec §"Requirement 14: Debug entry / WFI /
  dret". Asserting `debug_req_i=1` while running redirects IF away
  from the boot region. WFI and dret retire-paths require
  multi-instruction sequences and live in the SoC ISR gate.

- `req15_writeback_stage_zero` — Spec §"Requirement 15:
  WritebackStage=0". Probes `wb_stage_i.ready_wb_o = 1`,
  `rf_write_wb_o = 0`, `outstanding_load_wb_o = 0`,
  `outstanding_store_wb_o = 0`, `rf_wdata_fwd_wb_o = 0` via the WB
  instance hierarchy.

- `req16_rf_no_ecc_passthrough` — Spec §"Requirement 16: RF
  read/write routing (no ECC)". An LW with rs1=x5=0xCAFE_BABE
  produces `data_addr_o = 0xCAFE_BABE`, demonstrating the no-ECC
  read passthrough.

- `req17_crash_dump_aggregation` — Spec §"Requirement 17:
  Crash-dump aggregation". `crash_dump_o` is read after reset and
  during early operation; the read does not raise (smoke).

- `req18_alert_outputs_zero` — Spec §"Requirement 18: Alert
  outputs". All three alert outputs stay 0 across multiple cycles
  after reset.

- `req19_perf_counter_passthrough` — Spec §"Requirement 19:
  Performance-counter wire pass-through". A BEQ produces a
  `perf_branch` pulse on the ID instance hierarchy when exposed.

- `req20_pmp_tieoffs` — Spec §"Requirement 20: PMP tieoffs". An LW
  produces `data_req_o = 1` (no PMP gate), demonstrating
  `pmp_req_err[PMP_D] = 0`.

- `req21_non_secure_aliases` — Spec §"Requirement 21: Non-secure
  mem-response aliases". An LW response produces a single
  `rf_we_wb_o` pulse via the `rf_we_lsu = lsu_rdata_valid` alias.

## Full suite — extra coverage

The full suite re-imports and re-runs every basic-suite test, then
adds the following:

### Per-Requirement extra Given/When/Then scenarios

- Req 1: `req1_reset_holds_outputs_zero` (Given 1),
  `req1_csr_mtvec_init_strobe` (Given 2 — observable via R12 path).
- Req 2: `req2_rv32m_fast_multdiv_active` (Given 2: RV32MFast).
- Req 3: `req3_instr_valid_clear_drops_register` (Given 2: BEQ
  taken → IF drops valid).
- Req 4: `req4_alu_single_cycle_retire` (Given 1: single-cycle ALU).
- Req 5: `req5_multdiv_no_lsu_traffic` (Given 2: DIV stays in
  MULTI_CYCLE).
- Req 6: `req6_branch_predictor_zero_constants` (Given 2: BP=0
  constants — probes ID hierarchy when exposed).
- Req 7: `req7_no_extra_fetch_during_multdiv` (Given 1: MUL
  prefetch behaviour).
- Req 8: `req8_load_fault_load_err` (Given 3: load fault →
  exception entry), `req8_store_basic_request` (extra: SW path).
- Req 9: `req9_core_busy_off_when_idle` (Given 1: smoke; full WFI
  sleep deferred to SoC ISR gate).
- Req 10: `req10_fetch_enable_high_bits_absorbed` (Given 1: bits
  [3:1] ignored).
- Req 11: `req11_csrrw_writes_rd` (Given 1: CSRRW retire path).
- Req 12: `req12_ecall_redirect` (Given 2: ECALL → mtvec).
- Req 13: `req13_nmi_overrides_mie` (Given 2: NMI ignores
  mstatus.MIE).
- Req 14: `req14_dret_in_decode_mode_illegal` (DRET-outside-debug
  → exception). Full WFI / dret in SoC ISR gate.
- Req 15: `req15_no_loaduse_hazard_bypass` (Given 1: LW response
  advances IF).
- Req 16: `req16_rf_write_passthrough` (Given 2: write port
  passthrough via CSRRW retire).
- Req 17: `req17_crash_dump_combinational` (PS-7: combinational
  read).
- Req 18: `req18_alerts_during_redirect` (alerts stay 0 even
  during exception handling).
- Req 19: `req19_perf_iside_wait_glue` (line 528 glue smoke).
- Req 20: `req20_no_pmp_block_for_instr` (boot fetch lands
  successfully).
- Req 21: `req21_no_response_filter` (no filter; happy-path
  smoke).

### Caller-side rules

- **CS-1** (`boot_addr_i` aligned to 256): `cs1_boot_addr_aligned_first_fetch`
  — testable arm of CS-1 (the actual alignment-violation assertion
  in `ibex_if_stage.sv:831` is sim-only).
- **CS-2** (OBI instr-bus protocol): `cs2_instr_obi_delayed_grant` —
  variable grant latency. Multi-outstanding fetch traffic is
  exercised by the SoC integration tests.
- **CS-3** (OBI data-bus protocol): covered by `req8_*`. Response-
  to-request correspondence under SecureIbex=0 is the SoC's
  obligation; not directly unit-testable.
- **CS-4** (`irq_*_i` sticky): caller-side — not unit-testable. The
  CLINT/PLIC in the SoC ISR gate exercises it.
- **CS-5** (`irq_nm_i` level): covered by `req13_nmi_overrides_mie`.
- **CS-6** (`debug_req_i` level): covered by `req14_debug_entry`.
- **CS-7** (`fetch_enable_i = IbexMuBiOn`): covered by `req10_*` and
  `cs1_*`.
- **CS-8** (External RF combinational read): `cs8_rf_rdata_combinational_into_lsu`
  — rs1 change appears in `data_addr_o` in the same cycle.
- **CS-9** (External RF write rising-edge sample): covered by
  `req8_*` and `req21_*` (`rf_we_wb_o` is a 1-cycle pulse).
- **CS-10** (SoC IRQ-to-mip mapping for fast IRQs): caller-side —
  not unit-testable. The cs_registers (upstream-SV per N-2)
  handles the bit slicing.

### Producer-side rules

- **PS-1** (`instr_req_o = 0` after reset): `ps1_instr_req_zero_after_reset`.
- **PS-2** (`data_req_o = 0` after reset): `ps2_data_req_zero_after_reset`.
- **PS-3** (`instr_addr_o` 4-byte aligned): `ps3_instr_addr_word_aligned`.
- **PS-4** (`core_busy_o` falls only after pipeline drained): not
  unit-testable — requires WFI sleep sequence; SoC ISR gate covers it.
- **PS-5** (`pc_set_o` 1-cycle pulse): `ps5_pc_set_one_cycle_pulse`
  — best-effort hierarchical probe.
- **PS-6** (`instr_valid_clear_o` aligned with `pc_set_o`): covered
  indirectly by `req3_instr_valid_clear_drops_register` and
  `req6_branch_redirect`.
- **PS-7** (`crash_dump_o` combinational): covered by
  `req17_crash_dump_combinational`.
- **PS-8** (`alert_*_o` combinational): covered by
  `req18_alert_outputs_zero` and `req18_alerts_during_redirect`.
- **PS-9** (`irq_pending_o` tracks `mip & mie`):
  `ps9_irq_pending_tracks_mip_mie`.
- **PS-10** (`double_fault_seen_o` quiet under no fault):
  `ps10_double_fault_quiet_under_no_fault`.
- **PS-11** (`branch_target_ex` → IF same cycle): covered by
  `req6_branch_redirect` (no extra register delay between EX target
  and IF fetch address).
- **PS-12** (`imd_val_q_ex` same-cycle from ID to EX): covered by
  `req5_imd_val_feedback` (multdiv would diverge if not).
- **PS-13** (`data_addr_o` tracks `alu_adder_result_ex`
  combinationally): covered by `req4_id_ex_dispatch_lsu_addr` and
  `req16_rf_no_ecc_passthrough`.

### Smoke / regression

- `smoke_back_to_back_adds` — four ADDs back-to-back; advances PC by
  16 with no faults.

## Skipped / not unit-testable

The following Requirements / scenarios are NOT directly testable at
the IbexCore module boundary in isolation. They are covered by the
SoC ISR gate and the cross-module integration tests:

- **Req 13 full IRQ-take**: programming `mstatus.MIE = 1` requires a
  prior CSRRSI instruction. Multi-instruction; SoC ISR gate
  (`tests/cocotb_tests/test_timer_isr.py` etc.) covers it.
- **Req 14 WFI sleep**: requires the controller to walk DECODE →
  WAIT_SLEEP → SLEEP, observable as `core_busy_o = IbexMuBiOff`.
  Multi-instruction; SoC ISR gate covers it.
- **Req 14 dret retire**: requires entering debug mode then issuing
  DRET. Multi-instruction; SoC debug gate covers it.
- **Req 18 alert non-zero arm**: under our pinning, all three alerts
  reduce to 0 (R18 last paragraph). The OR-tree composition is
  structurally testable but no input combination produces a non-zero
  alert. The lint test verifies the structure.
- **CS-3 response-to-request correspondence**: SoC obligation; not
  observable at the IbexCore boundary.
- **CS-4 sticky IRQ lines**: SoC obligation; not observable.
- **CS-10 fast-IRQ bit slicing**: inside the upstream-SV
  `ibex_cs_registers`; not visible at IbexCore module scope.
- **PS-4 core_busy fall after drain**: requires WFI; SoC ISR gate.
- **N-X (spec notes)**: spec notes are not Requirements; no tests
  written for them per the test-design rule "Spec note N-X items
  are not Requirements".

## SV file list assumptions

The runner builds Verilator on the following ARCH-emitted swaps
(in `build/`, link order matters — package first):

```
build/ibex_core_shared_pkg.sv       (package, must link first)
build/ibex_counter.sv               (leaf, used by ID/IF/CSR)
build/ibex_decoder.sv               (sub-instance of id_stage)
build/ibex_controller.sv            (sub-instance of id_stage)
build/ibex_alu.sv                   (sub-instance of ex_block)
build/ibex_multdiv_fast.sv          (sub-instance of ex_block)
build/ibex_fetch_fifo.sv            (sub-instance of prefetch_buffer)
build/ibex_prefetch_buffer.sv       (sub-instance of if_stage)
build/ibex_compressed_decoder.sv    (sub-instance of if_stage)
build/ibex_id_stage.sv
build/ibex_ex_block.sv
build/ibex_load_store_unit.sv
build/ibex_wb_stage.sv
build/ibex_if_stage.sv
build/ibex_core.sv                  (top, the C1 swap)
```

Plus the upstream-SV dependency chain for `ibex_cs_registers`
(kept upstream per N-2):

```
$IBEX_ROOT/rtl/ibex_pkg.sv
$IBEX_ROOT/vendor/lowrisc_ip/ip/prim_generic/rtl/prim_pkg.sv
$IBEX_ROOT/vendor/lowrisc_ip/ip/prim_generic/rtl/prim_buf.sv
$IBEX_ROOT/vendor/lowrisc_ip/ip/prim_generic/rtl/prim_clock_gating.sv
$IBEX_ROOT/rtl/ibex_csr.sv
$IBEX_ROOT/rtl/ibex_cs_registers.sv
```

`IBEX_ROOT` defaults to `~/github/ibex`.

### Open questions / known gaps

1. **`ibex_register_file_ff.sv` is NOT in the file list.** Per the
   spec, the register file lives in `ibex_top` (outside `ibex_core`).
   The IbexCore swap only exposes the RF read/write *port*; the RF
   array itself is supplied by the test harness driving
   `rf_rdata_*_ecc_i` directly. If the implementer ends up
   instantiating an RF inside the swap, this file list will need
   `build/ibex_register_file_ff.sv` added.

2. **`prim_assert.sv`-related `*ASSERT*` macros**: the upstream
   `ibex_cs_registers.sv` uses `` `ASSERT_KNOWN ``,
   `` `ASSERT_INIT ``, etc. These macros are sim-only and the
   `prim_assert.svh` header lives in
   `vendor/lowrisc_ip/ip/prim/rtl/prim_assert.svh`. Verilator may
   either resolve these via `+incdir+` or treat them as no-ops with
   `-DSYNTHESIS`. The current build args do not pass either. If the
   compile fails on undefined `` `ASSERT* `` macros, add
   `+incdir+$IBEX_ROOT/vendor/lowrisc_ip/ip/prim/rtl` and
   `+define+SYNTHESIS` to `build_args`.

3. **`prim_secded_*.sv` for ECC paths**: under our pinning
   (`MemECC=0`, `RegFileECC=0`, `ICache=0`, `ICacheECC=0`), no SECDED
   primitives should be instantiated. If a build error names one,
   that is a sign the pinning didn't propagate fully into a sub-
   module's generate arms — investigate before adding the file.

4. **`ibex_cs_registers` placement (proposal Risks §3)**: whether
   ARCH supports an upstream-SV `inst` *inside* a `pipeline` stage
   or only at module scope is a tooling question for the
   implementer. The test harness simply drives the IbexCore ports;
   it does not depend on the placement. If the implementer's pilot
   places `cs_registers_i` outside the pipeline, no test changes
   are needed.

5. **`ic_*` ICache RAM ports**: under ICache=0 the upstream IF
   stage ties off these output ports. The runner does not
   intentionally drive `ic_tag_rdata_i` / `ic_data_rdata_i`; the
   default `_idle_inputs` only zeros `ic_scr_key_valid_i`. If
   Verilator complains about uninitialised packed-array inputs, add
   explicit zero drives in the cocotb helpers.

6. **`Wno-PINCONNECTEMPTY` and `Wno-DECLFILENAME`**: these are added
   beyond the B5 build args to tolerate the upstream-SV `ibex_csr`
   wrapper's empty-port-tie patterns and the file/module-name
   mismatch the upstream ibex_pkg.sv contains. If lint reports
   surface real bugs they should be re-enabled.

7. **`csr_mvendorid` / `csr_mimpid` parameters**: the spec lists
   these as cs_registers parameters but they have ibex_pkg defaults.
   The runner does not override them, relying on the upstream
   defaults.
