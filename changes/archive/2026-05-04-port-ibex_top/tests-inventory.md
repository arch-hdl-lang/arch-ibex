# C2 IbexTop — Test Inventory

Maps every Requirement / CS-N / PS-N rule from
`changes/port-ibex_top/specs/ibex_top/spec.md` to its cocotb tests, and
flags which scenarios are unit-testable at the IbexTop boundary vs.
which fall to the SoC ISR / debug gate.

The basic suite (`tests/cocotb_tests/test_ibex_top_unit.py`) contains
exactly 15 `@cocotb.test`s — one per Requirement, picking the most
representative scenario.

The full suite (`tests/cocotb_tests/test_ibex_top_unit_full.py`)
re-imports every basic test and layers extended scenarios for each
Given/When/Then plus testable CS-N / PS-N rules.

## Requirement coverage

### Requirement 1 — Reset state (`core_busy_q`, `core_sleep_o`)
- **Basic**: `req1_reset_and_core_busy_init`
- **Full extras**:
  - `req1_reset_async_low_takes_effect_immediately` — async-low
    negedge takes effect combinationally (Given 1 of 2)
  - `req1_reset_release_holds_sleep_when_idle` — post-release
    `core_sleep_o = 1` while wake-terms idle (Given 2 of 2)

### Requirement 2 — Sub-module instantiation
- **Basic**: `req2_submodule_instantiation` — probes the four required
  hierarchical handles. Mostly a smoke / structural assertion since
  the structural shape is enforced by Verilator's elaboration (a
  missing `inst` produces an unbound-port elaboration error during
  `runner.build(...)`, surfaced in the collector as a test failure).

### Requirement 3 — Fetch-enable buffering
- **Basic**: `req3_fetch_enable_buffer` — IbexMuBiOn allows fetch,
  IbexMuBiOff gates `instr_req_o` to 0 combinationally
- **Full extras**:
  - `req3_fetch_enable_buffer_all_values` — sweep 4-bit space; LSB
    semantics (every Given)

### Requirement 4 — `clock_en` reduction and `core_sleep_o`
- **Basic**: `req4_clock_en_wake_on_debug` — wake-on-debug Given
- **Full extras**:
  - `req4_clock_en_idle_implies_sleep` (Given 1 of 5)
  - `req4_clock_en_wake_on_irq_nm` (Given 4 of 5)
  - `req4_upper_3_bits_dont_participate` — final clause: bits[3:1]
    of `core_busy_q` MUST NOT participate in `clock_en`
- **Skipped at this scope**:
  - "irq_pending rises in the same cycle as irq_software & MIE" —
    requires CSRs to be pre-programmed (CSRRW MIE bit). Multi-instr;
    covered by SoC ISR gate (`test_sw_isr.py`).
  - "core_busy_q[0] = 1 ⇒ clock_en = 1" — implicit in
    `req5_busy_latches_one_cycle_after_core_busy_o`.

### Requirement 5 — `core_busy_q` flop on ungated `clk_i`
- **Basic**: `req5_core_busy_q_on_ungated_clk` — observe core_sleep_o
  fall while IF is fetching
- **Full extras**:
  - `req5_busy_latches_one_cycle_after_core_busy_o` (Given 2 of 2)
- **Skipped at this scope**:
  - "Gated clock has stopped, wake-up arrives, core_busy_q was
    sampling continuously" (Given 1 of 2) — requires inducing the
    fully-gated state which needs core_busy_q[0] = 0 AND IF fully
    drained, a multi-cycle WFI-equivalent dance. Covered by SoC ISR
    gate (WFI scenarios).

### Requirement 6 — Memory-data integrity collapse under MemECC=0
- **Basic**: `req6_mem_ecc_collapse` — `data_wdata_intg_o = 0`
  regardless of intg input
- **Full extras**:
  - `req6_data_rdata_passthrough` — varying `data_rdata_intg_i` has
    no effect (Given 1 of 2)
  - `req6_data_wdata_passthrough_full_width` — **skipped**: needs an
    SW with controlled rs2 value (multi-instr); covered by SoC ISR
    gate.

### Requirement 7 — ICache RAM port handling under ICache=0
- **Basic**: `req7_icache_ram_tieoffs` — rsp outputs constant 0
  regardless of cfg inputs
- **Full extras**:
  - `req7_ic_rdata_internal_tied_zero` (Given 2 of 2)

### Requirement 8 — Scramble interface tieoffs under ICacheScramble=0
- **Basic**: `req8_scramble_tieoffs` — `scramble_req_o = 0` always
- **Full extras**:
  - `req8_scramble_inputs_absorbed` — input toggling has no effect

### Requirement 9 — Lockstep / shadow-core tieoffs under SecureIbex=0
- **Basic**: `req9_lockstep_tieoffs` — all `*_shadow_o = 0`,
  `lockstep_cmp_en_o = IbexMuBiOff`
- **Full extras**:
  - `req9_lockstep_outputs_dont_mirror_live_bus` — even with bus
    activity the shadow outputs stay 0

### Requirement 10 — Alert OR-trees
- **Basic**: `req10_alert_or_trees` — all three alert outputs = 0
- **Full extras**:
  - `req10_alerts_under_bus_activity` — alerts stay 0 even with
    `instr_err_i = data_err_i = 1` and varied intg

### Requirement 11 — Boot signaling and hart identity
- **Basic**: `req11_boot_addr_passthrough` — boot_addr_i = 0x10_0000
  → first fetch at 0x10_0080
- **Full extras**:
  - `req11_boot_addr_alternate_value` — alternate value
    (0x2000_0000) confirms not constant-folded

### Requirement 12 — Debug interface pass-through
- **Basic**: `req12_debug_passthrough` — debug_req_i wakes the gate;
  `double_fault_seen_o = 0` smoke
- **Full extras**:
  - `req12_double_fault_seen_default_zero` — multi-cycle confirmation
  - `req12_crash_dump_combinational` — X-clean smoke
- **Skipped at this scope**:
  - "Debug-mode entry produces a redirect to DmHaltAddr" — covered by
    C1 (`req14_debug_entry`) and the SoC debug gate; not duplicated
    here.

### Requirement 13 — IRQ pass-through
- **Basic**: `req13_irq_passthrough` — irq_nm_i wake-up
  combinational
- **Full extras**:
  - `req13_irq_software_does_not_wake_when_mie_off` — MIE=0 keeps
    gate closed
  - `req13_irq_fast_15bit_passthrough` — 15-bit packed shape
- **Skipped at this scope**:
  - Multi-instruction IRQ-take sequences (set MIE, take IRQ, see
    mtvec redirect) — covered by SoC ISR gate.

### Requirement 14 — Register-file passthrough
- **Basic**: `req14_regfile_passthrough` — RF read flows
  combinationally to LSU adder (rs1=0 ⇒ data_addr_o = 0 for LW)
- **Full extras**:
  - `req14_rf_write_path_at_gated_clock` — **skipped**: needs LSU
    response loop + later RF read to confirm latching; covered by SoC
    ISR gate.

### Requirement 15 — DFT / test-mode port routing
- **Basic**: `req15_dft_test_en_routing` — test_en_i = 1 keeps clock
  running; scan_rst_ni = 0 has no observable effect
- (CS-3 in full suite covers the inverse: test_en_i = 0 keeps gate
  closed.)

## Caller-side coverage (CS-N)

| Rule  | Test                                | Status |
|-------|-------------------------------------|--------|
| CS-1  | `cs1_single_clock_single_reset`     | Smoke (no IbexTop-side CDC). Covered. |
| CS-2  | `cs2_boot_addr_stable_after_reset`  | Covered (boot_addr stable across reset). |
| CS-3  | `cs3_test_en_zero_keeps_gate_active`| Covered. |
| CS-4  | `cs4_scan_rst_ni_no_effect`         | Covered. |
| CS-5  | `cs5_ram_cfg_inputs_absorbed`       | Covered. |
| CS-6  | `cs6_scramble_inputs_absorbed`      | Covered. |
| CS-7  | `cs7_obi_protocol_inherited`        | **skipped** — protocol-level, covered by C1 unit tests + SoC ISR gate. |
| CS-8  | `cs8_irq_level_obligation`          | **skipped** — SoC CLINT/PLIC's job; pass-through covered by Req 13. |
| CS-9  | `cs9_debug_req_level_obligation`    | **skipped** — SoC debugger's job; pass-through covered by Req 12. |
| CS-10 | `cs10_fetch_enable_ibexmubion_to_run`| Covered. |

## Producer-side coverage (PS-N)

| Rule  | Test                                | Status |
|-------|-------------------------------------|--------|
| PS-1  | `ps1_core_sleep_falls_combinationally`| Covered. |
| PS-2  | `ps2_core_sleep_rises_when_drained` | **skipped** — multi-instr drain; covered by SoC ISR gate (WFI). |
| PS-3  | `ps3_crash_dump_pass_through`       | Smoke covered. |
| PS-4  | `ps4_double_fault_seen_zero_in_normal`| Covered. |
| PS-5  | `ps5_data_wdata_intg_o_zero_every_cycle`| Covered. |
| PS-6  | `ps6_instr_req_addr_passthrough`    | Covered. |
| PS-7  | `ps7_data_req_passthrough`          | Covered. |
| PS-8  | `ps8_lockstep_outputs_zero_every_cycle`| Covered. |
| PS-9  | `ps9_scramble_req_o_zero_every_cycle`| Covered. |
| PS-10 | `ps10_ram_cfg_rsp_zero_every_cycle` | Covered. |
| PS-11 | `ps11_alerts_combinational`         | Covered. |

## SV-file dependency assumptions

The Verilator runner needs the following SV files in this order:

**Upstream SV (parsed first):**
1. `~/github/ibex/rtl/ibex_pkg.sv` — defines `rv32m_e`, `rv32b_e`,
   `regfile_e`, `crash_dump_t`, `ibex_mubi_t`, `IbexMuBiOff/On`, plus
   `IC_NUM_WAYS`, `IC_TAG_SIZE`, `BUS_SIZE`, `SCRAMBLE_KEY_W`,
   `SCRAMBLE_NONCE_W` constants. IbexCore declares
   `parameter ibex_pkg::rv32m_e RV32M = ...` natively, so the package
   must be parsed before any consumer.
2. `~/github/ibex/vendor/lowrisc_ip/ip/prim_generic/rtl/prim_pkg.sv`
   — vendor primitives package.
3. `~/github/ibex/vendor/lowrisc_ip/ip/prim_generic/rtl/prim_buf.sv`
   — IbexTop's `u_fetch_enable_buf` instance + (transitively) used by
   `ibex_csr.sv` for register-output buffering.
4. `~/github/ibex/vendor/lowrisc_ip/ip/prim_generic/rtl/prim_clock_gating.sv`
   — IbexTop's `core_clock_gate_i` instance.
5. `~/github/ibex/rtl/ibex_csr.sv` — used by `ibex_cs_registers.sv`.
6. `~/github/ibex/rtl/ibex_cs_registers.sv` — instantiated inside
   IbexCore.

**ARCH-emitted swaps (parsed second), in dependency order:**
1. `build/ibex_core_shared_pkg.sv` (B5 lesson: shared types package
   first).
2. `build/ibex_counter.sv` — used by `ibex_cs_registers` (transitively
   through HPM counters) AND directly by IbexCore? Actually only by
   `ibex_cs_registers`; kept here for safety.
3. ID stage leaves: `ibex_decoder.sv`, `ibex_controller.sv`.
4. EX block leaves: `ibex_alu.sv`, `ibex_multdiv_fast.sv`.
5. IF stage leaves: `ibex_fetch_fifo.sv`, `ibex_prefetch_buffer.sv`,
   `ibex_compressed_decoder.sv`.
6. Stage modules: `ibex_id_stage.sv`, `ibex_ex_block.sv`,
   `ibex_load_store_unit.sv`, `ibex_wb_stage.sv`, `ibex_if_stage.sv`.
7. **NEW for C2**: `build/ibex_register_file_ff.sv` — A2 leaf,
   instantiated by IbexTop directly (not by IbexCore).
8. `build/ibex_core.sv` — C1 leaf, instantiated by IbexTop.
9. **NEW for C2**: `build/ibex_top.sv` — the C2 swap, top-level.

Plus `-I~/github/ibex/vendor/lowrisc_ip/ip/prim/rtl` for the
`prim_assert.sv` include path (per C1 lesson).

## Open questions

### Q1: N-7 unpacked-Vec port shape for `ic_*_rdata`
Spec note N-7 flags an ambiguity: upstream `ibex_top.sv:229,234`
declares `ic_tag_rdata` and `ic_data_rdata` as SV unpacked arrays
(`logic [W-1:0] x [IC_NUM_WAYS]`), but the auto-emitted
`src/ibex_core.archi` stub declares the corresponding ports as
**packed** `Vec<UInt<W>, N>` without an `unpacked` modifier.

The test files do not encode either choice — they only observe the
boundary effect (the rsp ports tied to 0, R7) and the `gen_norams`
contract. **The implementer MUST inspect `build/ibex_core.sv` after
C1 build to determine whether `ic_tag_rdata_i` / `ic_data_rdata_i`
are emitted packed or unpacked, and match the IbexTop ARCH internal
wires accordingly.**

If the wires are unpacked, IbexTop's ARCH source must use the
`unpacked` Vec modifier on `ic_tag_rdata` and `ic_data_rdata`. Wrong
choice trips a Verilator compile-time port-binding error (port-shape
mismatch at the `inst u_ibex_core` site).

The unit tests will catch this at build-time (the collector's
`runner.build(...)` call will fail) — not at run-time, since both
wires are tied to 0 inside IbexTop and would never be exercised
functionally.

### Q2: `prim_buf` and `prim_clock_gating` `.archi` stub paths
N-4 mandates that IbexTop keep these as upstream-SV instances against
hand-written `.archi` stubs. The tests assume the implementer creates
`prim_buf.archi` and `prim_clock_gating.archi` in `src/` and that
arch-com's `inst` mechanism wires them to the upstream-SV cells. If
the stubs are placed elsewhere or named differently, the
`make build` step will fail before the tests run; the collector will
then `pytest.skip` with "missing build/ibex_top.sv".

### Q3: `ibex_register_file_ff` parameter pass-through
IbexTop passes `WordZeroVal = RegFileDataWidth'(prim_secded_pkg::SecdedInv3932ZeroWord)`
upstream. Per N-3 the implementer MAY pass `WordZeroVal = 0`
literally (functionally equivalent under `RegFileECC=0`). The unit
tests don't exercise the x0 read path explicitly, so either choice
works for these tests. If the implementer wants to match upstream
verbatim, the `prim_secded_pkg.sv` file must be added to
`UPSTREAM_SV_FILES` in both collectors.

### Q4: `prim_ram_1p_pkg` types for `ram_cfg_*` ports
Per N-8 the `ram_cfg_*_i` and `ram_cfg_rsp_*_o` ports are typed as
`prim_ram_1p_pkg::ram_1p_cfg_t` / `ram_1p_cfg_rsp_t`. If arch-com
cannot natively model these as packed structs, the implementer may
need to:
- Add `prim_ram_1p_pkg.sv` to `UPSTREAM_SV_FILES`, OR
- Stub the typedef locally (the cfg ports are sunk under `ICache=0`,
  so a typedef alias of `logic [W-1:0]` suffices).

The tests drive these as integers (`ram_cfg_icache_tag_i = 0xFF`)
which works for either representation — the only requirement is that
the ARCH-emitted port shape matches Verilator's view of upstream's
type.

### Q5: `crash_dump_o` packed-struct width at the boundary
Per N-26 it is a 5 × `logic [31:0]` packed struct (160 bits). The
unit tests only smoke-check it (read it without expecting a
particular value); if Verilator emits it as a flat 160-bit vector
the `int(dut.crash_dump_o.value)` reads will succeed unchanged.

### Q6: Hierarchical handle availability
The basic suite's `req2_submodule_instantiation` test attempts to
read four hierarchical handles (`u_ibex_core`, `register_file_i`,
`core_clock_gate_i`, `u_fetch_enable_buf`). With
`--public-flat-rw` Verilator exposes most signals but instance
handles can be subtle. The test catches AttributeError gracefully —
the structural shape is more reliably enforced at elaboration time
(a missing `inst` produces a port-binding error at `runner.build`
time, surfaced as a collector failure).

## Build-failure as a unit test

Several Requirements (R2 sub-module set, N-7 port-shape match) are
"unit-tested" by the fact that `runner.build(...)` succeeds. If the
ARCH source omits any required `inst`, gets a port shape wrong, or
mismatches a parameter, Verilator elaboration fails before any cocotb
test runs and the collector reports the failure. This is the same
pattern C1 used.
