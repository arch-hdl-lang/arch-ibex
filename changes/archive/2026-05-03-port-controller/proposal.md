# Proposal: Port `ibex_controller` to ARCH

## Intent

This swap replaces `ibex_controller.sv` (944 LoC upstream) with
`src/IbexController.arch`. `ibex_controller` is the pipeline
controller — the main FSM that sequences the core through reset →
boot → fetch → decode → execute, and handles all asynchronous
disruptions (interrupts, debug requests, exceptions, WFI sleep, fence
flushes, mret/dret returns).

This is the fourth Phase B composite swap and the **first swap that
genuinely needs the `fsm` construct** — every prior leaf used plain
`module` + `seq`, and the prior composites (B1 IbexExBlock, B2
IbexWbStage, B3 IbexIfStage) were structural wrappers without
multi-state sequencing of their own. The controller is a 9-active-state
machine with state-dependent outputs and rich state-to-state branching.

## Scope

**In scope (matches `ibex_top.sv` + `mini_soc.sv` parameter pins):**

- `WritebackStage = 1'b0` — no writeback stage; `ready_wb_i = 1`,
  `wb_exception_o = 0`. The `g_no_wb_exceptions` upstream branch is
  the only exception-priority path.
- `BranchPredictor = 1'b0` — `instr_bp_taken_i = 0`,
  `branch_not_set_i = 0`, `nt_branch_mispredict_o = 0`. The branch-set
  path uses a constant `pc_set_o = 1'b1` (the `BranchPredictor ?
  ~instr_bp_taken_i : 1'b1` ternary collapses).
- `MemECC = 1'b0` — `g_no_intg_irq_int` branch only;
  `irq_nm_int = 0`, `irq_nm_int_cause = 0`, `irq_nm_int_mtval = 0`.
- All 9 active FSM states: `RESET`, `BOOT_SET`, `FIRST_FETCH`,
  `DECODE`, `IRQ_TAKEN`, `DBG_TAKEN_IF`, `DBG_TAKEN_ID`, `FLUSH`,
  `WAIT_SLEEP`, `SLEEP`.
- Exception priority encoding (`unique case (1'b1)` over
  `instr_fetch_err_q`, `illegal_insn_q`, `ecall_insn_q`,
  `ebrk_insn_q`, `store_err_q`, `load_err_q`).
- IRQ priority logic (NMI > fast > external > software > timer).
- Debug-entry conditions (`enter_debug_mode`).
- WFI / sleep handling.
- MRET / DRET return paths.
- `mfip_id` (find-first-set encoder for fast IRQs, 15-bit input → 4-bit ID).
- Latched-decoder-output state regs (`exc_req_q`, `illegal_insn_q`,
  `ecall_insn_q`, `mret_insn_q`, `dret_insn_q`, `wfi_insn_q`,
  `ebrk_insn_q`, `csr_pipe_flush`, `instr_fetch_err_q`,
  `instr_fetch_err_plus2_q`, `store_err_q`, `load_err_q`).
- Mode/state regs (`debug_mode_q`, `nmi_mode_q`).

**Out of scope:**

- `WritebackStage = 1` (the `g_wb_exceptions` and
  `g_writeback_mepc_save` branches; `wb_exception_o` priority logic).
- `BranchPredictor = 1` (skid buffer, branch-mispredict signaling,
  `g_bp_taken_*` branch).
- `MemECC = 1` (`g_intg_irq_int` SECDED-error injection; not part of
  the basic IRQ flow).
- `SecureIbex = 1` features (DummyInstructions, dummy LFSR — handled
  in IF stage; not the controller's concern under SoC pins).
- The `assert_static_in_decode` SVA / `LSU_HANDLES_EXC` assertion (sim
  assertions; not synthesizable spec).

## Construct enumeration

| Construct      | Status | Reason |
|----------------|--------|--------|
| `module`       | **picked** | Outer wrapper for the whole controller — declares ports, holds the latched decoder-output regs, the mode regs, and the `fsm` instance. |
| `fsm`          | **picked** | The 9-active-state controller is the textbook `fsm` use case: multi-state branching with state-dependent outputs and complex transitions. The `case (ctrl_fsm_cs)` in upstream lowers directly to ARCH `fsm` states. |
| `thread`       | **rejected** | The controller is a **reactive state machine**, not a sequential walker with `wait until cond;` cycles. Per `feedback_thread_single_state_idiom`, threads are right when the structure is "do A; wait; do B; wait; …" — but here every state is conditionally re-entered each cycle and transitions are input-dependent. The HANDOFF hint (`fsm` + `thread`) was speculative; the actual shape of the upstream FSM is `fsm`-only. |
| `fifo`         | **rejected** | No queueing; control state is a single register. |
| `ram` / `cam`  | **N/A** | No address-indexed storage. |
| `linklist`     | **N/A** | No pointer-chained storage. |
| `regfile`      | **N/A** | The latched decoder-output regs are individual flops with shared write-enable (`instr_valid_i`), modelled as plain `reg ... guard instr_valid_i` (or `port reg`-equivalent). Not a multi-port regfile. |
| `arbiter`      | **rejected** | The IRQ-priority encoding is a static `if-else` ladder (NMI > fast > external > software > timer), not a request/grant arbiter. |
| `counter`      | **N/A** | No freestanding count primitive. |
| `pipeline`     | **rejected** | The controller is the *consumer* of the pipeline's stall/ready signals; it doesn't declare its own pipeline shape. |
| `synchronizer` | **N/A** | Single clock domain. |
| `clkgate`      | **N/A** | The controller signals `ctrl_busy_o` for clock-gating in `ibex_top`, but doesn't own the gate cell. |

## Approach

**Outer structure:** `module ibex_controller` (snake_case for SoC compat) with const params:
- `param WritebackStage[0:0]: const = 1'd0;`
- `param BranchPredictor[0:0]: const = 1'd0;`
- `param MemECC[0:0]: const = 1'd0;`

**`fsm` construct:** declares the state register and lowers to a `case
(ctrl_fsm_cs)` block in SV. State enum:

```
fsm CtrlFsm states {RESET, BOOT_SET, FIRST_FETCH, DECODE, IRQ_TAKEN,
                    DBG_TAKEN_IF, DBG_TAKEN_ID, FLUSH, WAIT_SLEEP, SLEEP}
  initial RESET
  ... (state bodies — see ARCH spec §10 for the syntax)
```

Each state body computes per-state outputs (e.g. `pc_mux_o = PC_BOOT;`)
and the next-state transition (`ctrl_fsm_ns = ...;`).

**Latched decoder-output regs** (clocked by `instr_valid_i &
~instr_valid_clear_o`, async-low reset to 0):
- `exc_req_q` = OR of all decoder exception flags
- `illegal_insn_q`, `ecall_insn_q`, `mret_insn_q`, `dret_insn_q`,
  `wfi_insn_q`, `ebrk_insn_q`, `csr_pipe_flush`
- `instr_fetch_err_q`, `instr_fetch_err_plus2_q`
- `store_err_q`, `load_err_q` (latched on `lsu_store_err_i` /
  `lsu_load_err_i`, async-low reset)

**Mode regs** (async-low reset):
- `debug_mode_q: Bool` — `1` while in debug mode
- `nmi_mode_q: Bool` — `1` while in NMI mode

**Comb signals:**
- `handle_irq` — gating for IRQ entry
- `enter_debug_mode` — gating for debug entry
- `special_req` — exception/CSR-flush request
- `id_wb_pending` (= 0 under WritebackStage=0)
- `mfip_id` (4-bit fast-IRQ ID, find-first-set on `irqs_i.irq_fast`)
- `irq_pending_o`, output gates (`pc_mux_o`, `pc_set_o`, etc.)

## Verification gate

**Basic gate (blocking):**
```
make build
pytest tests/test_ibex_controller_unit.py tests/test_soc_lint.py tests/test_cpu_programs.py
```

**Full regression (background):**
```
pytest tests/test_ibex_controller_unit_full.py
```

The basic suite covers each FSM state's primary transition (RESET →
BOOT_SET, BOOT_SET → FIRST_FETCH, FIRST_FETCH → DECODE, DECODE →
{IRQ_TAKEN | DBG_TAKEN_IF | FLUSH}, IRQ_TAKEN → DECODE, DBG_TAKEN_*
→ DECODE, FLUSH → DECODE, WAIT_SLEEP → SLEEP, SLEEP → FIRST_FETCH).
Plus exception priority encoding, IRQ priority encoding (NMI > fast >
ext > sw > timer), `debug_mode_q` / `nmi_mode_q` set / clear.

The SoC lint and 4 ISR programs validate that the controller routes
real IRQs / exceptions / debug entries through the larger pipeline
correctly.

## Verification gate caveats

1. **Latched decoder outputs**: the controller latches every decoder
   flag (`illegal_insn_i`, `ecall_insn_i`, etc.) on the cycle when
   `instr_valid_i` first asserts, so `exc_req_q` etc. are 1 cycle
   behind their `_i` counterparts. Tests must drive `instr_valid_i`
   and the flag together for one cycle, then sample the `_q` output
   on the *next* cycle's transition.

2. **Async-low reset on `clk` falling edge**: upstream uses
   `always_ff @(negedge clk_i)` for the *enter_debug_mode latching
   pulse* register at line 174 (`do_single_step_d/q`). This is unusual
   — the rest of the module uses `posedge clk_i`. Per the
   `feedback_arch_syntax_pitfalls`, ARCH's default is rising edge;
   this one register needs `seq on clk_i falling` or a comb/reg
   restructuring that matches upstream's intent. Spec extractor and
   implementer should treat this as a known caveat.

3. **`mfip_id` priority encoder**: 15-bit one-hot input → 4-bit ID
   output. Upstream uses a `for` loop with priority break. ARCH's
   `find_first` Vec method is the natural fit (per
   `ARCH_HDL_Specification.md` §"find_first" and the B1 IbexExBlock
   precedent).

4. **`exc_cause` field assignment**: the controller writes
   `exc_cause_o = '{irq_ext: ..., irq_int: ..., lower_cause: ...}` —
   struct literal in upstream. ARCH uses field-by-field assignment
   or a struct-literal expression, depending on what the lowered SV
   needs to look like.

5. **WFI sleep**: `WAIT_SLEEP` → `SLEEP` is a one-cycle hand-off; the
   sleep-exit condition (`irq_nm | irq_pending_i | debug_req_i |
   debug_mode_q | debug_single_step_i`) is sampled in the SLEEP state.
   Tests must verify that asserting any of these in SLEEP triggers
   `ctrl_fsm_ns = FIRST_FETCH`.

## Reference

- Upstream: `~/github/ibex/rtl/ibex_controller.sv` (944 LoC, ~750
  effective under SoC pinning)
- Producer neighbors:
  - `~/github/ibex/rtl/ibex_decoder.sv` (drives `illegal_insn_i`,
    `ecall_insn_i`, `mret_insn_i`, `dret_insn_i`, `wfi_insn_i`,
    `ebrk_insn_i`, `csr_pipe_flush_i`)
  - `~/github/ibex/rtl/ibex_id_stage.sv` (drives `instr_valid_i`,
    `instr_i`, `instr_compressed_i`, `instr_is_compressed_i`,
    `instr_fetch_err_i`, `instr_fetch_err_plus2_i`, `pc_id_i`,
    `branch_set_i`, `jump_set_i`, `stall`, `id_wb_pending`)
  - `~/github/ibex/rtl/ibex_load_store_unit.sv` (drives
    `lsu_store_err_i`, `lsu_load_err_i`)
  - `~/github/ibex/rtl/ibex_cs_registers.sv` (drives `irqs_i`,
    `csr_mstatus_mie_i`, `irq_pending_i`, `nmi_mode_q` resync)
  - Debug interface (drives `debug_req_i`, `debug_single_step_i`,
    `debug_ebreakm_i`, `debug_ebreaku_i`)
- Consumer neighbor:
  - `~/github/ibex/rtl/ibex_id_stage.sv` (samples `pc_set_o`,
    `pc_mux_o`, `exc_pc_mux_o`, `exc_cause_o`, `instr_valid_clear_o`,
    `id_in_ready_o`, `controller_run_o`, `csr_save_*_o`,
    `csr_save_cause_o`, `csr_restore_*_o`, `nt_branch_mispredict_o`)
  - `~/github/ibex/rtl/ibex_if_stage.sv` (samples `instr_req_o`)
  - Top-level (samples `ctrl_busy_o`, `core_busy_o`)
- Pipeline reference: `~/github/ibex/doc/03_reference/pipeline_details.rst`
- Debug reference: `~/github/ibex/doc/03_reference/debug.rst` (if present)
