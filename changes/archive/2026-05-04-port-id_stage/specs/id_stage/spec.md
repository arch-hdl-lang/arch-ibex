# IbexIdStage — port contract + behavior

## Module overview

`ibex_id_stage` is the instruction-decode / issue stage of the Ibex
core. It is structurally a top-level wrapper that instantiates two
sub-modules (`ibex_decoder`, `ibex_controller`) and around them adds:
the operand-mux logic that selects ALU operand-A, operand-B, and the
B-immediate; the LSU request handshake (`lsu_req_o` and friends); the
register-file-write data mux; the multdiv intermediate-value pipeline
register pair (`imd_val_q[2]`); branch-set / jump-set pulse generation
(including the 2-cycle "branch-set flop" path); and the 2-state ID FSM
(`id_fsm_q ∈ {FIRST_CYCLE, MULTI_CYCLE}`) that aggregates stall sources
(`stall_ld_hz | stall_mem | stall_multdiv | stall_jump | stall_branch
| stall_alu`) and decides when an instruction has retired. It sits
between the IF stage (consumes `instr_valid_i`, `instr_rdata_i`,
`pc_id_i`, fetch-error flags), the EX block (drives
`alu_operand_*_ex_o`, multdiv operands, mult/div enables; receives
`ex_valid_i`, `result_ex_i`, `imd_val_d_ex_i`), the LSU (drives the
five `lsu_*_o` request signals; receives `lsu_resp_valid_i`,
`lsu_req_done_i`, error/last-addr signals), the CSRs (drives
`csr_*_o`), the register file (drives `rf_raddr_a/b_o`,
`rf_waddr_id_o`, `rf_wdata_id_o`, `rf_we_id_o`, `rf_ren_a/b_o`), and
emits per-cycle performance pulses
(`perf_jump_o`/`perf_branch_o`/`perf_tbranch_o`/`perf_dside_wait_o`/
`perf_mul_wait_o`/`perf_div_wait_o`).

## Pinned parameter values

This spec is restricted to the SoC's parameter pinning. Out-of-scope
branches are absent from the requirements below.

| Parameter         | Pinned value          | Effect on this spec |
|-------------------|-----------------------|---------------------|
| `RV32E`           | `1'b0`                | Register addresses are 5-bit; no GPR-narrowing logic. |
| `RV32M`           | `RV32MFast`           | `multdiv_en_dec = mult_en_dec | div_en_dec`. Single-cycle MUL can finish in FIRST_CYCLE if `ex_valid_i` is high. |
| `RV32B`           | `RV32BNone`           | No bitmanip operand muxing arms. |
| `BranchTargetALU` | `1'b0`                | `g_no_btalu_muxes` arm only. `bt_a_operand_o = 0`, `bt_b_operand_o = 0`. The full 7-arm `immediate_b_mux` is in scope (vs. the BTALU's reduced 5-arm). Branches always take 2 cycles; jumps always take 2 cycles. |
| `WritebackStage`  | `1'b0`                | `gen_no_stall_mem` arm only. `stall_ld_hz = 0`, `instr_executing_spec = instr_executing`, `rf_rdata_*_fwd = rf_rdata_*_i` (no WB forwarding). `expecting_load_resp_o`/`expecting_store_resp_o` are derived from `lsu_req_dec & ~instr_first_cycle`. `instr_type_wb_o = WB_INSTR_OTHER`. `stall_wb = 0`. `instr_id_done_o = instr_done`. |
| `BranchPredictor` | `1'b0`                | `g_n_calc_nt_addr` arm: `nt_branch_addr_o = 0`. `branch_not_set` is constant `0`. `instr_bp_taken_i = 0` (used only by sub-instances). |
| `MemECC`          | `1'b0`                | `mem_resp_intg_err = 0` (both `lsu_load_resp_intg_err_i` and `lsu_store_resp_intg_err_i` are tied off in the SoC). |
| `DataIndTiming`   | `1'b0`                | `g_branch_set_flop` arm is active (since `BranchTargetALU=0`); `g_nosec_branch_taken` arm: `branch_taken = 1` always. The `data_ind_timing_i` *input* is wired through but always 0 — its branch-stall arm is inert. |

## Ports

### Clock + reset

| Direction | Name      | Type / Width             | Role |
|-----------|-----------|--------------------------|------|
| in        | `clk_i`   | `Clock<SysDomain>`       | System clock (rising-edge sampled). |
| in        | `rst_ni`  | `Reset<Async, Low>`      | Active-low asynchronous reset. |

### IF-stage interface (consumer of IF→ID register, producer of redirect strobes)

| Direction | Name                       | Type / Width              | Role |
|-----------|----------------------------|---------------------------|------|
| in        | `instr_valid_i`            | `Bool`                    | An instruction sits in the IF→ID register and is valid for ID consumption. |
| in        | `instr_rdata_i`            | `UInt<32>`                | Latched 32-bit instruction word from the IF→ID register. |
| in        | `instr_rdata_alu_i`        | `UInt<32>`                | Replicated copy of `instr_rdata_i` (for ALU fan-out). Forwarded into `decoder_i`. |
| in        | `instr_rdata_c_i`          | `UInt<16>`                | Original 16-bit half of compressed instruction (mtval). Forwarded into `controller_i`. |
| in        | `instr_is_compressed_i`    | `Bool`                    | Current instruction is RV32C (16-bit). |
| in        | `instr_bp_taken_i`         | `Bool`                    | Pinned `0` (BranchPredictor=0). Forwarded into `controller_i`. |
| in        | `illegal_c_insn_i`         | `Bool`                    | Compressed-decoder reported illegal compressed encoding. |
| in        | `instr_fetch_err_i`        | `Bool`                    | IF stage flagged a fetch error for the current ID instruction. |
| in        | `instr_fetch_err_plus2_i`  | `Bool`                    | Fetch error landed on the upper 16 bits (mtval = pc+2). |
| in        | `pc_id_i`                  | `UInt<32>`                | PC of current ID instruction. |
| in        | `instr_exec_i`             | `Bool`                    | Top-level execution-enable; forwarded into `controller_i`. |
| out       | `instr_req_o`              | `Bool`                    | Forwarded directly from `controller_i.instr_req_o` — fetch-enable strobe to the prefetch/IF. |
| out       | `instr_first_cycle_id_o`   | `Bool`                    | `instr_valid_i & (id_fsm_q == FIRST_CYCLE)`. Used by EX/RF for first-cycle gating. |
| out       | `instr_valid_clear_o`      | `Bool`                    | Forwarded directly from `controller_i.instr_valid_clear_o`. Tells the IF→ID register to clear next cycle. |
| out       | `id_in_ready_o`            | `Bool`                    | Forwarded directly from `controller_i.id_in_ready_o`. ID stage will accept a new instruction from IF this cycle. |
| out       | `icache_inval_o`           | `Bool`                    | Forwarded directly from `decoder_i.icache_inval_o`. Asserted on `fence.i`. ICache is off in our SoC; output is unwired externally but must still be driven. |

### Branch / jump control

| Direction | Name                       | Type / Width              | Role |
|-----------|----------------------------|---------------------------|------|
| in        | `branch_decision_i`        | `Bool`                    | EX-block branch comparator output (taken/not-taken). |
| out       | `pc_set_o`                 | `Bool`                    | Forwarded from `controller_i.pc_set_o`. Strobe to redirect IF PC. |
| out       | `pc_mux_o`                 | `PcSel`                   | Forwarded from `controller_i.pc_mux_o`. |
| out       | `nt_branch_mispredict_o`   | `Bool`                    | Forwarded from `controller_i.nt_branch_mispredict_o`. Constant `0` under BranchPredictor=0. |
| out       | `nt_branch_addr_o`         | `UInt<32>`                | Constant `32'd0` under BranchPredictor=0. |
| out       | `exc_pc_mux_o`             | `ExcPcSel`                | Forwarded from `controller_i.exc_pc_mux_o`. |
| out       | `exc_cause_o`              | `ExcCause`                | Forwarded from `controller_i.exc_cause_o`. |

### EX-block interface

| Direction | Name                         | Type / Width                  | Role |
|-----------|------------------------------|-------------------------------|------|
| in        | `ex_valid_i`                 | `Bool`                        | EX stage has valid output (ALU done; multdiv result ready). Goes high when the ALU/multdiv result is valid; falls on the same edge as `id_in_ready_o`. |
| out       | `alu_operator_ex_o`          | `AluOp`                       | Decoder's `alu_operator` (combinational from `decoder_i`). |
| out       | `alu_operand_a_ex_o`         | `UInt<32>`                    | Selected operand A (see Requirement 4). |
| out       | `alu_operand_b_ex_o`         | `UInt<32>`                    | Selected operand B (see Requirement 5). |
| in        | `imd_val_we_ex_i`            | `UInt<2>`                     | Per-lane write-enable into the intermediate-value register pair. |
| in        | `imd_val_d_ex_i`             | `Vec<UInt<34>, 2>`            | Per-lane next-state for the imd_val pair. |
| out       | `imd_val_q_ex_o`             | `Vec<UInt<34>, 2>`            | Current value of the imd_val pair, fed back to EX/multdiv. |
| out       | `bt_a_operand_o`             | `UInt<32>`                    | Constant `32'h0` under BranchTargetALU=0. |
| out       | `bt_b_operand_o`             | `UInt<32>`                    | Constant `32'h0` under BranchTargetALU=0. |
| in        | `result_ex_i`                | `UInt<32>`                    | EX-block result (ALU/multdiv) for write-back data mux. |

### Multdiv interface

| Direction | Name                         | Type / Width                  | Role |
|-----------|------------------------------|-------------------------------|------|
| out       | `mult_en_ex_o`               | `Bool`                        | `instr_executing ? mult_en_dec : 0`. |
| out       | `div_en_ex_o`                | `Bool`                        | `instr_executing ? div_en_dec : 0`. |
| out       | `mult_sel_ex_o`              | `Bool`                        | Forwarded from `decoder_i.mult_sel_o`. |
| out       | `div_sel_ex_o`               | `Bool`                        | Forwarded from `decoder_i.div_sel_o`. |
| out       | `multdiv_operator_ex_o`      | `MdOp`                        | Forwarded from `decoder_i.multdiv_operator_o`. |
| out       | `multdiv_signed_mode_ex_o`   | `UInt<2>`                     | Forwarded from `decoder_i.multdiv_signed_mode_o`. |
| out       | `multdiv_operand_a_ex_o`     | `UInt<32>`                    | `rf_rdata_a_fwd`. (Under WritebackStage=0, `rf_rdata_a_fwd = rf_rdata_a_i`.) |
| out       | `multdiv_operand_b_ex_o`     | `UInt<32>`                    | `rf_rdata_b_fwd`. (Under WritebackStage=0, `rf_rdata_b_fwd = rf_rdata_b_i`.) |
| out       | `multdiv_ready_id_o`         | `Bool`                        | `ready_wb_i`. (Pinned `1` under WritebackStage=0.) |

### CSR interface

| Direction | Name                         | Type / Width                  | Role |
|-----------|------------------------------|-------------------------------|------|
| out       | `csr_access_o`               | `Bool`                        | Forwarded from `decoder_i.csr_access_o`. |
| out       | `csr_op_o`                   | `CsrOp`                       | Forwarded from `decoder_i.csr_op_o`. |
| out       | `csr_addr_o`                 | `CsrNum`                      | Forwarded from `decoder_i.csr_addr_o`. |
| out       | `csr_op_en_o`                | `Bool`                        | `csr_access_o & instr_executing & instr_id_done_o`. |
| out       | `csr_save_if_o`              | `Bool`                        | Forwarded from `controller_i.csr_save_if_o`. |
| out       | `csr_save_id_o`              | `Bool`                        | Forwarded from `controller_i.csr_save_id_o`. |
| out       | `csr_save_wb_o`              | `Bool`                        | Forwarded from `controller_i.csr_save_wb_o`. (Constant `0` under WritebackStage=0.) |
| out       | `csr_restore_mret_id_o`      | `Bool`                        | Forwarded from `controller_i.csr_restore_mret_id_o`. |
| out       | `csr_restore_dret_id_o`      | `Bool`                        | Forwarded from `controller_i.csr_restore_dret_id_o`. |
| out       | `csr_save_cause_o`           | `Bool`                        | Forwarded from `controller_i.csr_save_cause_o`. |
| out       | `csr_mtval_o`                | `UInt<32>`                    | Forwarded from `controller_i.csr_mtval_o`. |
| in        | `priv_mode_i`                | `PrivLvl`                     | Current privilege level. Forwarded into `controller_i`; locally used in `illegal_umode_insn`. |
| in        | `csr_mstatus_tw_i`           | `Bool`                        | mstatus.TW. Used in `illegal_umode_insn` (TW makes WFI illegal in U-mode). |
| in        | `illegal_csr_insn_i`         | `Bool`                        | CSR-side illegal flag. Used in `illegal_insn_o` and gates `rf_we_id_o`. |
| in        | `csr_rdata_i`                | `UInt<32>`                    | CSR read data, into `rf_wdata_id` mux when `rf_wdata_sel == RF_WD_CSR`. |
| in        | `data_ind_timing_i`          | `Bool`                        | Pinned `0`. Forwarded into the (inert) DataIndTiming arm. Otherwise consumed only by the `unused_*` absorber. |

### LSU interface

| Direction | Name                         | Type / Width                  | Role |
|-----------|------------------------------|-------------------------------|------|
| out       | `lsu_req_o`                  | `Bool`                        | LSU request strobe (see Requirement 7). |
| out       | `lsu_we_o`                   | `Bool`                        | Forwarded from `decoder_i.data_we_o` (raw, ungated by `instr_executing`). |
| out       | `lsu_type_o`                 | `UInt<2>`                     | Forwarded from `decoder_i.data_type_o` (raw). |
| out       | `lsu_sign_ext_o`             | `Bool`                        | Forwarded from `decoder_i.data_sign_extension_o` (raw). |
| out       | `lsu_wdata_o`                | `UInt<32>`                    | `rf_rdata_b_fwd` (= `rf_rdata_b_i` under WritebackStage=0). |
| in        | `lsu_resp_valid_i`           | `Bool`                        | LSU response valid (used in `multicycle_done` and `stall_mem`). |
| in        | `lsu_req_done_i`             | `Bool`                        | LSU request handshake complete signal. **Under WritebackStage=0 this is unused** (sunk into `unused_data_req_done_ex` absorber). |
| in        | `lsu_addr_incr_req_i`        | `Bool`                        | LSU is requesting the second half of a misaligned access; forces operand-A mux to `OP_A_FWD` and operand-B path to `IMM_B_INCR_ADDR`. |
| in        | `lsu_addr_last_i`            | `UInt<32>`                    | Last LSU address; sourced into `alu_operand_a` when `alu_op_a_mux_sel == OP_A_FWD`. Also forwarded into `controller_i`. |
| in        | `lsu_load_err_i`             | `Bool`                        | LSU load access fault; forwarded into `controller_i`. |
| in        | `lsu_load_resp_intg_err_i`   | `Bool`                        | Tied off `0` under MemECC=0. Combined into `mem_resp_intg_err`. |
| in        | `lsu_store_err_i`            | `Bool`                        | LSU store access fault; forwarded into `controller_i`. |
| in        | `lsu_store_resp_intg_err_i`  | `Bool`                        | Tied off `0` under MemECC=0. Combined into `mem_resp_intg_err`. |
| out       | `expecting_load_resp_o`      | `Bool`                        | `instr_valid_i & lsu_req_dec & ~instr_first_cycle & ~lsu_we`. |
| out       | `expecting_store_resp_o`     | `Bool`                        | `instr_valid_i & lsu_req_dec & ~instr_first_cycle &  lsu_we`. |

### Interrupt / debug interface (forwarded to controller)

| Direction | Name                         | Type / Width                  | Role |
|-----------|------------------------------|-------------------------------|------|
| in        | `csr_mstatus_mie_i`          | `Bool`                        | Forwarded into `controller_i`. |
| in        | `irq_pending_i`              | `Bool`                        | Forwarded into `controller_i`. |
| in        | `irqs_i`                     | `Irqs`                        | Forwarded into `controller_i`. |
| in        | `irq_nm_i`                   | `Bool`                        | Forwarded into `controller_i.irq_nm_ext_i`. |
| out       | `nmi_mode_o`                 | `Bool`                        | Forwarded from `controller_i.nmi_mode_o`. |
| in        | `debug_req_i`                | `Bool`                        | Forwarded into `controller_i`. |
| in        | `debug_single_step_i`        | `Bool`                        | Forwarded into `controller_i`. |
| in        | `debug_ebreakm_i`            | `Bool`                        | Forwarded into `controller_i`. |
| in        | `debug_ebreaku_i`            | `Bool`                        | Forwarded into `controller_i`. |
| in        | `trigger_match_i`            | `Bool`                        | Forwarded into `controller_i`. |
| out       | `debug_mode_o`               | `Bool`                        | Forwarded from `controller_i.debug_mode_o`. **Locally consumed** in `illegal_dret_insn = dret_insn_dec & ~debug_mode_o`. |
| out       | `debug_mode_entering_o`      | `Bool`                        | Forwarded from `controller_i.debug_mode_entering_o`. |
| out       | `debug_cause_o`              | `DbgCause`                    | Forwarded from `controller_i.debug_cause_o`. |
| out       | `debug_csr_save_o`           | `Bool`                        | Forwarded from `controller_i.debug_csr_save_o`. |

### Register-file interface

| Direction | Name                         | Type / Width                  | Role |
|-----------|------------------------------|-------------------------------|------|
| out       | `rf_raddr_a_o`               | `UInt<5>`                     | Forwarded from `decoder_i.rf_raddr_a_o`. |
| in        | `rf_rdata_a_i`               | `UInt<32>`                    | RF read-port-A data. |
| out       | `rf_raddr_b_o`               | `UInt<5>`                     | Forwarded from `decoder_i.rf_raddr_b_o`. |
| in        | `rf_rdata_b_i`               | `UInt<32>`                    | RF read-port-B data. |
| out       | `rf_ren_a_o`                 | `Bool`                        | `rf_ren_a = instr_valid_i & ~instr_fetch_err_i & ~illegal_insn_o & rf_ren_a_dec`. |
| out       | `rf_ren_b_o`                 | `Bool`                        | `rf_ren_b = instr_valid_i & ~instr_fetch_err_i & ~illegal_insn_o & rf_ren_b_dec`. |
| out       | `rf_waddr_id_o`              | `UInt<5>`                     | Forwarded from `decoder_i.rf_waddr_o`. |
| out       | `rf_wdata_id_o`              | `UInt<32>`                    | `rf_wdata_id_mux` output (Requirement 6). |
| out       | `rf_we_id_o`                 | `Bool`                        | `rf_we_raw & instr_executing & ~illegal_csr_insn_i`. |
| out       | `rf_rd_a_wb_match_o`         | `Bool`                        | Constant `0` under WritebackStage=0. |
| out       | `rf_rd_b_wb_match_o`         | `Bool`                        | Constant `0` under WritebackStage=0. |
| in        | `rf_waddr_wb_i`              | `UInt<5>`                     | Pinned `0` under WritebackStage=0; sunk into `unused_*` absorber. |
| in        | `rf_wdata_fwd_wb_i`          | `UInt<32>`                    | Pinned `0` under WritebackStage=0; sunk into `unused_*` absorber. |
| in        | `rf_write_wb_i`              | `Bool`                        | Pinned `0` under WritebackStage=0; sunk into `unused_*` absorber. |

### Writeback-stage interface (mostly absorbed under WritebackStage=0)

| Direction | Name                         | Type / Width                  | Role |
|-----------|------------------------------|-------------------------------|------|
| out       | `en_wb_o`                    | `Bool`                        | `instr_done`. (Indicates the in-ID instruction is retiring this cycle.) |
| out       | `instr_type_wb_o`            | `WbInstrType`                 | Constant `WB_INSTR_OTHER` under WritebackStage=0. |
| out       | `instr_perf_count_id_o`      | `Bool`                        | `~ebrk_insn & ~ecall_insn_dec & ~illegal_insn_dec & ~illegal_csr_insn_i & ~instr_fetch_err_i`. |
| in        | `ready_wb_i`                 | `Bool`                        | Pinned `1` under WritebackStage=0. |
| in        | `outstanding_load_wb_i`      | `Bool`                        | Pinned `0` under WritebackStage=0; sunk into `unused_*` absorber. |
| in        | `outstanding_store_wb_i`     | `Bool`                        | Pinned `0` under WritebackStage=0; sunk into `unused_*` absorber. |

### Top-level / miscellaneous

| Direction | Name                         | Type / Width                  | Role |
|-----------|------------------------------|-------------------------------|------|
| out       | `ctrl_busy_o`                | `Bool`                        | Forwarded from `controller_i.ctrl_busy_o`. |
| out       | `illegal_insn_o`             | `Bool`                        | `instr_valid_i & (illegal_insn_dec | illegal_csr_insn_i | illegal_dret_insn | illegal_umode_insn)`. |
| out       | `instr_id_done_o`            | `Bool`                        | Under WritebackStage=0: equals `instr_done`. Used by `csr_op_en_o`. |

### Performance counters (per-cycle pulse outputs)

| Direction | Name                         | Type / Width                  | Role |
|-----------|------------------------------|-------------------------------|------|
| out       | `perf_jump_o`                | `Bool`                        | Forwarded from `controller_i.perf_jump_o`. |
| out       | `perf_branch_o`              | `Bool`                        | Asserted in the FIRST_CYCLE of a `branch_in_dec` instruction (see Requirement 9). |
| out       | `perf_tbranch_o`             | `Bool`                        | Forwarded from `controller_i.perf_tbranch_o`. |
| out       | `perf_dside_wait_o`          | `Bool`                        | Under WritebackStage=0: `instr_executing & lsu_req_dec & ~lsu_resp_valid_i`. |
| out       | `perf_mul_wait_o`            | `Bool`                        | `stall_multdiv & mult_en_dec`. |
| out       | `perf_div_wait_o`            | `Bool`                        | `stall_multdiv & div_en_dec`. |

## Sub-module instances

### `decoder_i` (`ibex_decoder`, ported as A4)

Parameter pass-through:

- `RV32E = RV32E` (= 0)
- `RV32M = RV32M` (= `RV32MFast`)
- `RV32B = RV32B` (= `RV32BNone`)
- `BranchTargetALU = BranchTargetALU` (= 0)

Connections (outer name → decoder port):

| Outer signal              | Decoder port           | Direction (decoder side) |
|---------------------------|------------------------|--------------------------|
| `clk_i`                   | `clk_i`                | in                       |
| `rst_ni`                  | `rst_ni`               | in                       |
| `illegal_insn_dec`        | `illegal_insn_o`       | out                      |
| `ebrk_insn`               | `ebrk_insn_o`          | out                      |
| `mret_insn_dec`           | `mret_insn_o`          | out                      |
| `dret_insn_dec`           | `dret_insn_o`          | out                      |
| `ecall_insn_dec`          | `ecall_insn_o`         | out                      |
| `wfi_insn_dec`            | `wfi_insn_o`           | out                      |
| `jump_set_dec`            | `jump_set_o`           | out                      |
| `branch_taken`            | `branch_taken_i`       | in                       |
| `icache_inval_o`          | `icache_inval_o`       | out (passthrough to top) |
| `instr_first_cycle`       | `instr_first_cycle_i`  | in                       |
| `instr_rdata_i`           | `instr_rdata_i`        | in                       |
| `instr_rdata_alu_i`       | `instr_rdata_alu_i`    | in                       |
| `illegal_c_insn_i`        | `illegal_c_insn_i`     | in                       |
| `imm_a_mux_sel`           | `imm_a_mux_sel_o`      | out                      |
| `imm_b_mux_sel_dec`       | `imm_b_mux_sel_o`      | out                      |
| `bt_a_mux_sel`            | `bt_a_mux_sel_o`       | out                      |
| `bt_b_mux_sel`            | `bt_b_mux_sel_o`       | out                      |
| `imm_i_type` … `imm_j_type`, `zimm_rs1_type` | `imm_*_type_o`, `zimm_rs1_type_o` | out |
| `rf_wdata_sel`            | `rf_wdata_sel_o`       | out                      |
| `rf_we_dec`               | `rf_we_o`              | out                      |
| `rf_raddr_a_o` (top)      | `rf_raddr_a_o`         | out                      |
| `rf_raddr_b_o` (top)      | `rf_raddr_b_o`         | out                      |
| `rf_waddr_id_o` (top)     | `rf_waddr_o`           | out                      |
| `rf_ren_a_dec`            | `rf_ren_a_o`           | out                      |
| `rf_ren_b_dec`            | `rf_ren_b_o`           | out                      |
| `alu_operator`            | `alu_operator_o`       | out                      |
| `alu_op_a_mux_sel_dec`    | `alu_op_a_mux_sel_o`   | out                      |
| `alu_op_b_mux_sel_dec`    | `alu_op_b_mux_sel_o`   | out                      |
| `alu_multicycle_dec`      | `alu_multicycle_o`     | out                      |
| `mult_en_dec`             | `mult_en_o`            | out                      |
| `div_en_dec`              | `div_en_o`             | out                      |
| `mult_sel_ex_o` (top)     | `mult_sel_o`           | out                      |
| `div_sel_ex_o` (top)      | `div_sel_o`            | out                      |
| `multdiv_operator`        | `multdiv_operator_o`   | out                      |
| `multdiv_signed_mode`     | `multdiv_signed_mode_o`| out                      |
| `csr_access_o` (top)      | `csr_access_o`         | out                      |
| `csr_op_o` (top)          | `csr_op_o`             | out                      |
| `csr_addr_o` (top)        | `csr_addr_o`           | out                      |
| `lsu_req_dec`             | `data_req_o`           | out                      |
| `lsu_we`                  | `data_we_o`            | out                      |
| `lsu_type`                | `data_type_o`          | out                      |
| `lsu_sign_ext`            | `data_sign_extension_o`| out                      |
| `jump_in_dec`             | `jump_in_dec_o`        | out                      |
| `branch_in_dec`           | `branch_in_dec_o`      | out                      |

### `controller_i` (`ibex_controller`, ported as B4)

Parameter pass-through:

- `WritebackStage = WritebackStage` (= 0)
- `BranchPredictor = BranchPredictor` (= 0)
- `MemECC = MemECC` (= 0)

Connections (outer name → controller port):

| Outer signal              | Controller port            |
|---------------------------|----------------------------|
| `clk_i`, `rst_ni`         | `clk_i`, `rst_ni`          |
| `ctrl_busy_o`             | `ctrl_busy_o`              |
| `illegal_insn_o`          | `illegal_insn_i`           |
| `ecall_insn_dec`          | `ecall_insn_i`             |
| `mret_insn_dec`           | `mret_insn_i`              |
| `dret_insn_dec`           | `dret_insn_i`              |
| `wfi_insn_dec`            | `wfi_insn_i`               |
| `ebrk_insn`               | `ebrk_insn_i`              |
| `csr_pipe_flush`          | `csr_pipe_flush_i`         |
| `instr_valid_i`           | `instr_valid_i`            |
| `instr_rdata_i`           | `instr_i`                  |
| `instr_rdata_c_i`         | `instr_compressed_i`       |
| `instr_is_compressed_i`   | `instr_is_compressed_i`    |
| `instr_bp_taken_i`        | `instr_bp_taken_i`         |
| `instr_fetch_err_i`       | `instr_fetch_err_i`        |
| `instr_fetch_err_plus2_i` | `instr_fetch_err_plus2_i`  |
| `pc_id_i`                 | `pc_id_i`                  |
| `instr_valid_clear_o`     | `instr_valid_clear_o`      |
| `id_in_ready_o`           | `id_in_ready_o`            |
| `controller_run`          | `controller_run_o`         |
| `instr_exec_i`            | `instr_exec_i`             |
| `instr_req_o`             | `instr_req_o`              |
| `pc_set_o`                | `pc_set_o`                 |
| `pc_mux_o`                | `pc_mux_o`                 |
| `nt_branch_mispredict_o`  | `nt_branch_mispredict_o`   |
| `exc_pc_mux_o`            | `exc_pc_mux_o`             |
| `exc_cause_o`             | `exc_cause_o`              |
| `lsu_addr_last_i`         | `lsu_addr_last_i`          |
| `lsu_load_err_i`          | `load_err_i`               |
| `mem_resp_intg_err`       | `mem_resp_intg_err_i`      |
| `lsu_store_err_i`         | `store_err_i`              |
| `wb_exception`            | `wb_exception_o`           |
| `id_exception`            | `id_exception_o`           |
| `branch_set`              | `branch_set_i`             |
| `branch_not_set`          | `branch_not_set_i`         |
| `jump_set`                | `jump_set_i`               |
| `csr_mstatus_mie_i`       | `csr_mstatus_mie_i`        |
| `irq_pending_i`           | `irq_pending_i`            |
| `irqs_i`                  | `irqs_i`                   |
| `irq_nm_i`                | `irq_nm_ext_i`             |
| `nmi_mode_o`              | `nmi_mode_o`               |
| `csr_save_if_o`           | `csr_save_if_o`            |
| `csr_save_id_o`           | `csr_save_id_o`            |
| `csr_save_wb_o`           | `csr_save_wb_o`            |
| `csr_restore_mret_id_o`   | `csr_restore_mret_id_o`    |
| `csr_restore_dret_id_o`   | `csr_restore_dret_id_o`    |
| `csr_save_cause_o`        | `csr_save_cause_o`         |
| `csr_mtval_o`             | `csr_mtval_o`              |
| `priv_mode_i`             | `priv_mode_i`              |
| `debug_mode_o`            | `debug_mode_o`             |
| `debug_mode_entering_o`   | `debug_mode_entering_o`    |
| `debug_cause_o`           | `debug_cause_o`            |
| `debug_csr_save_o`        | `debug_csr_save_o`         |
| `debug_req_i`             | `debug_req_i`              |
| `debug_single_step_i`     | `debug_single_step_i`      |
| `debug_ebreakm_i`         | `debug_ebreakm_i`          |
| `debug_ebreaku_i`         | `debug_ebreaku_i`          |
| `trigger_match_i`         | `trigger_match_i`          |
| `stall_id`                | `stall_id_i`               |
| `stall_wb`                | `stall_wb_i`               |
| `flush_id`                | `flush_id_o`               |
| `ready_wb_i`              | `ready_wb_i`               |
| `perf_jump_o`             | `perf_jump_o`              |
| `perf_tbranch_o`          | `perf_tbranch_o`           |

## Latched state regs

All flops are clocked on `posedge clk_i` and reset asynchronously on
`negedge rst_ni`. All writes use blocking-writeback (`<=`) and all
reset values are listed below.

| Reg                       | Width / type      | Reset value     | Write-enable / next-state                                           |
|---------------------------|-------------------|-----------------|---------------------------------------------------------------------|
| `id_fsm_q`                | `UInt<1>` / 2-state enum (`FIRST_CYCLE`=0, `MULTI_CYCLE`=1) | `FIRST_CYCLE` | Update only when `instr_executing` is high. Next-state `id_fsm_d` is computed by the comb block in Requirement 9. |
| `imd_val_q[0]`            | `UInt<34>`        | `34'h0`         | `imd_val_we_ex_i[0]` ? `imd_val_d_ex_i[0]` : hold.                  |
| `imd_val_q[1]`            | `UInt<34>`        | `34'h0`         | `imd_val_we_ex_i[1]` ? `imd_val_d_ex_i[1]` : hold.                  |
| `branch_set_raw_q`        | `Bool`            | `1'b0`          | Unconditional update each cycle: `branch_set_raw_q <= branch_set_raw_d`. (Active under our pinning — `g_branch_set_flop` arm.) |
| `branch_jump_set_done_q`  | `Bool`            | `1'b0`          | Unconditional update: `branch_jump_set_done_q <= branch_jump_set_done_d` where `branch_jump_set_done_d = (branch_set_raw \| jump_set_raw \| branch_jump_set_done_q) & ~instr_valid_clear_o`. |

Note: there is **no** `branch_set_q` self-feeding latch in this module
under our pinning. The proposal mentions one in passing but the actual
cross-cycle hold is implemented via the `branch_set_raw_q` flop above
(in the `g_branch_set_flop` arm). The 1-cycle pulse `branch_set` is
re-derived combinationally each cycle as
`branch_set = branch_set_raw & ~branch_jump_set_done_q`.

Out-of-scope flops (NOT to be ported): `branch_taken_q` (DataIndTiming=1
arm), `nt_branch_mispredict_q` (BranchPredictor=1), and the
`gen_stall_mem` WB-bypass match flops (WritebackStage=1).

## Combinational logic blocks

The implementer should mirror upstream's block boundaries. Each block
below should be one comb block; signals marked "continuous" are simple
top-level assigns and may be top-level `let`s.

### LSU operand-mux override (continuous)

```
alu_op_a_mux_sel = lsu_addr_incr_req_i ? OP_A_FWD        : alu_op_a_mux_sel_dec
alu_op_b_mux_sel = lsu_addr_incr_req_i ? OP_B_IMM        : alu_op_b_mux_sel_dec
imm_b_mux_sel    = lsu_addr_incr_req_i ? IMM_B_INCR_ADDR : imm_b_mux_sel_dec
```

### `imm_a` (continuous)

```
imm_a = (imm_a_mux_sel == IMM_A_Z) ? zimm_rs1_type : 32'h0
```

### `alu_operand_a_mux` (always_comb)

```
case alu_op_a_mux_sel:
  OP_A_REG_A:  alu_operand_a = rf_rdata_a_fwd
  OP_A_FWD:    alu_operand_a = lsu_addr_last_i
  OP_A_CURRPC: alu_operand_a = pc_id_i
  OP_A_IMM:    alu_operand_a = imm_a
  default:     alu_operand_a = pc_id_i
```

### `immediate_b_mux` (always_comb, full 7-arm — `g_no_btalu_muxes`)

```
case imm_b_mux_sel:
  IMM_B_I:         imm_b = imm_i_type
  IMM_B_S:         imm_b = imm_s_type
  IMM_B_B:         imm_b = imm_b_type
  IMM_B_U:         imm_b = imm_u_type
  IMM_B_J:         imm_b = imm_j_type
  IMM_B_INCR_PC:   imm_b = instr_is_compressed_i ? 32'h2 : 32'h4
  IMM_B_INCR_ADDR: imm_b = 32'h4
  default:         imm_b = 32'h4
```

### `alu_operand_b` mux (continuous)

```
alu_operand_b = (alu_op_b_mux_sel == OP_B_IMM) ? imm_b : rf_rdata_b_fwd
```

### BTALU tieoffs (continuous, BranchTargetALU=0)

```
bt_a_operand_o = 32'h0
bt_b_operand_o = 32'h0
```

### `rf_wdata_id_mux` (always_comb)

```
case rf_wdata_sel:
  RF_WD_EX:  rf_wdata_id_o = result_ex_i
  RF_WD_CSR: rf_wdata_id_o = csr_rdata_i
  default:   rf_wdata_id_o = result_ex_i
```

### Decoder/CSR helpers (continuous)

```
no_flush_csr_addr  = csr_addr_o ∈ {CSR_MSCRATCH, CSR_MEPC}
csr_pipe_flush     = (csr_op_en_o == 1) &&
                     (csr_op_o ∈ {CSR_OP_WRITE, CSR_OP_SET, CSR_OP_CLEAR}) &&
                     ~no_flush_csr_addr
illegal_dret_insn  = dret_insn_dec & ~debug_mode_o
illegal_umode_insn = (priv_mode_i != PRIV_LVL_M) &
                     (mret_insn_dec | (csr_mstatus_tw_i & wfi_insn_dec))
illegal_insn_o     = instr_valid_i & (illegal_insn_dec | illegal_csr_insn_i |
                                      illegal_dret_insn | illegal_umode_insn)
mem_resp_intg_err  = lsu_load_resp_intg_err_i | lsu_store_resp_intg_err_i  // = 0 under MemECC=0
```

### Read-enable gating (continuous)

```
rf_ren_a   = instr_valid_i & ~instr_fetch_err_i & ~illegal_insn_o & rf_ren_a_dec
rf_ren_b   = instr_valid_i & ~instr_fetch_err_i & ~illegal_insn_o & rf_ren_b_dec
rf_ren_a_o = rf_ren_a
rf_ren_b_o = rf_ren_b
```

### EX-side wiring (continuous)

```
multdiv_en_dec          = mult_en_dec | div_en_dec
lsu_req                 = instr_executing ? data_req_allowed & lsu_req_dec : 1'b0
mult_en_id              = instr_executing ? mult_en_dec                    : 1'b0
div_en_id               = instr_executing ? div_en_dec                     : 1'b0
lsu_req_o               = lsu_req
lsu_we_o                = lsu_we
lsu_type_o              = lsu_type
lsu_sign_ext_o          = lsu_sign_ext
lsu_wdata_o             = rf_rdata_b_fwd
csr_op_en_o             = csr_access_o & instr_executing & instr_id_done_o
alu_operator_ex_o       = alu_operator
alu_operand_a_ex_o      = alu_operand_a
alu_operand_b_ex_o      = alu_operand_b
mult_en_ex_o            = mult_en_id
div_en_ex_o             = div_en_id
multdiv_operator_ex_o   = multdiv_operator
multdiv_signed_mode_ex_o= multdiv_signed_mode
multdiv_operand_a_ex_o  = rf_rdata_a_fwd
multdiv_operand_b_ex_o  = rf_rdata_b_fwd
multdiv_ready_id_o      = ready_wb_i
imd_val_q_ex_o          = imd_val_q   // pair forward
rf_we_id_o              = rf_we_raw & instr_executing & ~illegal_csr_insn_i
```

### Branch-set / jump-set derivation (continuous)

```
// g_branch_set_flop arm — BranchTargetALU=0 ⇒ branch_set_raw is the flopped version
branch_set_raw       = branch_set_raw_q
// Mask any cycle in which a set has already been emitted for this instruction
jump_set             = jump_set_raw    & ~branch_jump_set_done_q
branch_set           = branch_set_raw  & ~branch_jump_set_done_q
branch_jump_set_done_d = (branch_set_raw | jump_set_raw | branch_jump_set_done_q) & ~instr_valid_clear_o
// g_nosec_branch_taken arm — DataIndTiming=0 ⇒ branch_taken is constant 1
branch_taken         = 1'b1
// g_n_calc_nt_addr arm — BranchPredictor=0
nt_branch_addr_o     = 32'd0
```

### `instr_first_cycle` and friends (continuous)

```
instr_first_cycle      = instr_valid_i & (id_fsm_q == FIRST_CYCLE)
instr_first_cycle_id_o = instr_first_cycle
```

### `gen_no_stall_mem` arm (WritebackStage=0)

```
multicycle_done        = lsu_req_dec ? lsu_resp_valid_i : ex_valid_i
data_req_allowed       = instr_first_cycle
stall_mem              = instr_valid_i & (lsu_req_dec & (~lsu_resp_valid_i | instr_first_cycle))
stall_ld_hz            = 1'b0
instr_executing_spec   = instr_valid_i & ~instr_fetch_err_i & controller_run
instr_executing        = instr_executing_spec
rf_rdata_a_fwd         = rf_rdata_a_i
rf_rdata_b_fwd         = rf_rdata_b_i
rf_rd_a_wb_match_o     = 1'b0
rf_rd_b_wb_match_o     = 1'b0
expecting_load_resp_o  = instr_valid_i & lsu_req_dec & ~instr_first_cycle & ~lsu_we
expecting_store_resp_o = instr_valid_i & lsu_req_dec & ~instr_first_cycle &  lsu_we
instr_type_wb_o        = WB_INSTR_OTHER
stall_wb               = 1'b0
perf_dside_wait_o      = instr_executing & lsu_req_dec & ~lsu_resp_valid_i
instr_id_done_o        = instr_done
```

Plus absorbers for the WB-stage inputs unused under WritebackStage=0:
`lsu_req_done_i`, `rf_waddr_wb_i`, `rf_write_wb_i`,
`outstanding_load_wb_i`, `outstanding_store_wb_i`, `wb_exception`,
`rf_wdata_fwd_wb_i`, `id_exception`. (In ARCH these become `let
unused_* = signal;` absorbers or equivalent.)

### Common helpers (continuous)

```
stall_id          = stall_ld_hz | stall_mem | stall_multdiv | stall_jump | stall_branch | stall_alu
instr_done        = ~stall_id & ~flush_id & instr_executing
en_wb_o           = instr_done
instr_perf_count_id_o = ~ebrk_insn & ~ecall_insn_dec & ~illegal_insn_dec &
                        ~illegal_csr_insn_i & ~instr_fetch_err_i
perf_mul_wait_o   = stall_multdiv & mult_en_dec
perf_div_wait_o   = stall_multdiv & div_en_dec
```

### ID-FSM next-state and stall generation (one big always_comb)

This is the central control block. See Requirement 9 for the full
state-table behavior; pseudo-RTL below mirrors it directly. Defaults
are listed first; arms override them.

```
id_fsm_d         = id_fsm_q
rf_we_raw        = rf_we_dec
stall_multdiv    = 0
stall_jump       = 0
stall_branch     = 0
stall_alu        = 0
branch_set_raw_d = 0
branch_not_set   = 0
jump_set_raw     = 0
perf_branch_o    = 0

if (instr_executing_spec) {
  case (id_fsm_q) {
    FIRST_CYCLE: case (1'b1) {     // priority case: $onehot0 of the four flags below
      lsu_req_dec:        // load/store
        // WritebackStage=0 path — always go to MULTI_CYCLE on a load/store
        id_fsm_d = MULTI_CYCLE
      multdiv_en_dec:     // mul or div
        if (~ex_valid_i) {
          id_fsm_d      = MULTI_CYCLE
          rf_we_raw     = 0
          stall_multdiv = 1
        }
        // else (single-cycle MUL hit): id_fsm_d stays FIRST_CYCLE,
        // rf_we_raw stays = rf_we_dec, no stall flags
      branch_in_dec:      // conditional branch
        // BranchTargetALU=0, DataIndTiming=0 ⇒
        //   id_fsm_d         = branch_decision_i ? MULTI_CYCLE : FIRST_CYCLE
        //   stall_branch     = branch_decision_i
        //   branch_set_raw_d = branch_decision_i
        // perf_branch_o is asserted unconditionally on this arm.
        // BranchPredictor=0 ⇒ branch_not_set is left at its default 0.
        id_fsm_d         = branch_decision_i ? MULTI_CYCLE : FIRST_CYCLE
        stall_branch     = branch_decision_i
        branch_set_raw_d = branch_decision_i
        perf_branch_o    = 1
      jump_in_dec:        // unconditional jump
        // BranchTargetALU=0 ⇒ id_fsm_d = MULTI_CYCLE; stall_jump = 1
        id_fsm_d     = MULTI_CYCLE
        stall_jump   = 1
        jump_set_raw = jump_set_dec
      alu_multicycle_dec: // multi-cycle ALU op
        stall_alu = 1
        id_fsm_d  = MULTI_CYCLE
        rf_we_raw = 0
      default:
        id_fsm_d = FIRST_CYCLE
    }
    MULTI_CYCLE:
      if (multdiv_en_dec) { rf_we_raw = rf_we_dec & ex_valid_i }
      if (multicycle_done & ready_wb_i) {  // ready_wb_i pinned to 1
        id_fsm_d = FIRST_CYCLE
      } else {
        stall_multdiv = multdiv_en_dec
        stall_branch  = branch_in_dec
        stall_jump    = jump_in_dec
      }
    default:
      id_fsm_d = FIRST_CYCLE
  }
}
```

Notes for the implementer:

- The four arms in `FIRST_CYCLE` are mutually exclusive by decoder
  guarantee (`$onehot0({lsu_req_dec, multdiv_en_dec, branch_in_dec,
  jump_in_dec})`), so any priority encoding that yields the same
  selection for the legal inputs is acceptable.
- `branch_set_raw_d` is consumed by the `branch_set_raw_q` flop next
  cycle. Even though `branch_set_raw_d` itself is a 1-cycle pulse here,
  the flopped `branch_set_raw_q` is what feeds `branch_set` (which is
  what reaches the controller).
- The "outer" `if (instr_executing_spec)` gate means stall flags and
  `branch_set_raw_d` / `jump_set_raw` are all 0 whenever the
  instruction can't speculatively start (e.g., fetch error, controller
  not running).

## Requirements

### Requirement 1: Reset behavior

On `rst_ni` asserted (low) the module MUST reset:

- `id_fsm_q = FIRST_CYCLE`
- `imd_val_q[0] = 34'h0`, `imd_val_q[1] = 34'h0`
- `branch_set_raw_q = 1'b0`
- `branch_jump_set_done_q = 1'b0`
- All other outputs are combinational and follow their reset-input
  driving values (the controller and decoder are reset by their own
  modules).

While `rst_ni` is asserted, `lsu_req_o`, `mult_en_ex_o`, `div_en_ex_o`,
`rf_we_id_o`, `branch_set`, `jump_set`, and `pc_set_o` MUST all be 0.

### Requirement 2: Read-enable gating

`rf_ren_a_o` and `rf_ren_b_o` MUST be the AND of the decoder's raw
`rf_ren_a_dec` / `rf_ren_b_dec` with all of:

- `instr_valid_i`
- `~instr_fetch_err_i`
- `~illegal_insn_o`

That is: read-enables are suppressed for invalid instructions, fetch
errors, and any illegal-instruction case (illegal-decoded, illegal CSR,
illegal DRET, illegal U-mode access).

### Requirement 3: Illegal-instruction aggregation

`illegal_insn_o` MUST equal `instr_valid_i & (illegal_insn_dec |
illegal_csr_insn_i | illegal_dret_insn | illegal_umode_insn)`, where:

- `illegal_dret_insn = dret_insn_dec & ~debug_mode_o` — DRET outside
  debug mode is illegal.
- `illegal_umode_insn = (priv_mode_i != PRIV_LVL_M) & (mret_insn_dec |
  (csr_mstatus_tw_i & wfi_insn_dec))` — MRET in non-M mode is illegal,
  and WFI in non-M mode with mstatus.TW is illegal.

### Requirement 4: ALU operand-A mux (with LSU override)

`alu_operand_a` MUST be selected by `alu_op_a_mux_sel`, which is itself
overridden when the LSU asks for the second-half address:

```
alu_op_a_mux_sel = lsu_addr_incr_req_i ? OP_A_FWD : alu_op_a_mux_sel_dec
```

The mux body MUST select:

| `alu_op_a_mux_sel` | `alu_operand_a`      |
|--------------------|----------------------|
| `OP_A_REG_A`       | `rf_rdata_a_i`       |
| `OP_A_FWD`         | `lsu_addr_last_i`    |
| `OP_A_CURRPC`      | `pc_id_i`            |
| `OP_A_IMM`         | `imm_a`              |
| (default)          | `pc_id_i`            |

Where `imm_a = (imm_a_mux_sel == IMM_A_Z) ? zimm_rs1_type : 32'h0`.
(Under WritebackStage=0, `rf_rdata_a_fwd = rf_rdata_a_i`.)

### Requirement 5: ALU operand-B mux (with LSU override)

`alu_op_b_mux_sel` and `imm_b_mux_sel` MUST be:

```
alu_op_b_mux_sel = lsu_addr_incr_req_i ? OP_B_IMM        : alu_op_b_mux_sel_dec
imm_b_mux_sel    = lsu_addr_incr_req_i ? IMM_B_INCR_ADDR : imm_b_mux_sel_dec
```

Then:

```
alu_operand_b = (alu_op_b_mux_sel == OP_B_IMM) ? imm_b : rf_rdata_b_i
```

The full 7-arm `imm_b` mux (BranchTargetALU=0):

| `imm_b_mux_sel`    | `imm_b`                                      |
|--------------------|----------------------------------------------|
| `IMM_B_I`          | `imm_i_type`                                 |
| `IMM_B_S`          | `imm_s_type`                                 |
| `IMM_B_B`          | `imm_b_type`                                 |
| `IMM_B_U`          | `imm_u_type`                                 |
| `IMM_B_J`          | `imm_j_type`                                 |
| `IMM_B_INCR_PC`    | `instr_is_compressed_i ? 32'h2 : 32'h4`      |
| `IMM_B_INCR_ADDR`  | `32'h4`                                      |
| (default)          | `32'h4`                                      |

### Requirement 6: RF write-data mux and write enable

`rf_wdata_id_o` MUST be selected by `rf_wdata_sel`:

| `rf_wdata_sel` | `rf_wdata_id_o` |
|----------------|-----------------|
| `RF_WD_EX`     | `result_ex_i`   |
| `RF_WD_CSR`    | `csr_rdata_i`   |
| (default)      | `result_ex_i`   |

`rf_we_id_o` MUST equal `rf_we_raw & instr_executing & ~illegal_csr_insn_i`.

### Requirement 7: LSU request derivation

The LSU request strobe and its sidecar signals MUST be:

```
lsu_req_o      = instr_executing ? (data_req_allowed & lsu_req_dec) : 1'b0
lsu_we_o       = lsu_we                       // raw, ungated
lsu_type_o     = lsu_type                     // raw, ungated
lsu_sign_ext_o = lsu_sign_ext                 // raw, ungated
lsu_wdata_o    = rf_rdata_b_i                 // raw, ungated
```

Under WritebackStage=0: `data_req_allowed = instr_first_cycle`. So
`lsu_req_o` is high for exactly one cycle: the FIRST_CYCLE of a
load/store instruction (assuming `instr_executing` is high).

`expecting_load_resp_o` and `expecting_store_resp_o` MUST be asserted
only after that first cycle, while waiting for the response:

```
expecting_load_resp_o  = instr_valid_i & lsu_req_dec & ~instr_first_cycle & ~lsu_we
expecting_store_resp_o = instr_valid_i & lsu_req_dec & ~instr_first_cycle &  lsu_we
```

### Requirement 8: Multdiv intermediate-value register pair

`imd_val_q[2]` MUST be a 2-element vector of 34-bit registers, each
with its own write-enable lane. Each lane:

```
seq @(posedge clk_i, negedge rst_ni):
  if (~rst_ni)              imd_val_q[i] <= 34'h0
  else if (imd_val_we_ex_i[i]) imd_val_q[i] <= imd_val_d_ex_i[i]
  // else hold
```

`imd_val_q_ex_o` MUST be the current value of the pair (continuously).

### Requirement 9: ID-FSM next-state and stall sources

`id_fsm_q` is a 2-state register (`FIRST_CYCLE` / `MULTI_CYCLE`),
updated only when `instr_executing` is asserted. Its next-state
`id_fsm_d` is computed by the comb block whose pseudo-RTL is in the
"Combinational logic blocks" section. The Requirements that MUST hold:

- **Default behavior (no instruction can execute):** if
  `instr_executing_spec` is 0, `id_fsm_d = id_fsm_q`, all `stall_*`
  flags are 0, `branch_set_raw_d = 0`, `jump_set_raw = 0`,
  `branch_not_set = 0`, `perf_branch_o = 0`, `rf_we_raw = rf_we_dec`.
- **FIRST_CYCLE / load-store:** if `lsu_req_dec` is high, `id_fsm_d =
  MULTI_CYCLE` (under WritebackStage=0, regardless of `lsu_req_done_i`).
- **FIRST_CYCLE / multdiv hit:** if `multdiv_en_dec` is high and
  `ex_valid_i` is high (single-cycle MUL fast path), `id_fsm_d =
  FIRST_CYCLE`, `rf_we_raw = rf_we_dec`, `stall_multdiv = 0`.
- **FIRST_CYCLE / multdiv miss:** if `multdiv_en_dec` is high and
  `ex_valid_i` is 0, `id_fsm_d = MULTI_CYCLE`, `rf_we_raw = 0`,
  `stall_multdiv = 1`.
- **FIRST_CYCLE / branch-not-taken:** if `branch_in_dec` and
  `~branch_decision_i`, `id_fsm_d = FIRST_CYCLE`, `stall_branch = 0`,
  `branch_set_raw_d = 0`, `perf_branch_o = 1`.
- **FIRST_CYCLE / branch-taken:** if `branch_in_dec` and
  `branch_decision_i`, `id_fsm_d = MULTI_CYCLE`, `stall_branch = 1`,
  `branch_set_raw_d = 1`, `perf_branch_o = 1`.
- **FIRST_CYCLE / jump:** if `jump_in_dec`, `id_fsm_d = MULTI_CYCLE`,
  `stall_jump = 1`, `jump_set_raw = jump_set_dec`.
- **FIRST_CYCLE / multi-cycle ALU:** if `alu_multicycle_dec`,
  `id_fsm_d = MULTI_CYCLE`, `stall_alu = 1`, `rf_we_raw = 0`.
- **MULTI_CYCLE / retire:** if `multicycle_done` (and `ready_wb_i` —
  pinned 1), `id_fsm_d = FIRST_CYCLE`, all stall flags follow their
  defaults (= 0). For multdiv, `rf_we_raw = rf_we_dec & ex_valid_i`.
- **MULTI_CYCLE / not done:** else, `stall_multdiv = multdiv_en_dec`,
  `stall_branch = branch_in_dec`, `stall_jump = jump_in_dec`.

`stall_id` MUST be `stall_ld_hz | stall_mem | stall_multdiv | stall_jump
| stall_branch | stall_alu`. Under WritebackStage=0, `stall_ld_hz = 0`.

`instr_done` MUST be `~stall_id & ~flush_id & instr_executing`. Under
WritebackStage=0, `instr_id_done_o = instr_done` and `en_wb_o = instr_done`.

### Requirement 10: Branch-set / jump-set pulse generation

The 1-cycle pulses delivered to `controller.branch_set_i` /
`controller.jump_set_i` MUST be:

```
branch_set = branch_set_raw & ~branch_jump_set_done_q
jump_set   = jump_set_raw   & ~branch_jump_set_done_q
```

Under our pinning (BranchTargetALU=0 ⇒ `g_branch_set_flop` arm,
DataIndTiming=0):

```
branch_set_raw = branch_set_raw_q
branch_set_raw_q <= branch_set_raw_d on posedge clk_i (reset to 0)
```

`branch_jump_set_done_q` is a sticky flag tracking whether the current
ID-stage instruction has already fired its 1-cycle set pulse. Its
update is:

```
branch_jump_set_done_d = (branch_set_raw | jump_set_raw | branch_jump_set_done_q) & ~instr_valid_clear_o
```

That is: it sets when either pulse fires, and clears only on
`instr_valid_clear_o` (i.e., when the IF→ID register is being killed,
which happens on retire, branch, or any flush). This guarantees only
the first cycle of each branch/jump reaches the controller, even when
`*_raw` would otherwise oscillate due to `instr_executing_spec` going
high on subsequent cycles.

### Requirement 11: `branch_taken` and `nt_branch_addr_o` constants

Under DataIndTiming=0, `branch_taken = 1'b1` (continuous). It is
forwarded into `decoder_i.branch_taken_i`.

Under BranchPredictor=0, `nt_branch_addr_o = 32'd0` (continuous).

### Requirement 12: First-cycle signal

```
instr_first_cycle      = instr_valid_i & (id_fsm_q == FIRST_CYCLE)
instr_first_cycle_id_o = instr_first_cycle
```

`instr_first_cycle` is also forwarded into `decoder_i.instr_first_cycle_i`.

### Requirement 13: Multdiv enable gating

```
mult_en_id  = instr_executing ? mult_en_dec : 1'b0
div_en_id   = instr_executing ? div_en_dec  : 1'b0
mult_en_ex_o = mult_en_id
div_en_ex_o  = div_en_id
multdiv_ready_id_o = ready_wb_i  // = 1 under WritebackStage=0
```

Note: `mult_sel_ex_o`, `div_sel_ex_o`, `multdiv_operator_ex_o`, and
`multdiv_signed_mode_ex_o` are forwarded RAW from the decoder (no
`instr_executing` gating).

### Requirement 14: CSR pipe-flush + op-enable derivation

```
no_flush_csr_addr = csr_addr_o ∈ {CSR_MSCRATCH, CSR_MEPC}
csr_pipe_flush    = (csr_op_en_o == 1) &&
                    (csr_op_o ∈ {CSR_OP_WRITE, CSR_OP_SET, CSR_OP_CLEAR}) &&
                    ~no_flush_csr_addr
csr_op_en_o       = csr_access_o & instr_executing & instr_id_done_o
```

`csr_pipe_flush` is fed to `controller_i.csr_pipe_flush_i`. Note the
*combinational* dependency: `csr_pipe_flush` depends on `csr_op_en_o`,
which depends on `instr_id_done_o`, which depends on `flush_id`, which
in turn comes from the controller. There is no combinational loop
because `csr_op_en_o` does not feed back into `csr_access_o` — that's
the point of the comment "csr_op_en_o is set when CSR access should
actually happen; csr_access_o is set when CSR access instruction is
present". The implementer should preserve the same ordering.

### Requirement 15: Performance-counter outputs

```
perf_jump_o       = controller_i.perf_jump_o
perf_branch_o     = comb (set in FIRST_CYCLE only when branch_in_dec & instr_executing_spec)
perf_tbranch_o    = controller_i.perf_tbranch_o
perf_dside_wait_o = instr_executing & lsu_req_dec & ~lsu_resp_valid_i        // WritebackStage=0
perf_mul_wait_o   = stall_multdiv & mult_en_dec
perf_div_wait_o   = stall_multdiv & div_en_dec
instr_perf_count_id_o = ~ebrk_insn & ~ecall_insn_dec & ~illegal_insn_dec &
                        ~illegal_csr_insn_i & ~instr_fetch_err_i
```

### Requirement 16: WritebackStage=0 tieoffs and absorbers

Under WritebackStage=0, the following inputs are functionally unused
but MUST still be syntactically connected — wrap them in `let unused_*`
(or equivalent) to satisfy lint:

- `lsu_req_done_i`
- `rf_waddr_wb_i`
- `rf_write_wb_i`
- `outstanding_load_wb_i`
- `outstanding_store_wb_i`
- `rf_wdata_fwd_wb_i`
- `wb_exception` (internal — driven by the controller)
- `id_exception` (internal — driven by the controller)
- `data_ind_timing_i` (only the inert DataIndTiming arm references it)

The corresponding tieoff outputs MUST be:

- `instr_type_wb_o = WB_INSTR_OTHER`
- `stall_wb = 1'b0`
- `rf_rd_a_wb_match_o = 1'b0`
- `rf_rd_b_wb_match_o = 1'b0`
- `bt_a_operand_o = 32'h0`
- `bt_b_operand_o = 32'h0`

## Caller-side rules

These are the cross-module rules that a unit-test of id_stage *cannot*
catch on its own, but that the SoC integration relies on. They are
extracted from the caller (`ibex_core`) and the producer/consumer
neighbours.

### CS-1: `pc_set_o` 1-cycle pulse semantics (consumer-side)

`pc_set_o` is a strict 1-cycle pulse that redirects the IF prefetch.
The IF stage (`ibex_if_stage`) and prefetch buffer expect:

- `pc_set_o = 1` for exactly one clock; same cycle `pc_mux_o` /
  `branch_target_ex_o` carry the redirect target.
- Next cycle, `pc_set_o = 0` (otherwise the prefetch buffer
  double-redirects, leading to a stale IF fetch).

This pulse is sourced from `controller_i.pc_set_o`; from the id_stage
side, the only requirement is **never to override or stretch it**.
`pc_set_o` is a pass-through.

### CS-2: `instr_req_o` is steady-state (consumer-side)

`instr_req_o` is **not** a pulse — it's a level signal driven by the
controller's FSM-state-decoded outputs and held while the controller
wants the prefetch buffer to keep fetching. It is `0` only in
RESET / WAIT_SLEEP / SLEEP. Pass-through; do not gate.

### CS-3: `id_in_ready_o` ↔ `instr_valid_clear_o` relationship

Both come from the controller. The IF→ID register clears on
`instr_valid_clear_o`. The IF stage advances a new instruction into
the IF→ID register on `id_in_ready_o & instr_new_id`. They are
typically asserted together on retire (FIRST_CYCLE retire of a normal
instruction) but they are not the same signal — `instr_valid_clear_o`
also asserts on FLUSH/exception/sleep paths where `id_in_ready_o` does
not. Pass-through both.

### CS-4: `branch_set` / `jump_set` pulse uniqueness

The controller assumes `branch_set_i` and `jump_set_i` are 1-cycle
pulses that fire **at most once per ID-stage instruction**. The
`branch_jump_set_done_q` flop in id_stage is the mechanism that
guarantees this — see Requirement 10. The implementer must NOT
collapse this flop away, even though `branch_set_raw_q` already gives
a 1-cycle width on its own under our pinning: in the WritebackStage=1
path (out of scope) the `branch_set_raw` signal can stretch across
cycles when an outstanding memory access blocks `instr_executing`, and
the dedup flop catches that. For our SoC pinning the dedup flop is
still required because `branch_set_raw_d` could be re-asserted on the
next cycle if `instr_executing_spec` re-asserts before the FSM moves
to MULTI_CYCLE.

### CS-5: `branch_set_raw_q` 2-cycle latency on branches

With BranchTargetALU=0, taken branches have a 2-cycle latency to the
controller. Concretely: in cycle N, `branch_decision_i` arrives from
EX, the FIRST_CYCLE arm sets `branch_set_raw_d = 1` and `stall_branch
= 1`; in cycle N+1, `branch_set_raw_q` is high, so
`branch_set = 1` (assuming `branch_jump_set_done_q` is 0), and the
controller sees the redirect that cycle. The FSM is in MULTI_CYCLE
during cycle N+1, and `multicycle_done = ex_valid_i` returns to 1 (EX
ALU result is single-cycle for branch-target add), so cycle N+2
returns to FIRST_CYCLE. The implementer MUST preserve this 2-cycle
shape — it's load-bearing for the `pc_set_o` ↔ branch-target
synchronization in the EX/IF pair.

### CS-6: `lsu_req_o` rising edge and `multicycle_done` retire

For loads/stores under WritebackStage=0:

- Cycle N (FIRST_CYCLE, `instr_executing` and `lsu_req_dec` high):
  `lsu_req_o = 1`, `data_req_allowed = instr_first_cycle = 1`.
- Cycle N+1 onward (MULTI_CYCLE): `data_req_allowed = 0` (since
  `instr_first_cycle = 0` in MULTI_CYCLE) ⇒ `lsu_req_o = 0`. ID stalls
  on `stall_mem = lsu_req_dec & ~lsu_resp_valid_i` until the LSU
  responds.
- Cycle N+k (LSU `lsu_resp_valid_i = 1`): `multicycle_done = 1`,
  `stall_mem = 0`, `id_fsm_d = FIRST_CYCLE`, `instr_done = 1`. ID
  retires.

The LSU asserts `lsu_resp_valid_i` for 1 cycle on the response. The
`lsu_req_done_i` input is **ignored** under WritebackStage=0 (sunk
into `unused_*`). Do not use it.

### CS-7: `ex_valid_i` semantics

`ex_valid_i` is high when the EX block has a valid result this cycle.
Specifically:

- For ALU (single-cycle), `ex_valid_i = 1` for the cycle of the ALU op.
- For multdiv, `ex_valid_i = 1` only on the cycle the result is final.
  For single-cycle MUL, this is the FIRST_CYCLE; for divides /
  multi-cycle MUL, this is the last cycle of the multdiv loop.
- For loads/stores, `ex_valid_i = 1` is irrelevant — the `multicycle_done`
  expression uses `lsu_resp_valid_i` instead.

`ex_valid_i` falls on the same edge as `id_in_ready_o` (i.e., the
cycle after retire it is 0). The MULTI_CYCLE retire test
`multicycle_done & ready_wb_i` uses `ex_valid_i` for non-LSU paths.

### CS-8: `flush_id` ↔ `instr_valid_clear_o` interaction

`instr_valid_clear_o` is the **only** signal that kills the IF→ID
register from id_stage's perspective; the controller drives it via the
controller's own FSM (FLUSH, IRQ_TAKEN, DBG_TAKEN_*, retiring DECODE).

`flush_id_o` (controller output, internal name `flush_id` here) is
**separate**: it is consumed by id_stage to suppress `instr_done`
(`instr_done = ~stall_id & ~flush_id & instr_executing`). That means
on a flush cycle, id_stage will not retire the in-flight instruction
even if it would otherwise be done — `en_wb_o`, `instr_id_done_o`, and
`csr_op_en_o` all go to 0.

The two signals come from the same controller FSM state (FLUSH
asserts both), but they have different semantics: `flush_id` blocks
retire **this** cycle, `instr_valid_clear_o` clears the IF→ID register
**next** cycle. The implementer must wire both correctly and not
conflate them.

### CS-9: `branch_jump_set_done_q` clears on `instr_valid_clear_o`

`branch_jump_set_done_d` clears only on `instr_valid_clear_o`. This
matters because:

- A branch that retires in MULTI_CYCLE has its
  `instr_valid_clear_o` asserted on the retire cycle (controller
  emits it as part of normal DECODE retire).
- But on a FLUSH (e.g., interrupted mid-branch), the controller also
  asserts `instr_valid_clear_o` in FLUSH state → the dedup flop clears
  before the next instruction enters ID.

The behavior must hold even when `instr_valid_clear_o` overlaps with
`branch_set_raw | jump_set_raw` (in that case the new value is `0 &
~1 = 0`, i.e., the dedup flag does NOT stick — it clears).

### CS-10: `instr_executing` ↔ `id_fsm_q` invariant

`id_fsm_q` updates **only when `instr_executing` is asserted** (the
flop-update guard). Therefore:

- If `instr_executing = 0` for multiple cycles (e.g., controller in
  FLUSH or RESET), `id_fsm_q` is frozen at its last value.
- After reset, `id_fsm_q = FIRST_CYCLE`, so the very first instruction
  that satisfies `instr_executing = 1` will see FIRST_CYCLE.
- The assertion `IbexMoveToFirstCycleWhenIdReady` (`id_in_ready_o |=>
  id_fsm_q == FIRST_CYCLE`) holds because `id_in_ready_o` is asserted
  by the controller only in cycles where retire (or flush) will leave
  the FSM in FIRST_CYCLE next cycle — either via `multicycle_done &
  ready_wb_i` in MULTI_CYCLE, or by being already in FIRST_CYCLE with
  no stalls.

### CS-11: `instr_first_cycle_id_o` consumed by EX block

The EX block (`ex_block_i`) consumes `instr_first_cycle_id_o` as
`alu_instr_first_cycle_i`. It uses this to gate combinational
operations that should only fire on the first cycle of a multi-cycle
instruction. The signal is `instr_valid_i & (id_fsm_q == FIRST_CYCLE)`
— so it goes high together with `instr_valid_i` (when the IF→ID
register has a valid instruction AND the FSM is in FIRST_CYCLE), and
falls when either condition fails.

### CS-12: `imd_val_q_ex_o` round-trip with EX

The intermediate-value pair `imd_val_q[2]` is owned by id_stage but
*driven by* EX (`imd_val_we_ex_i`, `imd_val_d_ex_i` come from
`ex_block_i`). The contract:

- EX asserts `imd_val_we_ex_i[i] = 1` for the cycle in which it wants
  to update lane `i`.
- id_stage flops the new value on the next clock edge.
- `imd_val_q_ex_o` reflects the flopped value continuously.

EX therefore reads back its own write 1 cycle later. The implementer
MUST NOT add bypassing. (This was load-bearing in B1's IbexExBlock.)

### CS-13: `controller_run` gates `instr_executing_spec`

The combinational chain:

```
instr_executing_spec = instr_valid_i & ~instr_fetch_err_i & controller_run    (WritebackStage=0)
instr_executing      = instr_executing_spec
```

`controller_run` is the controller's `controller_run_o` (asserted only
in DECODE). When the controller is in any other state (RESET,
BOOT_SET, FIRST_FETCH, FLUSH, IRQ_TAKEN, WAIT_SLEEP, SLEEP,
DBG_TAKEN_*), `controller_run = 0` ⇒ `instr_executing = 0` ⇒ FSM is
frozen, no stalls fire, no `lsu_req_o`, no RF write, etc. This is what
makes interrupt entry safe: the controller's IRQ_TAKEN state asserts
`flush_id` and clears `controller_run`, freezing id_stage's FSM and
preventing the in-flight instruction from completing.

### CS-14: `nt_branch_mispredict_o` constant `0`

Even though id_stage forwards this from the controller, under
BranchPredictor=0 the controller drives it constant `0`. The
implementer should treat this as a tieoff for the id_stage interface.

### CS-15: `icache_inval_o` may be left dangling externally

`icache_inval_o` is the decoded `fence.i` signal from
`decoder_i.icache_inval_o`. ICache=0 in our SoC, so this output is
unwired by `ibex_core`. The implementer MUST still drive it correctly
(it's exposed as a port); the SV emit can leave the wire dangling at
the SoC level.

## Spec notes

### N-1: 4-arm priority case is `unique case (1'b1) ... endcase`

The `FIRST_CYCLE` body uses SystemVerilog's `unique case (1'b1)`
idiom with a one-hot selector across `lsu_req_dec`, `multdiv_en_dec`,
`branch_in_dec`, `jump_in_dec`. The decoder guarantees mutual
exclusivity (asserted via `IbexMulticycleEnableUnique`). When ARCH-side
the implementer expresses this, any priority encoding (e.g., `if/else
if`) works — but the **default** arm (none of the four asserted, e.g.
plain ALU op) MUST set `id_fsm_d = FIRST_CYCLE` (i.e., stay in
FIRST_CYCLE) and leave the stall flags at their defaults.

### N-2: `g_no_btalu_muxes` ties `bt_*_operand_o` to 0

Don't drop these outputs. They are part of the port contract; the
EX block consumes them but ignores them under BranchTargetALU=0. The
SV uses `assign bt_a_operand_o = '0; assign bt_b_operand_o = '0;` —
mirror this directly.

### N-3: `branch_set_raw_q` flop is **always-write** (no enable)

Unlike the `imd_val_q[i]` lanes (gated by `imd_val_we_ex_i[i]`), the
`branch_set_raw_q` flop and the `branch_jump_set_done_q` flop write
**every** cycle. Their next-state expressions encode the "hold"
behavior themselves (e.g., `branch_jump_set_done_d` includes `|
branch_jump_set_done_q`).

### N-4: `id_fsm_q` flop has an enable

`id_fsm_q` updates only when `instr_executing` is high. This is
*not* the same as the comb block guard `if (instr_executing_spec)` —
`instr_executing` (without `_spec`) is what gates the flop. Under
WritebackStage=0 the two are equal, but the gates are written
separately. The implementer should preserve the structural separation
(reg-side enable on `instr_executing`, comb-side outer guard on
`instr_executing_spec`).

### N-5: Continuous-assign signals vs. always-block signals

The implementer should preserve the SV's distinction between continuous
assigns (`assign foo = ...`) and always-comb-block assigns (`always_comb
... endcase`). In ARCH terms:

- Continuous assigns become module-scope `let` bindings (or the ARCH
  equivalent for combinational outputs).
- always_comb-block signals (the four mux blocks: `alu_operand_a_mux`,
  `immediate_b_mux`, `rf_wdata_id_mux`, and the big FSM next-state
  block) need explicit default initialisations and a multi-arm case.

The FSM next-state block in particular has 9 default assigns at the
top followed by overrides — ARCH's "default first, override later"
idiom matches this directly.

### N-6: `data_ind_timing_i` is wired through but unused

The `data_ind_timing_i` input is consumed in the `g_branch_set_flop` /
`g_sec_branch_taken` arms (DataIndTiming-related). Under our pinning
the input is pinned 0 at the SoC, but it is still a port. The
implementer must accept it (as a `let unused_data_ind_timing_i =
data_ind_timing_i;` absorber) and otherwise ignore it.

### N-7: `lsu_req_done_i` is functionally dead under WritebackStage=0

`lsu_req_done_i` is only meaningful in the WritebackStage=1 path of
the FIRST_CYCLE / load-store arm and in `gen_stall_mem`'s `stall_mem
= ... | (lsu_req_dec & ~lsu_req_done_i)`. Under WritebackStage=0, the
SV explicitly assigns `unused_data_req_done_ex = lsu_req_done_i;` to
satisfy lint. The implementer MUST follow suit — DO NOT use
`lsu_req_done_i` in any logic. Use `lsu_resp_valid_i` for the
multicycle-done test.

### N-8: `multicycle_done` for non-multdiv non-LSU instructions is `ex_valid_i`

For branches, jumps, and `alu_multicycle` instructions, `lsu_req_dec
= 0`, so `multicycle_done = ex_valid_i`. The EX block asserts
`ex_valid_i = 1` on the cycle the result is ready; for branch
target-add, that's the second cycle of the branch (since
`stall_branch` held the FSM in MULTI_CYCLE for one cycle). Read
together with Requirement 9 / CS-5: branches retire in
exactly 2 cycles when taken, 1 cycle when not taken.

### N-9: `branch_jump_set_done_q` clearance on retire is implicit via `instr_valid_clear_o`

There is no explicit reset of `branch_jump_set_done_q` per-instruction
beyond the `instr_valid_clear_o` gate on its `_d`. This works because
**every** retire cycle the controller asserts `instr_valid_clear_o`
(it's part of the normal DECODE retire path). On flush paths it is
also asserted. The implementer should NOT add an extra clear gate.

### N-10: `csr_op_en_o` and `instr_id_done_o` form a combinational bundle

`csr_op_en_o = csr_access_o & instr_executing & instr_id_done_o`. Under
WritebackStage=0, `instr_id_done_o = instr_done = ~stall_id & ~flush_id
& instr_executing`. So `csr_op_en_o` is high only on the retire cycle
of a CSR-access instruction — it's a 1-cycle pulse, not a level. CSR
side-effects (writes/sets/clears) MUST happen on this cycle only.

### N-11: `id_exception` and `wb_exception` are controller outputs absorbed in id_stage

`id_exception` and `wb_exception` are controller outputs (`id_exception_o`
and `wb_exception_o` of `ibex_controller`). Under WritebackStage=0,
`wb_exception_o` is constant 0, and id_stage doesn't use either signal
locally — they're just passed back to the unused-absorber pile. The
implementer should still expose the controller's outputs (they're
declared in the controller port-list) but absorb both on the id_stage
side.

### N-12: `data_req_allowed` is `instr_first_cycle` under WritebackStage=0

This means a load/store gets exactly **one cycle** to issue its
request: the FIRST_CYCLE. After that, the FSM moves to MULTI_CYCLE,
`instr_first_cycle = 0`, `data_req_allowed = 0`, and `lsu_req_o = 0`
(even though `lsu_req_dec` stays high). The LSU, having captured the
request on cycle N, is now responsible for completing it. This is
load-bearing for the LSU — see A9's spec for the receive side.
