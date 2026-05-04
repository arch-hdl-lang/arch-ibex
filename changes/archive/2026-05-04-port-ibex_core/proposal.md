# Proposal: Port `ibex_core` to ARCH

## Intent

This swap replaces `ibex_core.sv` (2023 LoC upstream, ~600 LoC effective
under SoC pinning) with `src/IbexCore.arch`. `ibex_core` is the
top-level CPU module: it instantiates the four pipeline-stage
sub-modules (`ibex_if_stage`, `ibex_id_stage`, `ibex_ex_block`,
`ibex_load_store_unit`, `ibex_wb_stage`) plus `ibex_cs_registers` (kept
upstream, see Out-of-scope) and wires their handshakes,
forward/feedback paths, and external memory / IRQ / debug ports.

This is the **first Phase C swap and the demo linchpin of the entire
Ibex-to-ARCH port**. It is the first use of the ARCH `pipeline`
construct on a real CPU, after a successful 2-stage spike at
`~/github/arch-ibex-c1-spike/spike/c1-pipeline/` validated that
pipeline stages can host stateful `inst` sub-modules with proper
stall propagation (per the spike `README.md`, findings 1–4). The
project plan (`~/.claude/projects/-Users-<user>-github-arch-com/memory/project_ibex_arch_plan.md`)
identifies Phase C as "the linchpin" precisely because it unlocks
`pipeline` + cross-module typed buses, turning the hybrid swap-out
into a credible "ARCH expresses CPUs better" artifact rather than a
collection of leaf-level ports.

The `ibex_core` boundary is the SoC's `cpu` instance in
`soc/ibex_mini_soc.sv`; replacing it transparently must keep
`make build && make test` green for all existing SoC-level integration
tests (compliance ISA tests, ISR programs, etc.).

## Scope

**In scope (matches `ibex_top.sv` parameter pins under
`soc/ibex_mini_soc.sv`):**

- `RV32E = 1'b0` — 32-entry RF, full 5-bit `rf_*addr_*` paths
  (lines 87-93 of upstream).
- `RV32M = ibex_pkg::RV32MFast` — multdiv enabled, fast variant
  (line 26).
- `RV32B = ibex_pkg::RV32BNone` — no bitmanip (line 27).
- `BranchTargetALU = 1'b0` — branches/jumps go through the regular
  ALU; `bt_a_operand` / `bt_b_operand` (lines 276-277) are still wired
  through to EX but the ALU absorbs them. The IbexExBlock (B1) port
  already accepts the inactive form.
- `WritebackStage = 1'b0` — `g_no_writeback_stage` paths only.
  IbexWbStage (B2) is **still instantiated**, but in passthrough mode:
  `ready_wb = 1`, `rf_write_wb = 0`, write-back muxing collapses to
  the LSU/ID write-port mux at the WB boundary. No WB-stage register.
- `ICache = 1'b0` — `icache_inval` / `icache_enable` are still wired
  out of CS-Registers and into the IF stage but the IF-stage's ICache
  paths are inert (B3 already gates these).
- `BranchPredictor = 1'b0` — `instr_bp_taken_id`,
  `nt_branch_mispredict`, `nt_branch_addr` paths exist but never
  assert; the ID stage drives them with constants.
- `DbgTriggerEn = 1'b0` — `trigger_match_i` from CS-Registers is
  always 0; the ID stage forwards it through but no debug-trigger
  decoding occurs.
- `MemECC = 1'b0` — `g_no_intg_irq_int` branch only;
  `instr_intg_err = 0`, `lsu_load_resp_intg_err = 0`,
  `lsu_store_resp_intg_err = 0`. `MemDataWidth = 32` (line 48
  collapses).
- `DataIndTiming = 1'b0` — derived from `SecureIbex = 0` at line 179
  upstream; `data_ind_timing` is wired to the EX block but always 0.
- `DummyInstructions = 1'b0` — derived from `SecureIbex = 0`; no LFSR;
  `dummy_instr_id`, `dummy_instr_wb` are tied to 0 from IF and WB
  respectively. The two top-level outputs `dummy_instr_id_o` /
  `dummy_instr_wb_o` (lines 85-86) still exist; both drive constant 0.
- `PMPEnable = 1'b0` — `g_no_pmp` branch (lines 1211-1226). No
  `ibex_pmp` instance; `pmp_req_err[*] = 1'b0`. PMP-related CSR
  outputs (`csr_pmp_*`) are sunk to unused tieoff. `pmp_req_err[PMP_D]`
  in the `data_req_o = data_req_out & ~pmp_req_err[PMP_D]` mask
  (line 772) becomes a no-op.
- `SecureIbex = 1'b0` — non-secure variants of `g_core_busy_*`
  (lines 419-422), `g_instr_req_gated_*` (lines 543-550),
  `g_check_mem_response` (lines 878-892).
- `ResetAll = 1'b0` — async-low reset only on flops with explicit
  reset values; downstream sub-modules already match this.
- `RegFileECC = 1'b0` — `gen_no_regfile_ecc` branch (lines 942-954);
  `rf_wdata_wb_ecc_o = rf_wdata_wb`, `rf_rdata_*_ecc_i` passes
  straight through, `rf_ecc_err_comb = 0`.

**The five sub-module instances inside ibex_core's "real" body:**

| Upstream line | Instance | ARCH port |
|---------------|----------|-----------|
| 428 | `ibex_if_stage if_stage_i` | `IbexIfStage.arch` (B3) |
| 556 | `ibex_id_stage id_stage_i` | `IbexIdStage.arch` (B5) |
| 723 | `ibex_ex_block ex_block_i` | `IbexExBlock.arch` (B1) |
| 775 | `ibex_load_store_unit load_store_unit_i` | `IbexLoadStoreUnit.arch` (A9) |
| 826 | `ibex_wb_stage wb_stage_i` | `IbexWbStage.arch` (B2) |

Plus the upstream-SV `ibex_cs_registers cs_registers_i` (line 1055,
stays SV — see Out-of-scope) and the **non-instance** glue:

- Core-busy mux (line 421): `core_busy_o = (ctrl_busy | if_busy |
  lsu_busy) ? IbexMuBiOn : IbexMuBiOff;` — non-secure form.
- Instruction-request gating (line 548):
  `instr_req_gated = instr_req_int & fetch_enable_i[0]`,
  `instr_exec = fetch_enable_i[0]`.
- LSU-error / RF-write-on-LSU-resp gating (line 880-883, non-secure):
  `lsu_load_err = lsu_load_err_raw; lsu_store_err = lsu_store_err_raw;
  rf_we_lsu = lsu_rdata_valid;`
- LSU data-request masking (line 772):
  `data_req_o = data_req_out & ~pmp_req_err[PMP_D]` → with
  `PMPEnable=0`, `pmp_req_err[PMP_D]=0`, so `data_req_o = data_req_out`.
- LSU-error reduction (line 773):
  `lsu_resp_err = lsu_load_err | lsu_store_err`.
- iSide-wait perf counter (line 528):
  `perf_iside_wait = id_in_ready & ~instr_valid_id`.
- RF-bypass under `gen_no_regfile_ecc` (lines 942-954):
  `rf_wdata_wb_ecc_o = rf_wdata_wb; rf_rdata_a = rf_rdata_a_ecc_i;
  rf_rdata_b = rf_rdata_b_ecc_i; rf_ecc_err_comb = 0;` — plus the
  three `unused_*` sinks for `rf_ren_*` / `rf_rd_*_wb_match`.
- Crash-dump aggregation (lines 961-965):
  `crash_dump_o.{current_pc, next_pc, last_data_addr, exception_pc,
  exception_addr}`.
- Alert outputs (lines 972-977):
  `alert_minor_o = icache_ecc_error;
   alert_major_internal_o = rf_ecc_err_comb | pc_mismatch_alert |
                            csr_shadow_err;
   alert_major_bus_o = lsu_load_resp_intg_err |
                       lsu_store_resp_intg_err | instr_intg_err;`
   (under our pins reduces substantially — `rf_ecc_err_comb=0`,
   `csr_shadow_err`/`pc_mismatch_alert` come from CSRs/IF, all three
   intg_err = 0.)
- Tie-throughs / unused sinks for `RV32E` etc. (`unused_*` signals).

## Out of scope

- **`ibex_cs_registers`** stays upstream SV. Per the project plan
  (`project_ibex_arch_plan.md`), `rdl2arch-riscv` generates the CSR
  file via fork-with-same-name; the rdl→ARCH plumbing is its own
  workstream and is not part of C1. ibex_core instantiates
  `ibex_cs_registers` as an upstream-SV black box from inside an
  ARCH module / pipeline. **This is a known novel integration point —
  see Risks §3.**
- **`ibex_pmp`** — out of scope (deferred to Phase D). The `g_no_pmp`
  branch (lines 1211-1226) is what we model; no `pmp_i` instance.
- **`ibex_lockstep` / `SecureIbex` shadowing** — out of scope (Phase
  D). All `if (SecureIbex)` branches resolve to the `g_*_non_secure`
  / `g_no_*` form.
- **Lockstep `ibex_dummy_instr` LFSR** (`DummyInstructions=0`).
- **Any RVFI tracking pipeline** (lines 1228 onward, ~700 LoC,
  guarded by `` `ifdef RVFI ``). Not synthesized in our flow;
  `RVFI` is never defined in the SoC build.
- **`` `ifdef INC_ASSERT `` block** (lines 980-1047): SVA assertions
  (`NoMemRFWriteWithoutPendingLoad`, `NoMemResponseWithoutPendingAccess`,
  `NoExecWhenFetchEnableNotOn`) — sim-only; not synthesizable; ARCH
  doesn't model SVAs in this proposal.
- **`` `ASSERT_INIT ``** macro calls (lines 533-534) and module-level
  `` `ASSERT `` (lines 1168-1174) — same reason.
- **`csr_wdata` write-port aliasing** (line 1053) is in scope:
  `csr_wdata = alu_operand_a_ex` is a single-line assign that lives
  outside the cs_registers instance and feeds it. Trivially re-emitted
  in ARCH.

## Construct enumeration

Required per `feedback_proposal_construct_enumeration.md`. One row per
ARCH first-class construct (per arch-com `ARCH_HDL_Specification.md`
§8-§12 + `pipeline`).

| Construct           | Status | Reason |
|---------------------|--------|--------|
| `module`            | **picked (secondary)** | Used for the **outer file scope** wrapping the `pipeline`, and used inside the SV `ibex_core` boundary at the few places where the structure isn't pipeline-shaped (e.g. the `core_busy_o` reduction, the alert-output OR-tree, the crash-dump struct assembly, the `instr_req_gated` AND-gate). These collapse into module-scope `comb` blocks alongside the pipeline. |
| `pipeline`          | **picked (primary)** | The **demo linchpin choice**. The 4-stage Ibex pipeline (IF / ID / EX / WB) maps onto an ARCH `pipeline` with one stage per architectural stage (see Stage decomposition §). Validated by the C1 spike (`spike/c1-pipeline/README.md`, findings 1-4): pipeline stages can host stateful `inst` sub-modules; stall propagation is automatic via `wait until <inst.busy_signal>`; flush composes via explicit `sub.flush_i <- flush_in` wiring; user-state regs need framework-`valid_r` gating. The fallback option (plain `module` with hand-rolled hazard logic, per `project_ibex_arch_plan.md` line 24) is **rejected** in favor of `pipeline` because the spike de-risked the choice. |
| `inst`              | **picked (heavily)** | Each of the 5 sub-modules in scope is instantiated with `inst <name>: <Module> { ... };`. This is the workhorse construct for C1: `if_stage_i`, `id_stage_i`, `ex_block_i`, `load_store_unit_i`, `wb_stage_i`. Plus `cs_registers_i` as an upstream-SV inst — see Risks §3 for whether arch-com supports SV-from-pipeline-stage inst. |
| `fsm`               | **rejected** | All FSM-shaped logic that ibex_core orchestrates already lives **inside** the already-ported sub-modules: the controller FSM is in `IbexIdStage.controller_i` (B4); the LSU 2-state walker is in `IbexLoadStoreUnit` (A9); the multdiv FSM is in `IbexExBlock.multdiv_i` (A6). At the `ibex_core` level, the only "state" outside sub-modules is the imd_val_q_ex pipeline registers between EX and ID (line 203), which are plain flops with bit-vector load enables (`imd_val_we_ex`), not a state machine. |
| `thread`            | **rejected** | Per `feedback_thread_single_state_idiom`, `thread` is for `do { ... } until cond;` walkers. ibex_core has no such walker at the top level — every cycle, every output is a function of the current cycle's inputs/sub-module outputs (a reactive structure, not sequential). |
| `pipe_reg`          | **rejected** | The two ID↔EX cross-stage registers (`imd_val_d_ex` / `imd_val_q_ex`) are NOT a fixed-shift pipeline register: they have an explicit `imd_val_we_ex[2]` write-enable per element, and live inside the ID stage (the existing IbexIdStage.arch already declares them — ibex_core only routes `imd_val_d_ex` / `imd_val_we_ex` from EX → ID and `imd_val_q_ex` from ID → EX). At the ibex_core level these are pure wires, not flops. |
| `fifo`              | **rejected** | No queueing at the ibex_core level. The IF stage's prefetch FIFO is internal to `IbexIfStage` (A7 IbexFetchFifo + A8 IbexPrefetchBuffer). |
| `ram`               | **N/A** | No address-indexed storage at this scope (the I-cache RAMs are external to ibex_core and pinned out via `ic_tag_*` / `ic_data_*` ports — they live in the SoC, not here). |
| `cam`               | **N/A** | No content-addressable lookup. |
| `linklist`          | **N/A** | No pointer-chained storage. |
| `regfile`           | **rejected (do NOT re-pick)** | The GPR file is `IbexRegisterFileFf` (A2, already ported), instantiated **outside** ibex_core in `ibex_top` and pinned through ibex_core's `rf_*` ports (lines 87-93). ibex_core has nothing to do with the regfile primitive itself; it just routes read/write ports between IF/ID/EX/LSU/WB sub-modules and the external instance. |
| `arbiter`           | **rejected** | No request/grant arbitration at ibex_core scope. The LSU vs IF request channels are separate external memory ports (`data_*` and `instr_*`), not arbitrated internally. |
| `bus`               | **assess → rejected for C1** | Tempting to lift the LSU req/resp shape into a `bus` typedef (`bus LsuReq { we; type; wdata; sign_ext; }`) and the IF-stage instr-fetch shape into another. **Decided against** for C1: doing so requires re-cutting the already-merged ports of `IbexLoadStoreUnit.arch` (A9), `IbexIdStage.arch` (B5), and `IbexIfStage.arch` (B3) — substantial rework that pulls those sub-modules back into scope. C1's value is the `pipeline` demonstration; `bus` typedefs are a follow-on refactor that can land separately without changing observable behavior. **Documented as a future swap** rather than blocking C1. |
| `handshake_channel` | **assess → rejected for C1** | Same reasoning as `bus`: the IF↔ID instr-fetch path (`instr_valid_id`, `instr_rdata_id`, `id_in_ready`, `instr_valid_clear`) and the LSU req/done path (`lsu_req`, `lsu_req_done`, `lsu_resp_valid`) are textbook handshake-channel candidates, but lifting them now requires re-port-ing already-merged sub-modules. Defer to a post-C1 cleanup. |
| `synchronizer`      | **N/A** | Single clock domain (`clk_i`); no CDC. |
| `clkgate`           | **N/A** | The clock-gating decision (driven by `core_busy_o`) lives in `ibex_top`, not in `ibex_core`. ibex_core just *exports* `core_busy_o`. |
| `counter`           | **rejected** | The performance-counter wires (`perf_jump`, `perf_branch`, `perf_load`, `perf_store`, `perf_*_wait`, `perf_iside_wait`) are single-cycle pulses produced by the sub-modules and routed into `ibex_cs_registers`'s `instr_ret_*_i` / `*_wait_i` ports, where the actual counters (`ibex_counter` instances, A3) live. ibex_core just routes these wires; no counter primitive at this scope. |

## Stage decomposition

The proposed mapping of the 4 architectural stages onto ARCH `pipeline`
stages:

```
pipeline IbexCore on clk_i, rst_ni
  stage IF
    inst if_stage_i: IbexIfStage { ... };
    // wait until: IF stage is "ready" once instr_valid_id_o asserts
    // OR if the instr stream is bus-faulted; the framework auto-stalls
    // upstream when this stage's "done" condition isn't met.
    wait until if_stage_i.instr_valid_id_o or if_stage_i.instr_fetch_err_o;
  end stage IF

  stage ID
    inst id_stage_i: IbexIdStage { ... };
    // ID is variable-latency: stalls on multdiv (id_fsm_q ==
    // MULTI_CYCLE), LSU req-not-done, branch-stall, jump-stall.
    // The IbexIdStage already exposes `id_in_ready_o` which is high
    // when ID is willing to accept a new instruction. We stall the
    // pipeline framework on its negation.
    wait until id_stage_i.id_in_ready_o;
  end stage ID

  stage EX
    inst ex_block_i: IbexExBlock { ... };
    // EX is variable-latency for multdiv (multi-cycle multiply,
    // 32+ cycle divide). EX exposes `ex_valid_o`; the framework
    // auto-derives capture_stall from this.
    wait until ex_block_i.ex_valid_o;
  end stage EX

  stage WB
    inst wb_stage_i: IbexWbStage { ... };
    inst load_store_unit_i: IbexLoadStoreUnit { ... };
    // LSU response can be variable-latency for misaligned accesses
    // (2 bus transactions). Wait on lsu_resp_valid_o for loads;
    // for ALU-only retires, ready_wb_o is the gate.
    wait until wb_stage_i.ready_wb_o and
               (not load_store_unit_i.busy_o or load_store_unit_i.lsu_resp_valid_o);
  end stage WB
end pipeline
```

**Why this shape (and the alternatives considered):**

1. **EX vs WB placement of `IbexLoadStoreUnit`**: the LSU is logically
   in EX (it consumes `alu_adder_result_ex` from line 759 in the same
   cycle EX produces it) but its **response** lands in WB
   (`lsu_resp_valid` → `rf_we_lsu` → `wb_stage_i.lsu_resp_valid_i` at
   line 866). With `WritebackStage=0` the WB stage is passthrough, so
   either placement works structurally. **Decision: instantiate LSU
   inside `stage WB`** because (a) the LSU's response-side ports
   dominate its interface fan-out, and (b) it makes the wait condition
   on WB cleaner (LSU done-or-idle gates WB completion). The LSU
   request-side inputs (`lsu_we`, `lsu_type`, `lsu_wdata`) come from
   ID via cross-stage references (`stage ID.id_stage_i.lsu_we_o`).
   The `alu_adder_result_ex` → LSU `adder_result_ex_i` reference is a
   same-cycle EX→WB combinational path; the spike confirmed this
   shape is valid (`stage Process` reading `Capture.data_r`).

2. **Cross-stage references** follow the cpu_pipeline.arch idiom from
   the spike: `stage <Stage>.<inst>.<port>` reads outputs of a
   sub-module instance in another stage. Examples needed for C1:
   - `stage IF.if_stage_i.instr_valid_id_o` → `stage ID.id_stage_i.instr_valid_i`
   - `stage ID.id_stage_i.alu_operator_ex_o` → `stage EX.ex_block_i.alu_operator_i`
   - `stage EX.ex_block_i.alu_adder_result_ex_o` → `stage WB.load_store_unit_i.adder_result_ex_i`
   - `stage WB.load_store_unit_i.lsu_resp_valid_o` → `stage ID.id_stage_i.lsu_resp_valid_i` (feedback!)

3. **Same-stage placement of WB + LSU**: both go into `stage WB`. They
   share the LSU response (`lsu_resp_valid`, `rf_we_lsu`, `rf_wdata_lsu`)
   and the `dummy_instr_id`/`pc_id` inputs, so colocating them avoids
   an extra inter-stage hop. The framework treats them as a single
   stage's body with two `inst` blocks; this is the same shape as
   the spike's `stage Process` (one `inst worker`) generalized to
   N-inst.

4. **`ibex_cs_registers` placement** — see Risks §3. Either (a)
   instantiate inside `stage ID` (it's mostly read by ID via
   `csr_rdata`, `irqs`, `csr_mstatus_*`, `priv_mode_id`), or (b)
   instantiate at module scope **outside** the pipeline if arch-com
   doesn't support SV-from-pipeline-stage inst. Decision deferred to
   the spec extractor, who should test (a) first.

5. **Flush wiring** (per spike finding #3, requires explicit user
   wiring): the upstream-SV ibex_core has *implicit* flush — there is
   no top-level `flush_i` driven into the sub-modules. Each
   sub-module's flush behavior is internal:
   - `IbexIdStage.controller_i` (B4) generates `instr_valid_clear_o`
     and `pc_set_o` itself; ID flushes IF by asserting
     `instr_valid_clear_o`.
   - `IbexIfStage` (B3) acts on `instr_valid_clear_i` and `pc_set_i`
     to clear its prefetch buffer.
   - `IbexExBlock`, `IbexLoadStoreUnit`, `IbexWbStage` have no
     external flush input under our pins.

   **Therefore the C1 pipeline does NOT need user-wired
   `sub.flush_i <- flush_in` connections** — the existing controller
   already does flush via `pc_set` + `instr_valid_clear`. The
   pipeline framework's `flush Stage when ...` clause should likely
   be omitted entirely, with all flush behavior coming from the
   sub-module-internal logic. **This is a divergence from the spike
   shape** (the spike's `Process.flush_i <- flush_in` was needed
   because `WorkUnit` had no other flush path) and is worth flagging
   to the implementer.

## Hazard handling

Under our pins, the live hazards are reduced compared to the full
Ibex matrix. Each is sourced from a specific sub-module's logic
(already ported); ibex_core just composes them.

| Hazard | Source | C1 disposition |
|--------|--------|----------------|
| **Branch flush** (taken branch in EX redirects PC) | `IbexExBlock.branch_decision_o` (line 763) → `IbexIdStage.branch_decision_i` (line 582) → `IbexIdStage.controller_i` asserts `pc_set_o` and `instr_valid_clear_o` (B4) | Handled entirely within the existing sub-modules. ibex_core just wires `branch_target_ex` (line 762) into IF's `branch_target_ex_i` (line 510). No top-level flush needed. |
| **Multdiv stall** (multi-cycle MUL/DIV) | `IbexExBlock.multdiv_i` keeps `ex_valid_o = 0` until done (A6) | Pipeline framework stalls EX stage on `wait until ex_valid_o`. Stall ripples back to ID via `capture_stall` (spike finding #2). The id_fsm_q's MULTI_CYCLE state handles the ID-side stall holding. |
| **LSU stall** (load/store waits for bus) | `IbexLoadStoreUnit.lsu_req_done_o` (line 804) and `lsu_resp_valid_o` (line 812) | ID's `lsu_req_dec` keeps `id_in_ready_o = 0` until `lsu_req_done_i` asserts (B5 IbexIdStage internal). For misaligned 2-beat accesses, LSU keeps `busy_o = 1` across both beats. Stage WB stalls on `wait until ... lsu_resp_valid_o`. |
| **Debug halt** (debug_req → DBG_TAKEN_IF) | `IbexIdStage.controller_i` enters DBG_TAKEN_IF state (B4); asserts `pc_set_o` to redirect to DM halt addr; `csr_save_*` saves to `dpc` | Handled in the controller. ibex_core just routes `debug_req_i` (line 118) → ID `debug_req_i` (line 677) and `debug_mode` (line 361) → CSRs `debug_mode_i` (line 1117). |
| **Exception** (illegal insn, mem fault, ecall, ebreak) | Decoder + LSU drive flag lines (`lsu_load_err`, `lsu_store_err`, `illegal_insn_id`, etc.) → controller's exception priority encoder (B4) | Same as above; controller handles it. ibex_core wires `lsu_load_err_raw` / `lsu_store_err_raw` (lines 815-817) through the `g_no_check_mem_response` aliases (line 880) into the controller's latched `_q` regs. |
| **Interrupt** (timer / sw / ext / fast / NMI) | CSRs aggregate IRQs into `irqs` / `irq_pending_o` / `nmi_mode` (lines 1098-1104) → controller IRQ_TAKEN state | Routed via `irqs_i`, `csr_mstatus_mie_i`, `irq_pending_i`, `nmi_mode_o` between CSRs and ID (lines 666-670). NMI / fast-IRQ priority resolution lives in the controller. |
| **Instr fetch error** | IF-stage drives `instr_fetch_err_o` / `instr_fetch_err_plus2_o` (lines 485-486) | Routed to ID's `instr_fetch_err_i` (line 598); controller treats it as an exception. |
| **WFI sleep** | controller WAIT_SLEEP → SLEEP states; `ctrl_busy = 0` lets `core_busy_o` deassert | `ctrl_busy_o` from ID (line 570) feeds `core_busy_o` reduction (line 421). Sleep wakeup is from `irq_*` / `debug_req_i`. |
| **WB-stage exception** (load fault retired late) | `WritebackStage = 0` ⇒ N/A. The `wb_exception_o` path is dropped entirely. | Out of scope. |
| **Branch-predictor mispredict** | `BranchPredictor = 0` ⇒ N/A. `nt_branch_mispredict` is always 0 from ID. | Out of scope. |

**Net effect**: C1 doesn't need to author any new hazard logic. It
needs to (a) wire the existing sub-module hazard outputs to their
correct sub-module inputs, and (b) translate "framework stalls" into
the right `wait until` conditions per stage so the pipeline framework's
`capture_stall` rippling matches what the upstream-SV's implicit
back-pressure does.

## Approach

**File layout:**

```
src/IbexCore.arch                  // outer pipeline + non-pipeline glue
src/IbexCoreSharedPkg.arch         // (already exists from B5; reused)
build/ibex_core.sv                 // emitted SV; SoC-compat snake_case basename
```

**Outer wrapper:** `pipeline IbexCore` at file scope (top), per the
spike's `SpikePipe.arch` shape. The name is `IbexCore` (CamelCase) in
the .arch file; emission target is `build/ibex_core.sv` per
build.sh's CamelCase→snake convention.

**Const params** (matches ibex_top defaults under SoC pinning):
```
param RV32E[0:0]:           const = 1'd0;
param RV32M:                const = ibex_pkg::RV32MFast;
param RV32B:                const = ibex_pkg::RV32BNone;
param BranchTargetALU[0:0]: const = 1'd0;
param WritebackStage[0:0]:  const = 1'd0;
param ICache[0:0]:          const = 1'd0;
param BranchPredictor[0:0]: const = 1'd0;
param DbgTriggerEn[0:0]:    const = 1'd0;
param MemECC[0:0]:          const = 1'd0;
param DataIndTiming[0:0]:   const = 1'd0;
param DummyInstructions[0:0]: const = 1'd0;
param PMPEnable[0:0]:       const = 1'd0;
param SecureIbex[0:0]:      const = 1'd0;
param ResetAll[0:0]:        const = 1'd0;
param RegFileECC[0:0]:      const = 1'd0;
// scalars passed through to sub-modules:
param DmHaltAddr:      const = 32'h1A110800;
param DmExceptionAddr: const = 32'h1A110808;
param MHPMCounterNum:  const = 0;
param MHPMCounterWidth: const = 40;
param BusSizeECC:      const = 32;       // BUS_SIZE
// (others as per ibex_top.sv defaults)
```
**Use the `[0:0]: const = 1'd0` form** for boolean params per
`feedback_arch_syntax_pitfalls` rule #12 (avoids WIDTHTRUNC on
ternary use).

**Ports**: 1:1 mirror of `ibex_core`'s upstream port list (lines
57-175), excluding the `` `ifdef RVFI `` block. Port directions /
widths must match exactly so the SoC's `cpu` instance binds without
diff. Vec ports that interop with upstream-SV's `logic [W-1:0] x [N]`
shape (e.g. `csr_pmp_addr` at line 341, `ic_tag_rdata_i` at line 100)
need the `unpacked` modifier per `feedback_arch_syntax_pitfalls` rule
#5. Under PMPEnable=0 the PMP-related Vec ports are sunk
to unused; they still need the right shape for SoC binding.

**Pipeline body** (sketch — see Stage decomposition for full shape):
```
pipeline IbexCore on clk_i, rst_ni
  stage IF   { inst if_stage_i: IbexIfStage   { ... }; wait until ...; }
  stage ID   { inst id_stage_i: IbexIdStage   { ... }; wait until ...; }
  stage EX   { inst ex_block_i: IbexExBlock   { ... }; wait until ...; }
  stage WB   {
    inst wb_stage_i:        IbexWbStage      { ... };
    inst load_store_unit_i: IbexLoadStoreUnit { ... };
    wait until ...;
  }
end pipeline
```

**Module-scope (non-pipeline) glue** — declared at the IbexCore
file scope alongside the pipeline (this is the part where `module`
semantics surface even though the outer is `pipeline`):

- `inst cs_registers_i: ibex_cs_registers { ... };` — upstream-SV
  inst at module scope (or inside `stage ID`; see Risks §3).
- `comb { core_busy_o = (ctrl_busy_w | if_busy_w | lsu_busy_w) ?
  IbexMuBiOn : IbexMuBiOff; }`
- `comb { instr_req_gated = instr_req_int & fetch_enable_i[0];
         instr_exec = fetch_enable_i[0]; }`
- `comb { data_req_o = data_req_out;  // PMPEnable=0
         lsu_load_err = lsu_load_err_raw;
         lsu_store_err = lsu_store_err_raw;
         rf_we_lsu = lsu_rdata_valid;
         lsu_resp_err = lsu_load_err | lsu_store_err; }`
- `comb { rf_wdata_wb_ecc_o = rf_wdata_wb;
         rf_rdata_a = rf_rdata_a_ecc_i;
         rf_rdata_b = rf_rdata_b_ecc_i;
         rf_ecc_err_comb = false; }`  // gen_no_regfile_ecc
- `comb { perf_iside_wait = id_in_ready & ~instr_valid_id; }`
- crash-dump struct field assigns (5 fields)
- alert-output OR-trees (3 outputs)
- the `dummy_instr_*_o`, `unused_*` tieoffs.

How "module-scope at file scope alongside `pipeline`" composes is the
spike's open question — the spike only had a `pipeline` and nothing
else at file scope. **See Risks §4.**

## Risks / open questions

1. **Does IbexIdStage's internal id_fsm_q (FIRST_CYCLE / MULTI_CYCLE)
   conflict with the pipeline framework's wait-FSM?**
   The spike's `WorkUnit` had a 4-state FSM (Idle/S1/S2/Done) with
   `done_o` as the wait condition; that worked. IbexIdStage's id_fsm_q
   is 2-state with `id_in_ready_o` as the equivalent "I'm done with
   the current instruction" signal. **Likely fine** — the wait-FSM
   only watches the named output, it doesn't care about the
   sub-module's internal state count. But if id_fsm_q transitions on
   the same cycle id_in_ready_o asserts (which it does on
   MULTI_CYCLE→FIRST_CYCLE), the framework needs to capture the
   "done" pulse correctly — i.e. accept the next instruction the
   following cycle, not the same cycle. Worth flagging to the
   implementer to verify with a single-multdiv-instruction directed
   test in the basic gate.

2. **EX↔ID feedback loop via `imd_val_q_ex` / `imd_val_d_ex` /
   `imd_val_we_ex`.** This is the multdiv intermediate-state
   feedback: EX produces `imd_val_d_ex` + `imd_val_we_ex`, ID stores
   them into `imd_val_q_ex` regs, ID feeds them back to EX next
   cycle. With `IbexIdStage` in `stage ID` and `IbexExBlock` in
   `stage EX`, this is a cross-stage backward-feedback loop —
   **EX (later stage) drives a value used by ID (earlier stage).**
   The pipeline framework's data flow is forward; backward references
   to `stage EX.ex_block_i.imd_val_d_o` from inside `stage ID` body
   are syntactically possible per the spike but need verification
   that they don't trigger a "backward dependency" lint. The
   `imd_val_q_ex` regs themselves live inside IbexIdStage (port
   `imd_val_q_ex_o`), so the actual flop is in ID; EX just reads
   `imd_val_q_i` and writes `imd_val_d_o` combinationally. This is
   the **most likely-to-bite pipeline integration point**, and the
   reason the spike was scoped to a forward-only data path.

3. **Can arch-com instantiate an upstream-SV module from inside an
   ARCH `pipeline` stage?** The spike only tested ARCH-on-ARCH
   `inst`. Two sub-questions:

   a. **`inst cs_registers_i: ibex_cs_registers { ... }` inside
      `stage ID`** — does the parser accept SV instances in stage
      bodies the same way it accepts ARCH instances? The parser line
      cited in the spike (`src/parser.rs` line 3687) accepts `inst`
      as a stage body item, but the lowering may differ for SV
      instances (no `*_busy_o` to derive `process_fsm_busy` from, no
      `process_*_in/out` connection synthesis).

   b. **Or instantiate `cs_registers_i` at module scope outside the
      pipeline.** This is structurally simpler but introduces
      ID↔CSRs combinational paths that cross the pipeline boundary
      (`csr_addr` from ID stage → CSR rdata back into ID), which the
      framework may not model cleanly.

   **Action**: spec extractor should test (a) first via a 5-line
   smoke build before committing the full pipeline shape. If (a)
   fails, fall back to (b) and document the cross-boundary path.
   If both fail, the **escape hatch** is to fall back to plain
   `module` for the entire ibex_core (per `project_ibex_arch_plan`
   line 24) — but this kills the C1 demo value, so it's a
   last-resort.

4. **Module-scope `comb` / `inst` blocks alongside a `pipeline` at
   file scope** — does arch-com support this? The spike's
   `SpikePipe.arch` had only the pipeline; everything else was
   inside stages. C1 needs (a) the non-pipeline glue listed in
   Approach (~10 `comb` blocks), (b) potentially the cs_registers
   inst, (c) pipeline ports at the file scope. The expectation is
   that `pipeline` is a top-level item just like `module` and can
   coexist with module-scope `comb`, but this isn't proven.

   **Action**: implementer should write a 20-line smoke test
   (`pipeline { stage A {} stage B {} } comb { x = y; }`) before
   the full IbexCore body, to confirm the file-scope layout is
   accepted.

5. **`imd_val_q_ex` / `imd_val_d_ex` packed-vs-unpacked.** Per
   `feedback_arch_syntax_pitfalls` rule #5 + the B1 lesson (B1
   flipped these to packed-both-sides for ARCH↔ARCH paths), both
   IbexExBlock and IbexIdStage now expose these ports as packed Vec.
   **Inside the C1 pipeline both sides are still ARCH↔ARCH**, just
   wired across stages instead of directly. The packed-Vec port
   shape must propagate through the cross-stage reference unchanged.
   No new conversion expected, but worth verifying in the smoke
   build.

6. **Performance counter wiring (10+ wires) + RVFI-only signals.**
   The perf counters (`perf_jump`, `perf_branch`, ..., 10 wires) are
   straight pass-throughs from sub-modules to CSRs. RVFI signals
   (lines 1228+) are not in scope. The implementer should resist any
   urge to "model" RVFI; just emit the per-signal mapping without
   the RVFI tracking flops.

7. **Snake_case file basename** — `build/ibex_core.sv` is required
   by SoC binding (mini_soc.sv binds to `ibex_core` not `IbexCore`).
   `scripts/build.sh` already does the conversion. The .arch source
   is `IbexCore.arch` per existing convention. Per
   `feedback_shared_types_package` (B5 lesson), don't snake-case
   the .arch filename to match upstream — keep CamelCase for ARCH
   sources, let the build script handle SV emission naming.

8. **Verilator preprocessor:** per `feedback_avoid_verilator_in_comments`
   (B2 lesson), `///` doc comments must not contain the literal word
   `Verilator`. Use lowercase `verilator` or `the simulator`.

9. **`use Pkg;` placement**: per `feedback_arch_syntax_pitfalls` rule
   #14, `use IbexPkg;` and `use IbexCoreSharedPkg;` (or whatever
   shared types are needed for `pc_sel_e`, `exc_pc_sel_e`,
   `exc_cause_t`, `alu_op_e`, `md_op_e`, `csr_op_e`, `csr_num_e`,
   `wb_instr_type_e`, `priv_lvl_e`, `dbg_cause_e`, `irqs_t`,
   `crash_dump_t`, `ibex_mubi_t`, `pmp_*_t`, `instr_exp_e`) must go
   at file scope BEFORE the pipeline declaration.

## Verification gate

**Basic gate (blocking, must pass before READY.md):**

```
rm -rf build/
make build
pytest tests/test_ibex_core_unit.py
pytest tests/test_soc_lint.py
pytest tests/test_cpu_programs.py
```

The unit suite (`test_ibex_core_unit.py`) has one cocotb test per
spec Requirement. Per the spec-first methodology
(`feedback_spec_first_arch_blind`), the spec extractor will define
Reqs covering at minimum:

- IF→ID handshake (instr_valid → id_in_ready transition)
- ID→EX dispatch (alu_op / multdiv_op / lsu_req propagation)
- EX→WB / LSU response retire
- branch-taken pipeline redirect (single-cycle pc_set pulse)
- multdiv stall propagation (EX stalls; ID holds; IF stalls)
- LSU stall propagation (WB stalls; ID holds; IF stalls)
- IRQ entry (NMI / external / fast / sw / timer priority)
- debug entry (debug_req → DBG_TAKEN_IF)
- exception entry (illegal insn, fetch err, mem err, ecall, ebreak)
- WFI → sleep → wake on IRQ
- core_busy_o reduction (any of ctrl_busy / if_busy / lsu_busy)
- crash_dump_o composition
- alert_*_o reduction
- imd_val_q_ex EX↔ID feedback (multdiv intermediate state)
- mret / dret return paths (csr_restore_*_id)

**Full SoC regression (blocking; per
`feedback_full_gate_before_ready`):**

```
rm -rf build/
make build
make test       # full SoC gate, all archived ISR programs + sanity
```

Per `feedback_full_gate_before_ready` (B1 lesson), this **must run
on a clean build/ tree** to avoid stale artifacts masking broken
edits — `make build` short-circuits on first error, so a leftover
`build/ibex_core.sv` from a prior good run can mask a current break.

The 4 ISR programs from B4 (`timer_isr`, `sw_isr`, `ext_isr`,
`multictx_isr`) are the integration-level gate that caught both
B4-controller bugs that unit tests missed
(`feedback_controller_isr_gap_lessons`). They MUST still pass after
the C1 swap; if they fail, treat as a regression even if the
unit suite is green.

**Parallel runner** (per `feedback_parallel_pytest`):
```
pytest -n auto --dist=loadfile tests/
```

**Phase C end-gate (deferred follow-on, NOT blocking C1)**: per
`project_ibex_arch_plan.md`, Phase C end-gate adds **riscv-arch-tests
RV32IMC compliance**. C1 itself targets only the standard SoC gate
above. Compliance test integration is a separate workstream
(test infrastructure work, not C1 IbexCore work).

## Verification gate caveats

1. **CSRs stay upstream-SV.** The build flow needs to copy
   `~/github/ibex/rtl/ibex_cs_registers.sv` (and any vendor'd `prim_*`
   it depends on) into the build tree alongside `build/ibex_core.sv`.
   If the build script's "ARCH-only" path doesn't already do this,
   it needs adjustment. (Check `scripts/build.sh`.)

2. **CSR-feedback-loop timing.** `csr_rdata` (CSR output, line 1095)
   is consumed combinationally by ID's CSR-write-back mux
   (`rf_wdata_id_mux` selects `csr_rdata_i` when the instruction is
   a CSR read). With CSRs at module scope and ID inside `stage ID`,
   this is a same-cycle pipeline↔non-pipeline combinational path.
   Verify this composes (Risks §3b).

3. **All `ibex_*` Vec ports that connect upstream→ARCH or ARCH→
   upstream need the `unpacked` modifier** per the rule. Specifically:
   - `csr_pmp_addr`, `csr_pmp_cfg`, `csr_pmp_mseccfg` (CSRs side, but
     unused under PMPEnable=0)
   - `ic_tag_rdata_i`, `ic_data_rdata_i`, `ic_tag_req_o`,
     `ic_data_req_o` (SoC side; ICache=0 ties them off but the port
     shape still binds)
   - `irq_fast_i [14:0]` is packed (single 15-bit), no `unpacked`
     needed
   - `imd_val_q_ex` / `imd_val_d_ex` are packed both sides per B1
     (Risks §5)

4. **`crash_dump_o` is a struct typedef** (`crash_dump_t`); ARCH
   struct-literal field assigns from
   `feedback_arch_syntax_pitfalls` (the B4 controller had the same
   pattern with `exc_cause_t`). Field-by-field assigns are the
   standard form.

5. **`SecureIbex` localparam derivations** — `DataIndTiming`,
   `PCIncrCheck` are `localparam bit` derived from `SecureIbex`
   (lines 179-180). Under our pin (`SecureIbex=0`), both are 0.
   ARCH should declare them as `let` constants or fold them at the
   sub-module port:
   `data_ind_timing_i: 1'd0`, `pc_incr_check_i: 1'd0`.

6. **`lsu_resp_err` reduction (line 773)** is a 2-input OR; not
   worth a named signal in ARCH if the consumer reads
   `lsu_load_err | lsu_store_err` directly. Keep the named wire to
   match upstream-SV variable visibility (helps waveform debug).

7. **`fetch_enable_i` is `ibex_mubi_t` (4-bit mubi)**; under
   non-secure (`SecureIbex=0`), only bit 0 is used (line 549). The
   `unused_fetch_enable = ^fetch_enable_i[3:1]` lint sink (line 546)
   needs an ARCH equivalent (or arch-com's lint can be configured to
   ignore high-3-bits-unused on this port).

## Reference

- **Upstream**: `~/github/ibex/rtl/ibex_core.sv` (2023 LoC; ~600
  effective under SoC pinning, after subtracting the
  `` `ifdef RVFI `` block (~700 LoC), the
  `` `ifdef INC_ASSERT `` block (~70 LoC), the `g_*_secure` /
  `g_pmp` / `gen_regfile_ecc` / `g_check_mem_response` /
  `g_intg_irq_int` branches.)

- **Spike validating `pipeline` choice**:
  `~/github/arch-ibex-c1-spike/spike/c1-pipeline/README.md`
  (3 cocotb tests; findings 1-4 reproduced above).
  - `WorkUnit.arch` — stateful sub-module shape model.
  - `SpikePipe.arch` — 3-stage pipeline with `inst` in stage body.
  - arch-com PR #282 (merged 2026-05-04) — wait-FSM lowering fix
    surfaced by the spike.

- **Sub-modules already in ARCH** (instantiated by C1):
  - `src/IbexIfStage.arch` (B3, archived
    `changes/archive/2026-05-03-port-if_stage/`)
  - `src/IbexIdStage.arch` (B5, archived
    `changes/archive/2026-05-04-port-id_stage/`)
  - `src/IbexExBlock.arch` (B1, archived
    `changes/archive/2026-05-02-port-ex_block/`)
  - `src/IbexLoadStoreUnit.arch` (A9, archived
    `changes/archive/2026-05-02-port-load_store_unit/`)
  - `src/IbexWbStage.arch` (B2, archived
    `changes/archive/2026-05-02-port-wb_stage/`)
  - `src/IbexCoreSharedPkg.arch` (B5; reused for shared types)

- **Stays upstream**: `~/github/ibex/rtl/ibex_cs_registers.sv`
  (rdl2arch-riscv workstream, separate from C1).

- **Out of scope (Phase D)**: `~/github/ibex/rtl/ibex_pmp.sv`,
  `~/github/ibex/rtl/ibex_lockstep.sv`,
  `~/github/ibex/rtl/ibex_dummy_instr.sv`.

- **Project plan**:
  `~/.claude/projects/-Users-<user>-github-arch-com/memory/project_ibex_arch_plan.md`
  (Phase C is the linchpin; rdl2arch-riscv generates CSRs).

- **Memory inputs consulted**:
  - `feedback_proposal_construct_enumeration.md` — required table.
  - `feedback_arch_syntax_pitfalls.md` — Vec reset, unpacked Vec
    ports, param ternary, `use Pkg;` placement, "verilator" in
    comments.
  - `feedback_thread_single_state_idiom.md` — why `thread` is
    rejected for ibex_core.
  - `feedback_full_gate_before_ready.md` — `rm -rf build/` before
    READY.md.
  - `feedback_parallel_pytest.md` — `pytest -n auto --dist=loadfile`.
  - `feedback_spec_first_arch_blind.md` — spec-first methodology;
    spec extractor + test writer + implementer are isolated agents.
  - `feedback_controller_isr_gap_lessons.md` — ISR programs are the
    integration gate that catches what unit tests miss.
  - `feedback_shared_types_package.md` — keep CamelCase .arch
    filenames; let build script handle snake_case SV emission.

- **ARCH HDL spec sections relevant to C1**:
  - §2 (`module` / file-scope structure)
  - §3.6 (`unpacked` Vec port modifier — held in
    `arch-com-unpacked-ports/` branch doc, not main)
  - §8-§12 (first-class construct catalog used for the enumeration
    table)
  - `pipeline` construct chapter (referenced by spike).
