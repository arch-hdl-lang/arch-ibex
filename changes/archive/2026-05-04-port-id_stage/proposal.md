# Proposal: Port `ibex_id_stage` to ARCH

## Intent

This swap replaces `ibex_id_stage.sv` (1156 LoC upstream) with
`src/IbexIdStage.arch`. `ibex_id_stage` is the instruction-decode /
issue stage — the structural top-level inside `ibex_core` that
instantiates `ibex_decoder` and `ibex_controller`, computes the ALU /
multdiv / CSR / LSU operand muxes, manages branch-set / jump-set
pulses, drives the LSU request handshake, and holds the ID→EX
pipeline registers (`branch_set_q`, `instr_executing_*` regs, the
`id_fsm_q` 2-state stall machine).

This is the **fifth and last Phase B composite swap**. Two of its
sub-instances are already ported: `ibex_decoder` (A4, leaf) and
`ibex_controller` (B4, just merged). After B5 lands, every leaf
under `ibex_core` is in ARCH and Phase C (the `ibex_core` linchpin
swap with `pipeline` + `bus` constructs) becomes the next milestone.

## Scope

**In scope (matches `ibex_top` defaults under `ibex_mini_soc.sv`):**

- `RV32E = 1'b0` — 32-entry GPR file (rs/rd 5-bit address paths).
- `RV32M = RV32MFast` — multdiv enabled; only the `multdiv_en_dec`
  /`mult_en_ex_o`/`div_en_ex_o` paths are exercised.
- `RV32B = RV32BNone` — no bitmanip; bitmanip operand muxing collapses.
- `BranchTargetALU = 1'b0` — branches/jumps go through the regular ALU,
  not a separate BT-ALU. The `g_btalu_muxes` branch is **out**; the
  `g_no_btalu_muxes` branch is the operand-mux path.
- `WritebackStage = 1'b0` — no writeback stage. `ready_wb_i = 1`,
  `rf_write_wb_i = 0`. The `g_no_writeback_stage` branch is what we
  port; bypass logic against WB collapses.
- `BranchPredictor = 1'b0` — `instr_bp_taken_i = 0`,
  `nt_branch_mispredict_o = 0`. Skid / mispredict paths drop out.
- `MemECC = 1'b0` — no integrity-error injection.
- `DataIndTiming = 1'b0` — fixed-time-execution branch-stall path is
  inactive (the `data_ind_timing_i` input is still wired but always 0).
- 2-state ID FSM (`id_fsm_q ∈ {FIRST_CYCLE, MULTI_CYCLE}`), governing
  multi-cycle stalls for LSU / multdiv / branches / `alu_multicycle`.
- ID→EX pipeline regs: `branch_set_q`, `instr_first_cycle_q`, the
  `imd_val_q` intermediate-value regs (multdiv carry / partial sums).
- ALU / branch-target / multdiv / CSR / LSU operand muxes (5 muxes).
- LSU request handshake (`lsu_req_o`, `lsu_*_o` outputs derived from
  decoder), including the `lsu_req_done_i` retire signal.
- Branch-set / jump-set pulse generation (single-cycle PC-redirect
  pulses to the IF stage).
- Register-file read-port wiring (rs1, rs2 addresses) and write-back
  data mux (`rf_wdata_id_mux`).
- `instr_valid_clear_o` / `id_in_ready_o` handshake to IF.
- Sub-module instantiations:
  - `ibex_decoder` (already ported, comes in via `.archi`).
  - `ibex_controller` (already ported, comes in via `.archi`).
- Performance counters: `perf_jump_o`, `perf_branch_o`,
  `perf_tbranch_o`, `perf_dside_wait_o`, `perf_mul_wait_o`,
  `perf_div_wait_o` (counted by the `ibex_counter` instances upstream).

**Out of scope (gated off by SoC pinning):**

- `BranchTargetALU = 1` (`g_btalu_muxes` branch, `bt_a_operand_o` /
  `bt_b_operand_o` separate paths).
- `WritebackStage = 1` (`g_writeback_stage` branch — separate WB
  handshake, WB-bypass mux, WB exception logic).
- `BranchPredictor = 1` (mispredict reporting, branch-not-set path).
- `MemECC = 1` (no `data_intg_err`-driven exception path).
- `DataIndTiming = 1` (fixed-time branch stall — the
  `data_ind_timing_i` input is wired through but kept at 0; we don't
  exercise its branch-stall arm).
- `RV32E = 1` (16-entry GPR — register-address paths still 5-bit;
  upstream just narrows them to 4-bit which we don't model).
- `RV32M = RV32MNone` / `RV32MSlow` (the slow-multdiv handshake; only
  `RV32MFast` is exercised).
- `RV32B != RV32BNone` (bitmanip operand muxing).
- Asserts (`SVA_*` blocks, `ASSERT_KNOWN_*`).

## Construct enumeration

| Construct      | Status | Reason |
|----------------|--------|--------|
| `module`       | **picked** | Outer wrapper. Holds the two sub-`inst` blocks (decoder, controller), the operand-mux comb logic, the ID-EX pipeline regs, and the 2-state stall machine. The id_stage is overwhelmingly structural + combinational; an outer `module` is the natural fit. |
| `fsm`          | **rejected** | The `id_fsm_q ∈ {FIRST_CYCLE, MULTI_CYCLE}` state machine is only 2 states with a single-state-dependent control variable (`stall_*` flags). Modelling it as a top-level `fsm` would force the ~100 lines of *non-state-dependent* combinational logic (operand muxes, RF wdata mux, LSU req gen) into FSM `default`/state bodies, contorting the structure for no gain. A plain `reg id_fsm_q` with a small `comb` block computing `id_fsm_d` mirrors upstream exactly. |
| `thread`       | **rejected** | Same reasoning as B4: this is a reactive controller, not a sequential walker. |
| `pipe_reg`     | **rejected** | The ID-EX boundary regs (`branch_set_q`, `instr_first_cycle_q`) are *not* a pipeline-stage shift register; they're individual flops with module-specific load conditions (`branch_set_d` = `branch_set_raw & ...`). `pipe_reg<T,1>` would model them as a fixed shift, losing the `instr_executing` / `branch_taken` gating. Plain `reg` with `seq on clk_i` is the right fit. |
| `fifo`         | **rejected** | No queueing; ID issues one instruction at a time. |
| `ram` / `cam`  | **N/A** | No address-indexed storage. |
| `linklist`     | **N/A** | No pointer-chained storage. |
| `regfile`      | **N/A** | The GPR file lives in `ibex_register_file_ff` (A2, already ported) — id_stage just connects to its read/write ports. |
| `arbiter`      | **rejected** | No request/grant arbitration in id_stage; multdiv and LSU are mutually exclusive by decoder. |
| `counter`      | **rejected** | `perf_jump_o` / `perf_branch_o` / `perf_*_wait_o` are single-cycle pulse outputs, not running counts; the actual counters live one level up in `ibex_core`. |
| `pipeline`     | **rejected** | Phase C territory. The id_stage is one *stage* of the (eventual) pipeline, not the pipeline itself. |
| `synchronizer` | **N/A** | Single clock domain. |
| `clkgate`      | **N/A** | id_stage drives `instr_first_cycle_id_o` for upstream's clock-gating decisions but doesn't own a gate cell. |

## Approach

**Outer structure:** `module ibex_id_stage` (snake_case for SoC compat),
const params:

```
param RV32E[0:0]:           const = 1'd0;
param RV32M:                const = ibex_pkg::RV32MFast;
param RV32B:                const = ibex_pkg::RV32BNone;
param BranchTargetALU[0:0]: const = 1'd0;
param WritebackStage[0:0]:  const = 1'd0;
param BranchPredictor[0:0]: const = 1'd0;
param DataIndTiming[0:0]:   const = 1'd0;
param MemECC[0:0]:          const = 1'd0;
```

**Sub-module instantiations:**

```
inst decoder_i: ibex_decoder { ... };       // pulls ibex_decoder.archi
inst controller_i: ibex_controller { ... }; // pulls ibex_controller.archi
```

**Latched flops** (async-low reset, all `reg ... reset rst_ni => 0`):

- `id_fsm_q: UInt<1>` — 0 = FIRST_CYCLE, 1 = MULTI_CYCLE
- `branch_set_q: Bool` — branch-set pulse held across the 2-cycle
  branch stall path
- `instr_first_cycle_q: Bool` — high during FIRST_CYCLE only
- `imd_val_q: Vec<UInt<34>, 2>` — multdiv intermediate (carry,
  partial sum)
- `lsu_req_done_q: Bool` (only when WritebackStage=1; under our pins
  this is dropped — see "Out of scope")
- `nt_branch_mispredict_q: Bool` (BranchPredictor=1 only — dropped)

**Comb signals & muxes** (one comb block per concern, mirroring the
upstream block boundaries):

- `alu_operand_a_mux` — selects rs1 / pc_id / zero / fwd from rf_wdata.
- `alu_operand_b_mux` (collapsed under !BranchTargetALU + !RV32B):
  selects rs2 / immediate.
- `immediate_b_mux` — picks among I/S/B/U/J/CSR immediate forms.
- `multdiv_operand_*` — wires rs1/rs2 to the multdiv unit.
- `lsu_req_o` / `lsu_we_o` / `lsu_wdata_o` / `lsu_type_o` /
  `lsu_sign_ext_o` — drives the LSU request from the decoder + rs2.
- `csr_*_o` — wires CSR access signals from the decoder.
- `rf_wdata_id_mux` — picks rf write-back source (alu / lsu / csr).
- `id_in_ready_o`, `instr_valid_clear_o`, `instr_first_cycle_id_o` —
  IF-side handshake.
- `stall_*` aggregator — collects stall sources for the 2-state FSM.
- `id_fsm_d` — next-state computation for the 2-state FSM (FIRST_CYCLE
  ↔ MULTI_CYCLE based on stall_multdiv / stall_branch / stall_jump /
  stall_alu / lsu_req_dec).

**Pipeline register block:**
```
seq on clk_i rising
  if (~rst_ni) { id_fsm_q <= FIRST_CYCLE; branch_set_q <= 0; ... }
  else if (~stall) { id_fsm_q <= id_fsm_d; ... }
end seq
```
mirrors upstream's `id_pipeline_reg` block.

## Verification gate

**Basic gate (blocking):**
```
make build
pytest tests/test_ibex_id_stage_unit.py
pytest tests/test_soc_lint.py
pytest tests/test_cpu_programs.py
```

The unit suite has one cocotb test per spec Requirement (Reqs covering:
plain ALU dispatch, branch-not-taken, branch-taken-stall,
jump-set-pulse, LSU req issue + complete, multdiv stall + retire,
illegal-insn flag forwarding, CSR access path, ID→EX operand muxing,
register-file read addr / wdata routing, FIRST_CYCLE↔MULTI_CYCLE
transitions, instr_valid_clear handshake).

**Full regression (background):**
```
pytest tests/test_ibex_id_stage_unit_full.py
pytest tests/   # everything; archsim_units must still pass
```

**ISR programs** are the integration gate: the same 4-cocotb-program
suite (`timer_isr`, `sw_isr`, `ext_isr`, `multictx_isr`) that gated
B4 must still pass after this swap. They exercise the
controller↔id_stage handshake under real IRQ/MRET timing — exactly
where B4's mepc-off-by-one bug surfaced.

## Verification gate caveats

1. **Two ports come in via `.archi`** (`ibex_decoder.archi` from A4,
   `ibex_controller.archi` from B4). The `arch build` order is leaf
   first, then composites. Build script already handles this for B3
   / B4; same flow applies here.

2. **Operand muxes are dense.** The upstream `alu_operand_a_mux` /
   `immediate_b_mux` are `case`-on-decoder-output ladders with 5–7
   arms each. Under `RV32B = RV32BNone`, the bitmanip arms drop out
   but the remaining muxes are still substantial. The implementer
   should expect ~250 LoC of pure combinational mux code.

3. **`imd_val_q` is `Vec<UInt<34>, 2>`** — the multdiv carry/partial
   pair. This shape worked in IbexExBlock (B1) and IbexMultdivFast
   (A6) under arch-com `main`. Under WritebackStage=0 the
   load-from-WB path drops out, so id_stage just forwards
   `imd_val_d_ex_i` from EX → `imd_val_q_ex_o` next cycle.

4. **`branch_set_q` latch** — branch-set pulses to IF are 1 cycle
   wide, but the 2-cycle branch path (`stall_branch` in the FSM)
   needs the pulse held across the stall. Upstream uses a `branch_set_d
   = branch_set_raw_d | (branch_set_q & branch_in_dec)` self-feeding
   latch. ARCH expresses this naturally as `seq on clk_i; branch_set_q
   <= branch_set_d`.

5. **B4 controller-side rules apply transitively.** id_stage drives
   `controller.instr_valid_i`, which feeds B4's `handle_irq` /
   `clean_dispatch` paths. The `halt_if_decode` and FLUSH-path
   `instr_valid_clear` rules (B4 lessons) are on the controller side;
   id_stage just needs to honor `id_in_ready_o` / `instr_valid_clear_o`
   from the controller correctly.

6. **`icache_inval_o`** — driven from a decoded `fence.i` instruction.
   ICache is off in our SoC (`ICache = 0`), so this output is unwired
   externally. Implementer should still drive it; the SV emit can
   leave the wire dangling.

## Reference

- Upstream: `~/github/ibex/rtl/ibex_id_stage.sv` (1156 LoC, ~700
  effective under SoC pinning).
- Sub-modules already in ARCH: `ibex_decoder.archi` (A4),
  `ibex_controller.archi` (B4).
- Producer neighbors:
  - `ibex_if_stage` (B3, drives `instr_valid_i`, `instr_rdata_i`,
    `pc_id_i`, `instr_fetch_err_*`).
  - `ibex_register_file_ff` (A2, supplies rs1/rs2 read data).
  - `ibex_ex_block` (B1, supplies `ex_valid_i`, `alu_adder_result_ex_i`).
  - `ibex_load_store_unit` (A9, supplies `lsu_resp_valid_i`,
    `lsu_load_err_i`, `lsu_store_err_i`, `lsu_addr_last_i`).
  - `ibex_cs_registers` (upstream, supplies `csr_*` values + IRQ
    state).
- Consumer neighbor: `ibex_core` (instantiates id_stage; forwards its
  outputs to EX, LSU, CSRs, RF write port, IF redirect).
- Spec: `specs/id_stage/spec.md` (to be authored from upstream by the
  spec-extraction agent).
- Construct refs: ARCH HDL spec §2 (`module`), §3.6 (`reg` /
  `seq on clk`), §3.7 (`Vec<T,N>`).
