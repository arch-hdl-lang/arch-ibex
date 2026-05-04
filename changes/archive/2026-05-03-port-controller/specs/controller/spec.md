# IbexController — port contract + behavior

## Purpose

`ibex_controller` is the main pipeline FSM of the Ibex core. It sequences
the processor through reset → boot fetch → first fetch → decode/execute,
and arbitrates every asynchronous disruption to that loop: external
interrupts, debug requests, exceptions, WFI sleep, CSR-induced pipeline
flushes, MRET/DRET returns. It owns the `pc_set_o` / `pc_mux_o` /
`exc_pc_mux_o` outputs that redirect the IF stage, the
`csr_save_*_o` / `csr_restore_*_o` / `csr_save_cause_o` / `exc_cause_o` /
`csr_mtval_o` outputs that drive CSR side-effects on exception/IRQ
entry and mret/dret return, the `flush_id_o` / `instr_valid_clear_o` /
`id_in_ready_o` / `controller_run_o` outputs that gate the ID stage,
and the mode flags `debug_mode_o` / `nmi_mode_o`.

## Pinned parameter values

This spec is restricted to the SoC's parameter pinning. All
out-of-scope branches are absent from the requirements below.

| Parameter         | Pinned value | Effect on this spec                                                                                  |
|-------------------|--------------|------------------------------------------------------------------------------------------------------|
| `WritebackStage`  | `0`          | `g_no_wb_exceptions` priority encoder only; `wb_exception_o` is constant `0`; `g_no_writeback_mepc_save` (`csr_save_id_o = 0` in FLUSH except where set by FSM); `id_wb_pending = instr_valid_i` (since `ready_wb_i = 1`). |
| `BranchPredictor` | `0`          | `instr_bp_taken_i = 0`, `branch_not_set_i = 0`; `nt_branch_mispredict_o` is constant `0`; the `pc_set_o = BranchPredictor ? ~instr_bp_taken_i : 1'b1` ternary collapses to `1` on every taken branch/jump. |
| `MemECC`          | `0`          | `g_no_intg_irq_int` branch only: `irq_nm_int = 0`, `irq_nm_int_cause = 0`, `irq_nm_int_mtval = 0`. NMI is only ever external (`irq_nm_ext_i`).                                              |

## Port contract

### Inputs

| Port                       | Type / width        | Role                                                                                       |
|----------------------------|---------------------|--------------------------------------------------------------------------------------------|
| `clk_i`                    | Clock               | Rising-edge clock for all flops (see Spec notes for the lone simulation-only `negedge`).   |
| `rst_ni`                   | Reset (active-low)  | Async-asserted, sync-deasserted reset of all flops to their RESET values.                   |
| `illegal_insn_i`           | `Bool`              | Decoder reports current ID instruction is illegal (only ever asserted with `instr_valid_i = 1`). |
| `ecall_insn_i`             | `Bool`              | Decoder reports current ID instruction is `ECALL`.                                         |
| `mret_insn_i`              | `Bool`              | Decoder reports current ID instruction is `MRET`.                                          |
| `dret_insn_i`              | `Bool`              | Decoder reports current ID instruction is `DRET`.                                          |
| `wfi_insn_i`               | `Bool`              | Decoder reports current ID instruction is `WFI`.                                           |
| `ebrk_insn_i`              | `Bool`              | Decoder reports current ID instruction is `EBREAK`.                                        |
| `csr_pipe_flush_i`         | `Bool`              | CSR write requires a pipeline flush.                                                       |
| `instr_valid_i`            | `Bool`              | The ID stage holds a valid instruction this cycle.                                         |
| `instr_i`                  | `UInt<32>`          | Uncompressed instruction word (for `mtval` on illegal-insn).                               |
| `instr_compressed_i`       | `UInt<16>`          | Compressed instruction word (for `mtval` on illegal-insn when compressed).                 |
| `instr_is_compressed_i`    | `Bool`              | Current ID instruction is 16-bit compressed.                                               |
| `instr_bp_taken_i`         | `Bool`              | Pinned `0` (BranchPredictor=0).                                                            |
| `instr_fetch_err_i`        | `Bool`              | IF stage flagged a fetch error for the current ID instruction.                             |
| `instr_fetch_err_plus2_i`  | `Bool`              | Fetch-error landed on the upper 16 bits of a 32-bit instruction (mtval = pc+2).            |
| `pc_id_i`                  | `UInt<32>`          | PC of current ID instruction.                                                              |
| `instr_exec_i`             | `Bool`              | Top-level execution-enable; when `0`, ID must stop accepting from IF.                       |
| `lsu_addr_last_i`          | `UInt<32>`          | Last LSU address (latched into `mtval` on LSU exceptions).                                 |
| `load_err_i`               | `Bool`              | LSU load access fault (1-cycle pulse, latched into `load_err_q`).                          |
| `store_err_i`              | `Bool`              | LSU store access fault (1-cycle pulse, latched into `store_err_q`).                        |
| `mem_resp_intg_err_i`      | `Bool`              | Tied off / unused under `MemECC=0`.                                                        |
| `branch_set_i`             | `Bool`              | ID/EX has resolved a taken branch.                                                         |
| `branch_not_set_i`         | `Bool`              | Pinned `0` (BranchPredictor=0).                                                            |
| `jump_set_i`               | `Bool`              | ID/EX has resolved a taken jump (`JAL`/`JALR`).                                            |
| `csr_mstatus_mie_i`        | `Bool`              | M-mode global IRQ enable (`mstatus.MIE`).                                                  |
| `irq_pending_i`            | `Bool`              | Any non-NMI IRQ in `mip & mie` is asserted.                                                |
| `irqs_i`                   | `Irqs`              | Per-IRQ enable-qualified pending bits: `{irq_software, irq_timer, irq_external, irq_fast[14:0]}`. |
| `irq_nm_ext_i`             | `Bool`              | External non-maskable interrupt request.                                                   |
| `debug_req_i`              | `Bool`              | External debug-mode entry request.                                                         |
| `debug_single_step_i`      | `Bool`              | `dcsr.step` — single-step mode.                                                            |
| `debug_ebreakm_i`          | `Bool`              | `dcsr.ebreakm` — `EBREAK` in M-mode enters debug.                                          |
| `debug_ebreaku_i`          | `Bool`              | `dcsr.ebreaku` — `EBREAK` in U-mode enters debug.                                          |
| `trigger_match_i`          | `Bool`              | Hardware trigger (breakpoint) match.                                                       |
| `priv_mode_i`              | `PrivLvl`           | Current privilege level (`PRIV_LVL_M` / `PRIV_LVL_U`).                                     |
| `stall_id_i`               | `Bool`              | ID-stage stall (multicycle instruction not done).                                          |
| `stall_wb_i`               | `Bool`              | Pinned `0` under `WritebackStage=0`.                                                       |
| `ready_wb_i`               | `Bool`              | Pinned `1` under `WritebackStage=0`.                                                       |

### Outputs

| Port                       | Type / width        | Role                                                                                          |
|----------------------------|---------------------|-----------------------------------------------------------------------------------------------|
| `ctrl_busy_o`              | `Bool`              | Core is busy — used by top-level clock-gate. `0` only in `WAIT_SLEEP` and idle `SLEEP`.        |
| `instr_valid_clear_o`      | `Bool`              | Tells ID-stage to clear its `instr_valid` flop next cycle.                                   |
| `id_in_ready_o`            | `Bool`              | ID stage will accept a new instruction from IF this cycle.                                   |
| `controller_run_o`         | `Bool`              | Controller is in normal-run (DECODE) mode; only set in DECODE state.                          |
| `instr_req_o`              | `Bool`              | Tell IF/prefetch to fetch instructions. `0` in RESET / WAIT_SLEEP / SLEEP.                   |
| `pc_set_o`                 | `Bool`              | Strobe to redirect IF PC to `pc_mux_o`.                                                      |
| `pc_mux_o`                 | `PcSel`             | `PC_BOOT`/`PC_JUMP`/`PC_EXC`/`PC_ERET`/`PC_DRET`/`PC_BP`. (PC_BP unused under BranchPredictor=0.) |
| `nt_branch_mispredict_o`   | `Bool`              | Constant `0` (BranchPredictor=0).                                                            |
| `exc_pc_mux_o`             | `ExcPcSel`          | `EXC_PC_EXC`/`EXC_PC_IRQ`/`EXC_PC_DBD`/`EXC_PC_DBG_EXC`. Selects which mtvec/dpc target IF jumps to. |
| `exc_cause_o`              | `ExcCause`          | Struct `{irq_ext, irq_int, lower_cause[4:0]}` written to `mcause` on exception/IRQ entry.    |
| `wb_exception_o`           | `Bool`              | Constant `0` under `WritebackStage=0`.                                                       |
| `id_exception_o`           | `Bool`              | `exc_req_d & ~wb_exception_o`. Combinational: ID-stage instruction is taking an exception this cycle. |
| `nmi_mode_o`               | `Bool`              | Equals `nmi_mode_q` — core is executing the NMI handler.                                     |
| `debug_cause_o`            | `DbgCause`          | Equals `debug_cause_q`; latched flavor of `debug_cause_d`.                                    |
| `debug_csr_save_o`         | `Bool`              | Strobe to CSR: save dpc/dcsr (asserted in DBG_TAKEN_IF and DBG_TAKEN_ID-with-update only).   |
| `debug_mode_o`             | `Bool`              | Equals `debug_mode_q`.                                                                       |
| `debug_mode_entering_o`    | `Bool`              | Pulse on the cycle the FSM is in DBG_TAKEN_IF / DBG_TAKEN_ID and writes `debug_mode_d = 1`. |
| `csr_save_if_o`            | `Bool`              | Strobe: save IF-stage PC into mepc/dpc.                                                      |
| `csr_save_id_o`            | `Bool`              | Strobe: save ID-stage PC into mepc/dpc.                                                      |
| `csr_save_wb_o`            | `Bool`              | Constant `0` under `WritebackStage=0`.                                                       |
| `csr_restore_mret_id_o`    | `Bool`              | Strobe to CSR: restore mstatus from MRET (FLUSH state with `mret_insn`).                     |
| `csr_restore_dret_id_o`    | `Bool`              | Strobe to CSR: restore mstatus from DRET (FLUSH state with `dret_insn`).                     |
| `csr_save_cause_o`         | `Bool`              | Strobe: latch `exc_cause_o` into mcause/dcause and the matching mepc/dpc.                    |
| `csr_mtval_o`              | `UInt<32>`          | mtval value to latch when `csr_save_cause_o` is asserted on a fault.                         |
| `flush_id_o`               | `Bool`              | Pulse to ID stage: drop the in-flight instruction (asserted in FLUSH, WAIT_SLEEP, SLEEP, DBG_TAKEN_*). |
| `perf_jump_o`              | `Bool`              | DECODE state, `jump_set_i` asserted: count a taken jump.                                     |
| `perf_tbranch_o`           | `Bool`              | DECODE state, `branch_set_i` asserted: count a taken branch.                                 |

## Requirements

### Requirement 1: Reset → Boot → First-fetch startup sequence

The controller MUST execute a deterministic 3-state startup sequence on
reset deassertion: `RESET → BOOT_SET → FIRST_FETCH → DECODE`.

- In `RESET`: `instr_req_o = 0`, `pc_mux_o = PC_BOOT`, `pc_set_o = 1`,
  `ctrl_fsm_ns = BOOT_SET`. (No fetch yet; the PC mux is being primed.)
- In `BOOT_SET`: `instr_req_o = 1`, `pc_mux_o = PC_BOOT`, `pc_set_o = 1`,
  `ctrl_fsm_ns = FIRST_FETCH`. (First fetch issued, PC redirected to boot
  address.)
- In `FIRST_FETCH`: `instr_req_o = 1`, all CSR-save outputs `0`,
  `pc_set_o = 0` by default. `ctrl_fsm_ns = DECODE` iff `id_in_ready_o`.
  If `handle_irq` is asserted, transition to `IRQ_TAKEN` instead with
  `halt_if = 1`. If `enter_debug_mode` is asserted, transition to
  `DBG_TAKEN_IF` instead with `halt_if = 1`.
- During this entire sequence `ctrl_busy_o = 1`.

#### Scenario: Cold reset
- GIVEN `rst_ni` deasserts at cycle 0.
- WHEN cycle 0 (RESET): `instr_req_o = 0`, `pc_mux_o = PC_BOOT`, `pc_set_o = 1`.
- WHEN cycle 1 (BOOT_SET): `instr_req_o = 1`, `pc_mux_o = PC_BOOT`, `pc_set_o = 1`.
- WHEN cycle 2 (FIRST_FETCH): `instr_req_o = 1`, `pc_set_o = 0`.
- THEN, once the IF stage delivers a valid instruction so that
  `id_in_ready_o = 1`, the next cycle is `DECODE`.
- (ref: ibex_controller.sv:495–559, 874–895)

#### Scenario: Debug request before first instruction
- GIVEN the FSM is in `FIRST_FETCH` and `debug_req_i = 1`.
- WHEN the cycle ends, `enter_debug_mode = 1` (since `debug_mode_q = 0`).
- THEN `ctrl_fsm_ns = DBG_TAKEN_IF`, `halt_if = 1` this cycle.
- (ref: ibex_controller.sv:552–558)

---

### Requirement 2: DECODE-state behavior and special-request gating

In `DECODE` the controller MUST present the normal-run output profile
and arbitrate the four classes of next-state transitions in priority
order: pending exception/CSR-flush > debug entry > IRQ entry > stay in
DECODE.

`controller_run_o = 1` MUST hold in `DECODE` and only in `DECODE`.

`pc_mux_o = PC_JUMP` MUST hold throughout `DECODE` (the value is only
sampled when `pc_set_o` is asserted).

When `branch_set_i || jump_set_i`:
- `pc_set_o` MUST be `1` (BranchPredictor=0 collapses the ternary).
- `perf_tbranch_o = branch_set_i`, `perf_jump_o = jump_set_i`.

When `special_req` is asserted:
- `retain_id` MUST be `1` (so `id_in_ready_o = 0`, `instr_valid_clear_o = 0`,
  the ID instruction is held).
- Since `ready_wb_i = 1` (pinned), the next-state MUST be `FLUSH`.

When `(enter_debug_mode | handle_irq) & (stall | id_wb_pending)`:
- `halt_if` MUST be `1`.

When `!stall & !special_req & !id_wb_pending`:
- If `enter_debug_mode`: next-state `DBG_TAKEN_IF`, `halt_if = 1`.
- Else if `handle_irq`: next-state `IRQ_TAKEN`, `halt_if = 1`.
- Else: stay in DECODE.

The defining helpers are:

- `special_req_flush_only = wfi_insn | csr_pipe_flush`
- `special_req_pc_change = mret_insn | dret_insn | exc_req_d | exc_req_lsu`
- `special_req = special_req_pc_change | special_req_flush_only`
- `exc_req_lsu = store_err_i | load_err_i`
- `id_wb_pending = instr_valid_i | ~ready_wb_i` ⇒ under pin, `id_wb_pending = instr_valid_i`.

Where each `*_insn` is the decoder-output ANDed with `instr_valid_i`
(see Requirement 9), and `exc_req_d` is defined in Requirement 9.

#### Scenario: Plain ALU instruction
- GIVEN DECODE, `instr_valid_i = 1`, no decoder flags, no IRQ/debug.
- WHEN `stall = 0`, `branch_set_i = 0`, `jump_set_i = 0`.
- THEN `pc_set_o = 0`, `controller_run_o = 1`, `instr_valid_clear_o = 1`,
  `id_in_ready_o = 1`, next-state `DECODE`.
- (ref: ibex_controller.sv:561–635, 864, 871)

#### Scenario: Taken branch
- GIVEN DECODE, `branch_set_i = 1`.
- THEN `pc_set_o = 1`, `pc_mux_o = PC_JUMP`, `perf_tbranch_o = 1`.
- (ref: ibex_controller.sv:594–600)

#### Scenario: Special-request transition to FLUSH
- GIVEN DECODE, `instr_valid_i = 1`, `mret_insn_i = 1`.
- THEN `mret_insn = 1` → `special_req_pc_change = 1` → `special_req = 1`.
- `retain_id = 1`, `ctrl_fsm_ns = FLUSH` (since `ready_wb_i = 1`).
- `id_in_ready_o = 0`, `instr_valid_clear_o = 0` (ID instruction held).
- (ref: ibex_controller.sv:577–592)

---

### Requirement 3: IRQ priority and entry sequence

When `handle_irq = ~debug_mode_q & ~debug_single_step_i & ~nmi_mode_q & (irq_nm | (irq_pending_i & irq_enabled))`
and the FSM is in DECODE (with no special_req / debug entry / stall /
id_wb_pending) or in FIRST_FETCH, the controller MUST transition to
`IRQ_TAKEN` and from `IRQ_TAKEN` perform an IRQ-entry side-effect, then
transition back to DECODE.

In `IRQ_TAKEN` (always one cycle, unconditional next-state DECODE):
- `pc_mux_o = PC_EXC`, `exc_pc_mux_o = EXC_PC_IRQ`.
- If `handle_irq` still holds:
  - `pc_set_o = 1`, `csr_save_if_o = 1`, `csr_save_cause_o = 1`.
  - `exc_cause_o` MUST be selected by the priority ladder:
    1. `irq_nm & !nmi_mode_q` (NMI; under `MemECC=0`, only external):
       `exc_cause_o = ExcCauseIrqNm` (i.e. `{irq_ext=1, irq_int=0,
       lower_cause=5'd31}`); `nmi_mode_d = 1`. (`csr_mtval_o` stays 0
       since `irq_nm_int = 0`.)
    2. Else if `irqs_i.irq_fast != 0`:
       `exc_cause_o = {irq_ext=1, irq_int=0, lower_cause={1'b1, mfip_id}}`
       where `mfip_id` is the highest-set fast-IRQ index (Requirement 11).
    3. Else if `irqs_i.irq_external`: `exc_cause_o = ExcCauseIrqExternalM`.
    4. Else if `irqs_i.irq_software`: `exc_cause_o = ExcCauseIrqSoftwareM`.
    5. Else (`irqs_i.irq_timer`): `exc_cause_o = ExcCauseIrqTimerM`.
- `irq_enabled = csr_mstatus_mie_i | (priv_mode_i == PRIV_LVL_U)`.
- `irq_nm = irq_nm_ext_i` (under `MemECC=0`).
- IRQs MUST be ignored while in debug mode, NMI mode, or single-step
  mode.

#### Scenario: NMI taken from DECODE
- GIVEN DECODE, `irq_nm_ext_i = 1`, `nmi_mode_q = 0`, `debug_mode_q = 0`,
  `debug_single_step_i = 0`, `instr_valid_i = 0`, `stall = 0`.
- WHEN cycle N: `handle_irq = 1`, `id_wb_pending = 0`, `enter_debug_mode = 0`,
  next-state IRQ_TAKEN, `halt_if = 1`.
- WHEN cycle N+1 (IRQ_TAKEN): `pc_set_o = 1`, `pc_mux_o = PC_EXC`,
  `exc_pc_mux_o = EXC_PC_IRQ`, `exc_cause_o = ExcCauseIrqNm`,
  `csr_save_if_o = 1`, `csr_save_cause_o = 1`, `nmi_mode_d = 1`,
  next-state DECODE.
- WHEN cycle N+2 (DECODE): `nmi_mode_q = 1` (NMI handler now running).
- (ref: ibex_controller.sv:637–674)

#### Scenario: Fast IRQ priority (8 and 12 simultaneous)
- GIVEN `irqs_i.irq_fast[8] = 1` and `irqs_i.irq_fast[12] = 1`,
  no NMI, in DECODE → IRQ_TAKEN.
- THEN `mfip_id = 4'd12` (highest index wins; Requirement 11).
- `exc_cause_o = {irq_ext=1, irq_int=0, lower_cause={1'b1, 4'd12}}`
  = `5'b1_1100` = lower_cause `5'd28`.
- (ref: ibex_controller.sv:417–425, 658–663)

#### Scenario: IRQ ignored in debug mode
- GIVEN `debug_mode_q = 1`, any external IRQ pending.
- THEN `handle_irq = 0`; FSM does NOT transition to IRQ_TAKEN.
- (ref: ibex_controller.sv:413–414)

---

### Requirement 4: Debug entry

The controller MUST recognize debug-mode entry from three priority
sources and route them through one of two states:

- `DBG_TAKEN_IF`: entered for external `debug_req_i` or single-step
  (`do_single_step_d = ~debug_mode_q & debug_single_step_i & instr_valid_i`,
  held until handled), or trigger match (`trigger_match_i & ~debug_mode_q`),
  whenever the FSM observes a clean dispatch boundary (DECODE with no
  stall/special_req/id_wb_pending, or FIRST_FETCH, or FLUSH with
  `enter_debug_mode_prio_q` and not an EBREAK-into-debug).
- `DBG_TAKEN_ID`: entered for `EBREAK` that should enter debug mode
  (i.e. `ebrk_insn_prio` priority-encoded in FLUSH **and**
  (`debug_mode_q | ebreak_into_debug`)). This path comes via FLUSH,
  not directly from DECODE.

Helpers:
- `enter_debug_mode_prio_d = (debug_req_i | do_single_step_d) & ~debug_mode_q`
- `enter_debug_mode = enter_debug_mode_prio_d | (trigger_match_i & ~debug_mode_q)`
- `ebreak_into_debug = (priv_mode_i == PRIV_LVL_M) ? debug_ebreakm_i :
   (priv_mode_i == PRIV_LVL_U) ? debug_ebreaku_i : 1'b0`

In `DBG_TAKEN_IF`:
- `pc_mux_o = PC_EXC`, `exc_pc_mux_o = EXC_PC_DBD`, `pc_set_o = 1`.
- `flush_id = 1`, `csr_save_if_o = 1`, `debug_csr_save_o = 1`,
  `csr_save_cause_o = 1`.
- `debug_mode_d = 1`, `debug_mode_entering_o = 1`.
- `ctrl_fsm_ns = DECODE`.

In `DBG_TAKEN_ID`:
- `pc_mux_o = PC_EXC`, `exc_pc_mux_o = EXC_PC_DBD`, `pc_set_o = 1`,
  `flush_id = 1`.
- If `ebreak_into_debug && !debug_mode_q` (forced-entry on EBREAK from
  outside debug mode): `csr_save_cause_o = 1`, `csr_save_id_o = 1`,
  `debug_csr_save_o = 1`. Otherwise (re-entering debug from inside
  debug): no CSR save.
- `debug_mode_d = 1`, `debug_mode_entering_o = 1`.
- `ctrl_fsm_ns = DECODE`.

If FLUSH is reached with `enter_debug_mode_prio_q = 1` AND it is NOT an
`ebrk_insn_prio && ebreak_into_debug` case, the FSM MUST go to
`DBG_TAKEN_IF` regardless of whatever exception/return path the FLUSH
body computed.

#### Scenario: External debug_req on idle DECODE
- GIVEN DECODE, `debug_req_i = 1`, `debug_mode_q = 0`, no stall, no
  pending instr, no special_req, no IRQ.
- THEN `enter_debug_mode = 1`, next-state DBG_TAKEN_IF, `halt_if = 1`.
- WHEN next cycle (DBG_TAKEN_IF): `pc_set_o = 1`, `pc_mux_o = PC_EXC`,
  `exc_pc_mux_o = EXC_PC_DBD`, `csr_save_if_o = 1`,
  `csr_save_cause_o = 1`, `debug_csr_save_o = 1`, `flush_id = 1`,
  `debug_mode_d = 1`, `debug_mode_entering_o = 1`.
- (ref: ibex_controller.sv:617–622, 676–695)

#### Scenario: EBREAK (M-mode, dcsr.ebreakm=1) goes via FLUSH then DBG_TAKEN_ID
- GIVEN DECODE, `instr_valid_i = 1`, `ebrk_insn_i = 1`,
  `priv_mode_i = PRIV_LVL_M`, `debug_ebreakm_i = 1`, `debug_mode_q = 0`.
- THEN cycle N: `ebrk_insn = 1` → `exc_req_d = 1` → `special_req = 1`,
  `retain_id = 1`, next-state FLUSH.
- WHEN cycle N+1 (FLUSH): `exc_req_q = 1`, `ebrk_insn_prio = 1`,
  `ebreak_into_debug = 1`. The EBREAK clause inside FLUSH overrides
  the default exception path: `pc_set_o = 0`, `csr_save_id_o = 0`,
  `csr_save_cause_o = 0`, `flush_id = 0`, `ctrl_fsm_ns = DBG_TAKEN_ID`.
- WHEN cycle N+2 (DBG_TAKEN_ID): `pc_set_o = 1`, `flush_id = 1`,
  `csr_save_cause_o = 1`, `csr_save_id_o = 1`, `debug_csr_save_o = 1`,
  `debug_mode_d = 1`.
- (ref: ibex_controller.sv:697–726, 770–785)

#### Scenario: debug_req_i during FLUSH for an ECALL
- GIVEN FLUSH, `exc_req_q = 1`, `ecall_insn_prio = 1`,
  `enter_debug_mode_prio_q = 1` (debug_req_i was high last cycle).
- THEN the FLUSH clause sets `csr_save_cause_o`/`exc_cause_o` for ECALL
  AND the trailing override at end of FLUSH sets `ctrl_fsm_ns =
  DBG_TAKEN_IF` (since the prio is not EBREAK-into-debug). The CSRs
  get the ECALL state but we then enter debug.
- (ref: ibex_controller.sv:822–831)

---

### Requirement 5: Exception handling in FLUSH

FLUSH MUST always assert `halt_if = 1` and `flush_id = 1` and default
to next-state `DECODE`. Within FLUSH, the action depends on which
class of trigger took us here:

(a) **Exception/fault** (`exc_req_q | store_err_q | load_err_q`):

- `pc_set_o = 1`, `pc_mux_o = PC_EXC`,
  `exc_pc_mux_o = debug_mode_q ? EXC_PC_DBG_EXC : EXC_PC_EXC`.
- `csr_save_id_o = 0` (under `WritebackStage=0`), `csr_save_cause_o = 1`.
- `exc_cause_o` and `csr_mtval_o` MUST be set by the priority encoder
  (`unique case (1'b1)` over `*_prio`):

  1. `instr_fetch_err_prio` → `exc_cause_o = ExcCauseInstrAccessFault`,
     `csr_mtval_o = instr_fetch_err_plus2_i ? (pc_id_i + 32'd2) : pc_id_i`.
  2. `illegal_insn_prio` → `exc_cause_o = ExcCauseIllegalInsn`,
     `csr_mtval_o = instr_is_compressed_i ? {16'b0, instr_compressed_i} : instr_i`.
  3. `ecall_insn_prio` → `exc_cause_o = (priv_mode_i == PRIV_LVL_M) ?
     ExcCauseEcallMMode : ExcCauseEcallUMode`.
  4. `ebrk_insn_prio` →
     - If `debug_mode_q | ebreak_into_debug`: redirect to `DBG_TAKEN_ID`
       (Requirement 4) — `pc_set_o = 0`, `csr_save_id_o = 0`,
       `csr_save_cause_o = 0`, `flush_id = 0`.
     - Else: `exc_cause_o = ExcCauseBreakpoint`.
  5. `store_err_prio` → `exc_cause_o = ExcCauseStoreAccessFault`,
     `csr_mtval_o = lsu_addr_last_i`.
  6. `load_err_prio` → `exc_cause_o = ExcCauseLoadAccessFault`,
     `csr_mtval_o = lsu_addr_last_i`.

  The priority encoder under `WritebackStage=0` is:
  `instr_fetch_err > illegal_insn > ecall > ebrk > store_err > load_err`.

- Exactly one `*_prio` SHALL be `1` whenever
  `(ctrl_fsm_cs == FLUSH) & exc_req_q` (`IbexExceptionPrioOnehot`).

(b) **Special instruction return / sleep** (no `exc_req_q | store_err_q | load_err_q`):

- `mret_insn` → `pc_mux_o = PC_ERET`, `pc_set_o = 1`,
  `csr_restore_mret_id_o = 1`, and if `nmi_mode_q = 1` then
  `nmi_mode_d = 0`.
- `dret_insn` → `pc_mux_o = PC_DRET`, `pc_set_o = 1`,
  `csr_restore_dret_id_o = 1`, `debug_mode_d = 0`.
- `wfi_insn` → `ctrl_fsm_ns = WAIT_SLEEP`.

(c) **Unconditional override at end of FLUSH:**
- If `enter_debug_mode_prio_q && !(ebrk_insn_prio && ebreak_into_debug)`:
  `ctrl_fsm_ns = DBG_TAKEN_IF` (overrides whatever (a)/(b) set).

#### Scenario: Illegal-instruction exception
- GIVEN FLUSH, `exc_req_q = 1`, `illegal_insn_q = 1` (set last cycle),
  `instr_fetch_err_q = 0`, `instr_is_compressed_i = 0`, `instr_i = 0xDEADBEEF`.
- THEN `illegal_insn_prio = 1`, `pc_set_o = 1`,
  `exc_pc_mux_o = EXC_PC_EXC`, `exc_cause_o = ExcCauseIllegalInsn`,
  `csr_mtval_o = 0xDEADBEEF`, `csr_save_cause_o = 1`,
  `flush_id = 1`, next-state DECODE.
- (ref: ibex_controller.sv:728–795)

#### Scenario: Load access fault
- GIVEN FLUSH, `exc_req_q = 0`, `load_err_q = 1`, `store_err_q = 0`.
- THEN under `WritebackStage=0` priority: `load_err_prio = 1`.
- `pc_set_o = 1`, `pc_mux_o = PC_EXC`, `exc_pc_mux_o = EXC_PC_EXC`,
  `exc_cause_o = ExcCauseLoadAccessFault`,
  `csr_mtval_o = lsu_addr_last_i`, `csr_save_cause_o = 1`.
- (ref: ibex_controller.sv:790–793)

#### Scenario: ECALL from M-mode
- GIVEN FLUSH, `exc_req_q = 1`, `ecall_insn = 1`, `priv_mode_i = PRIV_LVL_M`.
- THEN `ecall_insn_prio = 1`, `exc_cause_o = ExcCauseEcallMMode`.
- (ref: ibex_controller.sv:766–769)

---

### Requirement 6: WFI / sleep cycle

A WFI in DECODE MUST drive the FSM through `DECODE → FLUSH →
WAIT_SLEEP → SLEEP → FIRST_FETCH`, with `ctrl_busy_o = 0` only in
`WAIT_SLEEP` and idle `SLEEP`.

State outputs:

- `WAIT_SLEEP`: `ctrl_busy_o = 0`, `instr_req_o = 0`, `halt_if = 1`,
  `flush_id = 1`, `ctrl_fsm_ns = SLEEP` (unconditional).
- `SLEEP`: `instr_req_o = 0`, `halt_if = 1`, `flush_id = 1`.
  - If `irq_nm | irq_pending_i | debug_req_i | debug_mode_q |
    debug_single_step_i`: `ctrl_fsm_ns = FIRST_FETCH`.
  - Else: `ctrl_busy_o = 0` (clock-gate may de-assert).
- `FIRST_FETCH` after sleep: identical to startup (Requirement 1).

#### Scenario: WFI then external IRQ wake
- GIVEN DECODE, `instr_valid_i = 1`, `wfi_insn_i = 1`.
- WHEN cycle N: `wfi_insn = 1` → `special_req_flush_only = 1` →
  `special_req = 1`, `retain_id = 1`, `ctrl_fsm_ns = FLUSH`.
- WHEN cycle N+1 (FLUSH): no exception (`exc_req_q = 0`), `wfi_insn = 1`,
  `ctrl_fsm_ns = WAIT_SLEEP`.
- WHEN cycle N+2 (WAIT_SLEEP): `ctrl_busy_o = 0`, `instr_req_o = 0`,
  next-state SLEEP.
- WHEN cycle N+3+ (SLEEP, no wake): `ctrl_busy_o = 0`.
- WHEN external IRQ asserts (`irq_pending_i & irq_enabled = 1` ⇒
  the WHEN clause in SLEEP is true): `ctrl_fsm_ns = FIRST_FETCH`.
  Note: SLEEP wake checks `irq_pending_i` directly (not gated by
  `csr_mstatus_mie_i`); `handle_irq` is computed downstream in
  FIRST_FETCH/DECODE.
- (ref: ibex_controller.sv:511–534, 810–812)

---

### Requirement 7: MRET / DRET return

- MRET in DECODE MUST go via FLUSH and produce a `PC_ERET` redirect with
  `csr_restore_mret_id_o = 1`. If currently in NMI mode (`nmi_mode_q = 1`),
  `nmi_mode_d = 0` (NMI mode clears).
- DRET in DECODE MUST go via FLUSH and produce a `PC_DRET` redirect with
  `csr_restore_dret_id_o = 1` and `debug_mode_d = 0` (debug mode clears).

#### Scenario: MRET from NMI handler
- GIVEN nmi_mode_q = 1, DECODE, `mret_insn_i = 1`, `instr_valid_i = 1`.
- WHEN cycle N+1 (FLUSH): `exc_req_q = 0`, `mret_insn = 1`,
  `pc_mux_o = PC_ERET`, `pc_set_o = 1`,
  `csr_restore_mret_id_o = 1`, `nmi_mode_d = 0`.
- WHEN cycle N+2 (DECODE): `nmi_mode_q = 0`.
- (ref: ibex_controller.sv:798–804)

#### Scenario: DRET from debug mode
- GIVEN debug_mode_q = 1, DECODE, `dret_insn_i = 1`, `instr_valid_i = 1`.
- WHEN cycle N+1 (FLUSH): `pc_mux_o = PC_DRET`, `pc_set_o = 1`,
  `csr_restore_dret_id_o = 1`, `debug_mode_d = 0`.
- WHEN cycle N+2 (DECODE): `debug_mode_q = 0`.
- (ref: ibex_controller.sv:805–809)

---

### Requirement 8: csr_save_* output rules

The CSR save/restore strobes are state-conditional:

| State          | csr_save_if | csr_save_id | csr_save_wb | csr_save_cause | csr_restore_mret | csr_restore_dret | debug_csr_save |
|----------------|-------------|-------------|-------------|----------------|------------------|------------------|----------------|
| RESET          | 0           | 0           | 0           | 0              | 0                | 0                | 0              |
| BOOT_SET       | 0           | 0           | 0           | 0              | 0                | 0                | 0              |
| FIRST_FETCH    | 0           | 0           | 0           | 0              | 0                | 0                | 0              |
| DECODE         | 0           | 0           | 0           | 0              | 0                | 0                | 0              |
| IRQ_TAKEN (handle_irq) | **1** | 0           | 0           | **1**          | 0                | 0                | 0              |
| DBG_TAKEN_IF   | **1**       | 0           | 0           | **1**          | 0                | 0                | **1**          |
| DBG_TAKEN_ID (forced entry) | 0 | **1**     | 0           | **1**          | 0                | 0                | **1**          |
| DBG_TAKEN_ID (re-entry from debug) | 0 | 0 | 0       | 0              | 0                | 0                | 0              |
| FLUSH (exception, fetch_err/illegal/ecall/store_err/load_err) | 0 | 0 | 0 | **1** | 0 | 0 | 0          |
| FLUSH (ebrk → DBG_TAKEN_ID redirect) | 0 | 0 | 0  | 0              | 0                | 0                | 0              |
| FLUSH (mret)   | 0           | 0           | 0           | 0              | **1**            | 0                | 0              |
| FLUSH (dret)   | 0           | 0           | 0           | 0              | 0                | **1**            | 0              |
| WAIT_SLEEP     | 0           | 0           | 0           | 0              | 0                | 0                | 0              |
| SLEEP          | 0           | 0           | 0           | 0              | 0                | 0                | 0              |

Specifically: under `WritebackStage=0`, in FLUSH for an exception
`csr_save_id_o = 1'b0` (the `g_no_writeback_mepc_save` branch). The
CSR's epc must come from IF in this configuration.

`csr_save_wb_o` MUST be constant `0` under `WritebackStage=0`.

---

### Requirement 9: Latched decoder/LSU state registers

The controller flops a small set of qualified decoder/LSU outputs on
every clock edge (synchronous to `clk_i`, async-reset to `0` via
`rst_ni`):

- `illegal_insn_q ← illegal_insn_d = illegal_insn_i & (ctrl_fsm_cs != FLUSH)`
- `exc_req_q     ← exc_req_d     = (ecall_insn | ebrk_insn | illegal_insn_d | instr_fetch_err) & (ctrl_fsm_cs != FLUSH)`
- `load_err_q    ← load_err_d    = load_err_i`
- `store_err_q   ← store_err_d   = store_err_i`

Where the AND-with-`instr_valid_i` qualifications are combinational
helpers, NOT flopped:

- `ecall_insn      = ecall_insn_i      & instr_valid_i`
- `mret_insn       = mret_insn_i       & instr_valid_i`
- `dret_insn       = dret_insn_i       & instr_valid_i`
- `wfi_insn        = wfi_insn_i        & instr_valid_i`
- `ebrk_insn       = ebrk_insn_i       & instr_valid_i`
- `csr_pipe_flush  = csr_pipe_flush_i  & instr_valid_i`
- `instr_fetch_err = instr_fetch_err_i & instr_valid_i`

(Note: the proposal listed `mret_insn_q`, `dret_insn_q`, `wfi_insn_q`,
`ebrk_insn_q`, `ecall_insn_q`, `instr_fetch_err_q` etc. as flopped.
Upstream actually keeps these combinational and only flops
`illegal_insn_q`, `exc_req_q`, `load_err_q`, `store_err_q`. The
implementer should follow the upstream — flopping the others would
delay the flush-trigger by a cycle and break Requirement 2's
DECODE→FLUSH transition.)

The "(ctrl_fsm_cs != FLUSH)" gate on `illegal_insn_d` and `exc_req_d`
is an explicit one-cycle clear: as soon as the FSM enters FLUSH, the
next-cycle value of these flops is `0`, which prevents a stale
exception request from re-firing on the FLUSH→DECODE return.

#### Scenario: Illegal instruction sample-and-flush
- GIVEN DECODE, cycle N: `illegal_insn_i = 1`, `instr_valid_i = 1`.
- THEN cycle N: `illegal_insn_d = 1`, `exc_req_d = 1`, `id_exception_o = 1`,
  `special_req = 1`, `retain_id = 1`, `ctrl_fsm_ns = FLUSH`.
- THEN cycle N+1 (FLUSH): `illegal_insn_q = 1`, `exc_req_q = 1`,
  `illegal_insn_prio = 1`. Also during the FLUSH cycle,
  `illegal_insn_d = 0` (because `ctrl_fsm_cs == FLUSH`), so
  `illegal_insn_q` will be `0` again at cycle N+2.
- (ref: ibex_controller.sv:200–215, 874–895)

---

### Requirement 10: debug_mode_q and nmi_mode_q

`debug_mode_q` and `nmi_mode_q` are flopped (async-low reset to `0`)
mode flags. Their next-state `debug_mode_d` / `nmi_mode_d` defaults to
the current value, and is assigned in specific FSM states:

- `debug_mode_d = 1` in `DBG_TAKEN_IF` and `DBG_TAKEN_ID`.
- `debug_mode_d = 0` in FLUSH on `dret_insn`.
- `nmi_mode_d = 1` in `IRQ_TAKEN` when `irq_nm & !nmi_mode_q`.
- `nmi_mode_d = 0` in FLUSH on `mret_insn` when `nmi_mode_q = 1`.
- `debug_mode_o = debug_mode_q` (output is the flop directly).
- `nmi_mode_o = nmi_mode_q` (output is the flop directly).
- `debug_mode_entering_o = 1` only in `DBG_TAKEN_IF` / `DBG_TAKEN_ID`.

Pipeline-flush invariant: whenever `debug_mode_d != debug_mode_q`,
`flush_id_o = 1` AND `pc_set_o = 1` (`IbexPipelineFlushOnChangingDebugMode`
assertion). The implementer must preserve this — both DBG_TAKEN_IF /
DBG_TAKEN_ID set `flush_id = 1` and `pc_set_o = 1`, and the FLUSH-DRET
clause sets both as well.

#### Scenario: NMI entry → MRET clears nmi_mode_q
- GIVEN cycle N: IRQ_TAKEN with `irq_nm = 1`, `nmi_mode_q = 0`.
- THEN cycle N+1 (DECODE): `nmi_mode_q = 1`.
- … later … MRET in DECODE → FLUSH (cycle M): `mret_insn = 1`,
  `nmi_mode_q = 1`, so `nmi_mode_d = 0`.
- THEN cycle M+1 (DECODE): `nmi_mode_q = 0`.
- (ref: ibex_controller.sv:657, 802–804)

---

### Requirement 11: mfip_id priority encoder for fast IRQs

`mfip_id` MUST be the index `[3:0]` of the highest-numbered set bit of
the 15-wide `irqs_i.irq_fast`, or `0` if all bits are clear. (Upstream
implements this as a for-loop over `i = 14..0` that overwrites
`mfip_id` whenever `irq_fast[i]` is set; the highest `i` wins because
the loop iterates downward and the last-overwriting iteration is the
lowest `i` that is set — but the **first** assignment has highest
index. Wait — re-reading: the loop walks `i` from 14 down to 0 and
overwrites on each set bit, so the last overwriting iteration is the
smallest `i` that is set, meaning `mfip_id` ends up as the **lowest**
set fast-IRQ index, not the highest. See Spec notes for clarification.)

- The output of mfip_id is concatenated with `1'b1` to form the lower
  cause: `lower_cause = {1'b1, mfip_id}` (5 bits) → cause IDs in
  range `5'd16..5'd31` (`ExcCauseIrqFast0..15`).
- `irqs_i.irq_timer` is intentionally not used in any controller logic
  beyond `irq_pending_i` (it's tied to `unused_irq_timer` in upstream).
  The controller drives `ExcCauseIrqTimerM` only when none of NMI /
  fast / external / software is pending (default arm in IRQ_TAKEN).

#### Scenario: fast IRQ 0 only
- GIVEN `irqs_i.irq_fast = 15'b000_0000_0000_0001`.
- THEN `mfip_id = 4'd0`, `lower_cause = 5'd16` (= `ExcCauseIrqFast0`).
- (ref: ibex_controller.sv:417–425)

---

### Requirement 12: pc_mux_o / exc_pc_mux_o driving rules per state

The `pc_mux_o` / `exc_pc_mux_o` values are only architecturally
meaningful when `pc_set_o = 1`. The defaults at the top of the
combinational always-block are `pc_mux_o = PC_BOOT`,
`exc_pc_mux_o = EXC_PC_IRQ`, `exc_cause_o = ExcCauseInsnAddrMisa`.
State overrides:

| State          | pc_mux_o   | pc_set_o conditions                        | exc_pc_mux_o          | exc_cause_o                |
|----------------|------------|--------------------------------------------|-----------------------|----------------------------|
| RESET          | PC_BOOT    | `1` (always)                               | EXC_PC_IRQ (default)  | ExcCauseInsnAddrMisa       |
| BOOT_SET       | PC_BOOT    | `1` (always)                               | EXC_PC_IRQ            | ExcCauseInsnAddrMisa       |
| FIRST_FETCH    | PC_BOOT    | `0`                                        | EXC_PC_IRQ            | ExcCauseInsnAddrMisa       |
| DECODE         | PC_JUMP    | `1` iff `branch_set_i \| jump_set_i`       | EXC_PC_IRQ            | ExcCauseInsnAddrMisa       |
| IRQ_TAKEN      | PC_EXC     | `1` iff `handle_irq`                        | EXC_PC_IRQ            | per Requirement 3 priority |
| DBG_TAKEN_IF   | PC_EXC     | `1`                                        | EXC_PC_DBD            | (don't-care, csr ignores)  |
| DBG_TAKEN_ID   | PC_EXC     | `1`                                        | EXC_PC_DBD            | (don't-care)               |
| FLUSH (exception path) | PC_EXC | `1`                                      | `debug_mode_q ? EXC_PC_DBG_EXC : EXC_PC_EXC` | per Requirement 5 priority |
| FLUSH (mret)   | PC_ERET    | `1`                                        | (don't-care)          | (don't-care)               |
| FLUSH (dret)   | PC_DRET    | `1`                                        | (don't-care)          | (don't-care)               |
| FLUSH (wfi-only) | PC_BOOT  | `0`                                        | EXC_PC_IRQ            | (don't-care)               |
| FLUSH (ebrk → DBG_TAKEN_ID) | PC_EXC | `0` (overridden)                  | EXC_PC_EXC (overridden)| (don't-care)               |
| WAIT_SLEEP     | PC_BOOT    | `0`                                        | EXC_PC_IRQ            | (don't-care)               |
| SLEEP          | PC_BOOT    | `0`                                        | EXC_PC_IRQ            | (don't-care)               |

`nt_branch_mispredict_o` MUST be constant `0` under `BranchPredictor=0`.

`PC_BP` MUST never be selected under `BranchPredictor=0`.

---

## FSM transition table

| From          | Condition                                                                            | To             |
|---------------|--------------------------------------------------------------------------------------|----------------|
| RESET         | (unconditional, 1 cycle)                                                             | BOOT_SET       |
| BOOT_SET      | (unconditional, 1 cycle)                                                             | FIRST_FETCH    |
| FIRST_FETCH   | `enter_debug_mode`                                                                   | DBG_TAKEN_IF   |
| FIRST_FETCH   | `handle_irq` (& not entering debug)                                                  | IRQ_TAKEN      |
| FIRST_FETCH   | `id_in_ready_o` & not above                                                          | DECODE         |
| FIRST_FETCH   | otherwise                                                                            | FIRST_FETCH    |
| DECODE        | `special_req` & `(ready_wb_i \| wb_exception_o)` (always under WS=0)                 | FLUSH          |
| DECODE        | `!stall & !special_req & !id_wb_pending & enter_debug_mode`                          | DBG_TAKEN_IF   |
| DECODE        | `!stall & !special_req & !id_wb_pending & handle_irq` (& not enter_debug_mode)       | IRQ_TAKEN      |
| DECODE        | otherwise                                                                            | DECODE         |
| IRQ_TAKEN     | (unconditional)                                                                      | DECODE         |
| DBG_TAKEN_IF  | (unconditional)                                                                      | DECODE         |
| DBG_TAKEN_ID  | (unconditional)                                                                      | DECODE         |
| FLUSH         | `exc_req_q & ebrk_insn_prio & (debug_mode_q \| ebreak_into_debug)`                   | DBG_TAKEN_ID   |
| FLUSH         | `enter_debug_mode_prio_q & !(ebrk_insn_prio & ebreak_into_debug)`                    | DBG_TAKEN_IF   |
| FLUSH         | `!exc_req_q & !store_err_q & !load_err_q & wfi_insn`                                 | WAIT_SLEEP     |
| FLUSH         | otherwise                                                                            | DECODE         |
| WAIT_SLEEP    | (unconditional)                                                                      | SLEEP          |
| SLEEP         | `irq_nm \| irq_pending_i \| debug_req_i \| debug_mode_q \| debug_single_step_i`      | FIRST_FETCH    |
| SLEEP         | otherwise                                                                            | SLEEP          |
| (any unknown) | default arm                                                                          | RESET          |

Reset state: `ctrl_fsm_cs = RESET` on `~rst_ni`.

---

## Integration constraints

### IC-1: Decoder qualifies its outputs by instr_valid_i (producer-side)

The decoder's `*_insn_o` outputs (`illegal_insn_o`, `ebrk_insn_o`,
`mret_insn_o`, `dret_insn_o`, `ecall_insn_o`, `wfi_insn_o`,
`csr_pipe_flush_o`) are gated by `instr_valid_i` upstream
(`ibex_id_stage.sv:541`: `assign illegal_insn_o = instr_valid_i & ...`),
but the controller does NOT trust this — it re-applies the
`& instr_valid_i` gate combinationally for `ecall`/`mret`/`dret`/
`wfi`/`ebrk`/`csr_pipe_flush`/`instr_fetch_err` (Requirement 9). The
single exception is `illegal_insn_i`, which the controller flops as
`illegal_insn_q` directly without re-gating; this is safe because of
the upstream assertion `IllegalInsnOnlyIfInsnValid`
(`illegal_insn_i |-> instr_valid_i`).

### IC-2: LSU error pulses are 1-cycle (producer-side)

`load_err_i` and `store_err_i` from the LSU are asserted for exactly
one cycle. The controller flops them into `load_err_q` / `store_err_q`
on the same cycle, and they remain visible in `*_q` for use in FLUSH
the next cycle. There is no `(ctrl_fsm_cs != FLUSH)` gate on `load_err_d`
/ `store_err_d` — they shadow the input directly — so a back-to-back
LSU error during FLUSH is captured. (See Spec note on FLUSH same-cycle
LSU error.)

### IC-3: ID stage gates its handshake on id_in_ready_o (consumer-side)

ID stage uses `id_in_ready_o` to gate its instruction-accept handshake
(`ibex_id_stage.sv` line ~577 wires it back into IF/ID). The
controller drives `id_in_ready_o = ~stall & ~halt_if & ~retain_id`,
so `id_in_ready_o = 0` whenever:
- `stall_id_i` is high (multicycle in ID), or
- the FSM has set `halt_if = 1` (FLUSH, WAIT_SLEEP, SLEEP, DBG_TAKEN_*,
  pre-IRQ-entry from FIRST_FETCH/DECODE, or `instr_exec_i = 0`), or
- DECODE is in the special-request stall (`retain_id = 1`).

ID stage MUST sample this each cycle, not only on FSM-state changes.

### IC-4: instr_valid_clear_o relationship to retain_id

`instr_valid_clear_o = ~(stall | retain_id) | flush_id`. Concretely:
- In normal DECODE with no stall and no special_req:
  `instr_valid_clear_o = 1` (the ID instruction is consumed).
- In DECODE with `special_req = 1` (retain_id = 1) AND no flush_id:
  `instr_valid_clear_o = 0` (instruction held for FLUSH inspection).
- In any state with `flush_id = 1` (FLUSH, WAIT_SLEEP, SLEEP,
  DBG_TAKEN_IF, DBG_TAKEN_ID-default-path):
  `instr_valid_clear_o = 1` (instruction killed).
- In `stall = 1`: `instr_valid_clear_o = 0` (instruction held).

This rule is what guarantees the FLUSH state has the correct
priority-encoder inputs available (the ID instruction must still be
visible during FLUSH).

### IC-5: instr_exec_i forces halt_if (top-level override)

The very last action of the controller's combinational block is:
```
if (~instr_exec_i) halt_if = 1'b1;
```
This MUST be the LAST override on `halt_if` — it overrides every
state's default of `halt_if = 0`. Effect: when the top level wants to
suppress execution (e.g. for clock-gating handoff), `id_in_ready_o = 0`
and the controller stops accepting instructions, but the FSM continues
running on its current state's outputs.

### IC-6: handle_irq and enter_debug_mode are computed combinationally

Neither helper is flopped. They are sampled fresh every cycle:
- `handle_irq` depends on `irqs_i`, `irq_pending_i`, `csr_mstatus_mie_i`,
  `priv_mode_i`, `irq_nm_ext_i`, and the mode flops (`debug_mode_q`,
  `nmi_mode_q`, `debug_single_step_i`).
- `enter_debug_mode` depends on `debug_req_i`, `debug_single_step_i`,
  `trigger_match_i`, `instr_valid_i`, `debug_mode_q`, `do_single_step_q`.

This means a 1-cycle pulse of `debug_req_i` will be reflected in the
FSM transition the same cycle it asserts (subject to the gating in
Requirement 4), without a 1-cycle latency.

### IC-7: SLEEP wake uses raw irq_pending_i, not handle_irq

Note that the wake condition in SLEEP is
`irq_nm | irq_pending_i | debug_req_i | debug_mode_q | debug_single_step_i`,
which uses **raw** `irq_pending_i` (not gated by `csr_mstatus_mie_i` or
`priv_mode_i`). This is intentional — even with MIE=0 the WFI must be
woken by an IRQ for the architecture to make progress (the IRQ won't
be **taken** in FIRST_FETCH/DECODE if MIE=0, but the core leaves SLEEP
to recheck). The implementer MUST NOT substitute `handle_irq` for the
raw expression here.

### IC-8: nt_branch_mispredict_o tied to instr_valid_clear_o (assertion)

Upstream assertion `AlwaysInstrClearOnMispredict`:
`nt_branch_mispredict_o |-> instr_valid_clear_o`. Under
`BranchPredictor=0` `nt_branch_mispredict_o = 0` always, so the
constraint is trivially satisfied; the implementer MUST NOT inadvertently
drive `nt_branch_mispredict_o = 1` from any path.

### IC-9: Pipeline empty before IRQ_TAKEN (assertion)

Upstream assertion `PipeEmptyOnIrq`:
`ctrl_fsm_cs != IRQ_TAKEN & ctrl_fsm_ns == IRQ_TAKEN |-> ~instr_valid_i & ready_wb_i`.
Under `WritebackStage=0`, `ready_wb_i = 1` is automatic, so the
constraint reduces to "instr_valid_i is low when entering IRQ_TAKEN".
The DECODE clause that gates the IRQ transition by
`!stall & !special_req & !id_wb_pending` (where `id_wb_pending =
instr_valid_i` under pin) provides exactly this guarantee. The
FIRST_FETCH path also satisfies it because instr_valid_i is gated by
the IF→ID handshake.

---

## Spec notes

### N-1: Simulation-only `negedge clk_i` block

Upstream `ibex_controller.sv:174–180` contains an
`always_ff @(negedge clk_i)` block — but this is **not** a state
register. It is wrapped in `` `ifndef SYNTHESIS `` and contains a
single `$display` for an illegal-instruction warning. It MUST NOT be
ported. The proposal's caveat #2 ("`do_single_step_d/q` register at
line 174 is on `negedge clk_i`") is incorrect: the actual
`do_single_step_q` register is in the regular synchronous-update block
at line 874–895 (`always_ff @(posedge clk_i or negedge rst_ni)`),
along with all other state. There is **no** falling-edge state
register in this module. The implementer should treat the entire FSM
+ flop set as standard rising-edge `seq on clk_i` with async-low
reset.

### N-2: `mfip_id` direction of priority

Upstream `gen_mfip_id` (lines 417–425) is a for-loop `for (int i = 14;
i >= 0; i--) if (irqs_i.irq_fast[i]) mfip_id = i[3:0];`. Because the
loop iterates from 14 down to 0 and overwrites `mfip_id` on every set
bit, the **last** overwrite (i.e. the smallest `i` that is set) wins.
So `mfip_id` is the **lowest** set fast-IRQ index, not the highest.
This contradicts the proposal's "highest priority to lowest ID"
comment header text — the priority is actually highest (i.e. lowest
index) when mapping ID `0` = highest priority. ARCH's `find_first` Vec
method (which returns the lowest index of a set bit) is therefore the
correct primitive. The Requirement 11 scenario above uses the lowest
set bit; if a test enumerates multiple bits it should expect the
lowest index to win.

### N-3: `enter_debug_mode_prio_q` capture window

`enter_debug_mode_prio_d = (debug_req_i | do_single_step_d) & ~debug_mode_q`
is flopped into `enter_debug_mode_prio_q`. This flop is the
mechanism by which a debug request asserted while the FSM is taking
an exception (so it transitions DECODE→FLUSH first) is preserved into
the FLUSH state — at end-of-FLUSH the override redirects to
DBG_TAKEN_IF. The implementer must expose this state as a flop, not as
a re-evaluation of `debug_req_i` in FLUSH (the request might be
de-asserted by then).

### N-4: `do_single_step_d/q` semantics

`do_single_step_d = instr_valid_i ? (~debug_mode_q & debug_single_step_i)
                                  : do_single_step_q`. Reading: when
`instr_valid_i = 0` the flop holds; when `instr_valid_i = 1`, it loads
`(~debug_mode_q & debug_single_step_i)`. The intended behavior:
"latch single-step-pending on the first valid instruction outside
debug mode; clear it on the first valid instruction inside debug
mode". The implementer MUST preserve this hold-vs-load semantics
exactly — converting it to a plain register-with-enable would
double-clear the flag.

### N-5: FLUSH reentry due to LSU error during FLUSH

`load_err_d = load_err_i` and `store_err_d = store_err_i` are NOT
gated by `(ctrl_fsm_cs != FLUSH)`. So if an LSU error pulses during
the FLUSH cycle that is handling an unrelated exception, `load_err_q`
or `store_err_q` will assert next cycle — which is benign because
FLUSH always returns to DECODE, and a new LSU exception arriving on
the FLUSH→DECODE boundary will be caught by the next DECODE→FLUSH
transition via `exc_req_lsu`.

### N-6: `unused_irq_timer` and `mem_resp_intg_err_i`

Under the SoC pinning, `irqs_i.irq_timer` is assigned to
`unused_irq_timer` (it is read in IRQ_TAKEN's else-branch but is not
**prioritized** explicitly because `handle_irq` already qualified it).
`mem_resp_intg_err_i` is connected to `unused_mem_resp_intg_err_i`
inside the `g_no_intg_irq_int` block (`MemECC=0`). The implementer
should declare these inputs but may treat them as no-ops in the ARCH
body.

### N-7: `default` arm of the FSM case

The `default:` arm of `unique case (ctrl_fsm_cs)` sets `instr_req_o = 0`
and `ctrl_fsm_ns = RESET`. Since the state enum is exhaustive
(`IbexCtrlStateValid` asserts membership), this arm is unreachable in
synthesis — but the implementer MUST emit it (or the ARCH-equivalent
"stuck-state recovery") so the lowered SV preserves the same
unique-case-with-default shape.
