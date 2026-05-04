# IbexCore — port contract + behavior

## Module overview

`ibex_core` is the top-level CPU module of the lowRISC Ibex core. Under
the SoC pinning frozen by the C1 proposal it instantiates four
pipeline-stage sub-modules (`ibex_if_stage`, `ibex_id_stage`,
`ibex_ex_block`, `ibex_load_store_unit`, `ibex_wb_stage`) plus the CSR
file (`ibex_cs_registers`, kept upstream-SV) and wires their handshakes,
hazard signals, redirect strobes, exception/IRQ paths, register-file
read/write paths, and external bus / IRQ / debug ports. It also adds a
small amount of glue: a fetch-enable mubi gate, the LSU PMP-mask
collapse, the non-secure LSU-error / RF-write-on-LSU-resp aliases, the
non-ECC RF-read passthrough, the perf-iside-wait pulse, the crash-dump
struct assembly, the alert-output OR-trees, and the core-busy reduction
that drives `core_busy_o`.

Upstream file: `~/github/ibex/rtl/ibex_core.sv` (2023 LoC; ~600
effective under SoC pinning after subtracting the `` `ifdef RVFI ``
block, the `` `ifdef INC_ASSERT `` block, and the secure / PMP / regfile-
ECC / mem-ECC / dummy-instr / lockstep arms).

## Pinned parameter values

This spec is restricted to the parameter values bound by
`soc/ibex_mini_soc.sv` via `ibex_top_tracing` defaults. Branches /
generate arms guarded by their opposite values are out of scope and
are not required to be ported.

| Parameter            | Pinned value          | Effect on this spec |
|----------------------|-----------------------|---------------------|
| `RV32E`              | `1'b0`                | Full 32-entry RF; 5-bit `rf_*addr_*` paths. |
| `RV32M`              | `RV32MFast`           | Multdiv enabled (fast variant); EX block produces `ex_valid_o=0` until multdiv result is ready. |
| `RV32B`              | `RV32BNone`           | No bitmanip arms in EX/ID. |
| `BranchTargetALU`    | `1'b0`                | `bt_a_operand`/`bt_b_operand` driven to `0` by ID; branches/jumps go through the regular ALU. |
| `WritebackStage`     | `1'b0`                | WB stage is passthrough: `ready_wb_o=1`, `rf_write_wb_o=0`, no WB-stage register, no load-to-use hazard logic. |
| `ICache`             | `1'b0`                | `icache_enable`/`icache_inval` are wired but inert; ICache RAM ports tie off through IF stage. |
| `BranchPredictor`    | `1'b0`                | `instr_bp_taken_id`, `nt_branch_mispredict`, `nt_branch_addr` are constant `0` (driven by IF/ID respectively). |
| `DbgTriggerEn`       | `1'b0`                | `trigger_match` from CSRs is `0`. |
| `MemECC`             | `1'b0`                | `MemDataWidth = 32`. `instr_intg_err_o` is `0` from IF; `lsu_load_resp_intg_err`/`lsu_store_resp_intg_err` are `0` from LSU. |
| `DataIndTiming`      | `1'b0` (= `SecureIbex`) | `data_ind_timing` wire is `0` from CSRs; EX/ID DIT arms are inert. |
| `DummyInstructions`  | `1'b0`                | No LFSR; `dummy_instr_id`, `dummy_instr_wb` are `0` from IF / WB respectively. The two top-level outputs `dummy_instr_id_o` and `dummy_instr_wb_o` exist and drive `0`. |
| `PMPEnable`          | `1'b0`                | `g_no_pmp` arm; `pmp_req_err[*] = 0`; PMP-related CSR outputs are sunk to unused. |
| `SecureIbex`         | `1'b0`                | Non-secure variants of `g_core_busy_*`, `g_instr_req_gated_*`, `g_check_mem_response`. `DataIndTiming = 0`, `PCIncrCheck = 0`. |
| `ResetAll`           | `1'b0`                | Async-low reset only on flops with explicit reset values. |
| `RegFileECC`         | `1'b0`                | `gen_no_regfile_ecc` arm: `rf_wdata_wb_ecc_o = rf_wdata_wb`; `rf_rdata_a/b = rf_rdata_a/b_ecc_i`; `rf_ecc_err_comb = 0`. |
| `RV32ZC`             | `RV32ZcaZcbZcmp`      | Forwarded into IF-stage; not consumed at this scope. |
| `MHPMCounterNum`     | `0`                   | Forwarded to CSRs; no effect at this scope. |
| `MHPMCounterWidth`   | `40`                  | Forwarded to CSRs; no effect at this scope. |
| `DmHaltAddr`         | (default `32'h1A11_0800`, SoC overrides to `32'h0000_0000`) | Forwarded into IF stage. |
| `DmExceptionAddr`    | (default `32'h1A11_0808`, SoC overrides to `32'h0000_0000`) | Forwarded into IF stage. |
| `BusSizeECC`         | `BUS_SIZE` (= 32)     | Forwarded into IF stage. |
| `boot_addr_i`        | `32'h0010_0000` (SoC bind) | First fetch address is `{boot_addr[31:8], 8'h80}` = `32'h0010_0080` (per `ibex_if_stage.sv:218`). |

## Ports

The port list mirrors the upstream `ibex_core` declaration excluding:

- the `` `ifdef RVFI `` block (lines 127-166) — **out of scope, do
  not implement** (see Spec note N-1).
- the `` `ifdef INC_ASSERT `` block (lines 980-1047) — sim-only
  assertions.

All ports below cite `ibex_core.sv:LINE`.

### Clock + reset

| Direction | Name      | Type / Width             | Role | Cite |
|-----------|-----------|--------------------------|------|------|
| in        | `clk_i`   | `Clock<SysDomain>`       | System clock (rising-edge sampled). | :59 |
| in        | `rst_ni`  | `Reset<Async, Low>`      | Active-low asynchronous reset. | :60 |

### Hart identity / boot

| Direction | Name           | Type / Width             | Role | Cite |
|-----------|----------------|--------------------------|------|------|
| in        | `hart_id_i`    | `UInt<32>`               | Hart identity; forwarded into CSRs. | :62 |
| in        | `boot_addr_i`  | `UInt<32>`               | Boot/mtvec base; forwarded into IF stage and into CSRs (mtvec init). | :63 |

### Instruction memory interface (OBI)

| Direction | Name              | Type / Width  | Role | Cite |
|-----------|-------------------|---------------|------|------|
| out       | `instr_req_o`     | `Bool`        | Instr-fetch request strobe (forwarded from `if_stage_i.instr_req_o`, gated by `instr_req_gated`). | :66, :454 |
| in        | `instr_gnt_i`     | `Bool`        | Bus grant. Forwarded into IF stage. | :67, :456 |
| in        | `instr_rvalid_i`  | `Bool`        | Instr-read response valid. Forwarded into IF stage. | :68, :457 |
| out       | `instr_addr_o`    | `UInt<32>`    | Instr-fetch byte address (4-byte-aligned). Forwarded from IF stage. | :69, :455 |
| in        | `instr_rdata_i`   | `UInt<32>`    | Instr-read data (`MemDataWidth=32` under MemECC=0). | :70, :458 |
| in        | `instr_err_i`     | `Bool`        | Instr-bus error flag. Forwarded into IF stage as `instr_bus_err_i`. | :71, :459 |

### Data memory interface (OBI)

| Direction | Name              | Type / Width  | Role | Cite |
|-----------|-------------------|---------------|------|------|
| out       | `data_req_o`      | `Bool`        | Data-bus request strobe. Equals `data_req_out & ~pmp_req_err[PMP_D]`; under PMPEnable=0 this is `data_req_out`. | :74, :772 |
| in        | `data_gnt_i`      | `Bool`        | Bus grant. Forwarded into LSU. | :75, :784 |
| in        | `data_rvalid_i`   | `Bool`        | Data-read response valid. Forwarded into LSU. | :76, :785 |
| out       | `data_we_o`       | `Bool`        | Data-bus write-enable. Forwarded from LSU. | :77, :790 |
| out       | `data_be_o`       | `UInt<4>`     | Per-byte enable. Forwarded from LSU. | :78, :791 |
| out       | `data_addr_o`     | `UInt<32>`    | Data-bus byte address. Forwarded from LSU. | :79, :789 |
| out       | `data_wdata_o`    | `UInt<32>`    | Data-bus write data (`MemDataWidth=32`). Forwarded from LSU. | :80, :792 |
| in        | `data_rdata_i`    | `UInt<32>`    | Data-bus read data. Forwarded into LSU. | :81, :793 |
| in        | `data_err_i`      | `Bool`        | Data-bus error. Forwarded into LSU as `data_bus_err_i`. | :82, :786 |

### Register-file interface (RF lives outside ibex_core in ibex_top)

| Direction | Name               | Type / Width             | Role | Cite |
|-----------|--------------------|--------------------------|------|------|
| out       | `dummy_instr_id_o` | `Bool`                   | Equals `dummy_instr_id` from IF stage; pinned `0` under DummyInstructions=0. | :85, :898 |
| out       | `dummy_instr_wb_o` | `Bool`                   | Equals `dummy_instr_wb` from WB stage; pinned `0` under DummyInstructions=0. | :86, :899 |
| out       | `rf_raddr_a_o`     | `UInt<5>`                | RF read-port-A address. | :87, :900 |
| out       | `rf_raddr_b_o`     | `UInt<5>`                | RF read-port-B address. | :88, :903 |
| out       | `rf_waddr_wb_o`    | `UInt<5>`                | RF write-port address (drives RF). Forwarded from WB stage. | :89, :901 |
| out       | `rf_we_wb_o`       | `Bool`                   | RF write-enable (drives RF). Forwarded from WB stage. | :90, :902 |
| out       | `rf_wdata_wb_ecc_o`| `UInt<32>`               | RF write-data (drives RF). Under RegFileECC=0 equals `rf_wdata_wb`. | :91, :950 |
| in        | `rf_rdata_a_ecc_i` | `UInt<32>`               | RF read-port-A data. Under RegFileECC=0 forwarded directly to internal `rf_rdata_a`. | :92, :951 |
| in        | `rf_rdata_b_ecc_i` | `UInt<32>`               | RF read-port-B data. Under RegFileECC=0 forwarded directly to internal `rf_rdata_b`. | :93, :952 |

### ICache RAM interface (off under ICache=0; ports still bind)

| Direction | Name                  | Type / Width                       | Role | Cite |
|-----------|-----------------------|------------------------------------|------|------|
| out       | `ic_tag_req_o`        | `UInt<IC_NUM_WAYS>` (packed)       | Forwarded from IF stage; tied off under ICache=0. | :96, :462 |
| out       | `ic_tag_write_o`      | `Bool`                             | Forwarded from IF stage. | :97, :463 |
| out       | `ic_tag_addr_o`       | `UInt<IC_INDEX_W>`                 | Forwarded from IF stage. | :98, :464 |
| out       | `ic_tag_wdata_o`      | `UInt<TagSizeECC>`                 | Forwarded from IF stage. | :99, :465 |
| in        | `ic_tag_rdata_i`      | `Vec<UInt<TagSizeECC>, IC_NUM_WAYS>` (unpacked) | Forwarded into IF stage. | :100, :466 |
| out       | `ic_data_req_o`       | `UInt<IC_NUM_WAYS>` (packed)       | Forwarded from IF stage. | :101, :467 |
| out       | `ic_data_write_o`     | `Bool`                             | Forwarded from IF stage. | :102, :468 |
| out       | `ic_data_addr_o`      | `UInt<IC_INDEX_W>`                 | Forwarded from IF stage. | :103, :469 |
| out       | `ic_data_wdata_o`     | `UInt<LineSizeECC>`                | Forwarded from IF stage. | :104, :470 |
| in        | `ic_data_rdata_i`     | `Vec<UInt<LineSizeECC>, IC_NUM_WAYS>` (unpacked) | Forwarded into IF stage. | :105, :471 |
| in        | `ic_scr_key_valid_i`  | `Bool`                             | Forwarded into IF stage and into CSRs. | :106, :472, :1137 |
| out       | `ic_scr_key_req_o`    | `Bool`                             | Forwarded from IF stage. | :107, :473 |

### Interrupt inputs (forwarded into CSRs)

| Direction | Name              | Type / Width   | Role | Cite |
|-----------|-------------------|----------------|------|------|
| in        | `irq_software_i`  | `Bool`         | M-mode software IRQ (mip.MSIP). Forwarded into CSRs. | :110, :1098 |
| in        | `irq_timer_i`     | `Bool`         | M-mode timer IRQ (mip.MTIP). Forwarded into CSRs. | :111, :1099 |
| in        | `irq_external_i`  | `Bool`         | M-mode external IRQ (mip.MEIP). Forwarded into CSRs. | :112, :1100 |
| in        | `irq_fast_i`      | `UInt<15>` (packed) | Fast IRQ vector (mip bits 16-30). Forwarded into CSRs. | :113, :1101 |
| in        | `irq_nm_i`        | `Bool`         | Non-maskable IRQ. Forwarded into ID (`controller_i.irq_nm_ext_i`). | :114, :669 |
| out       | `irq_pending_o`   | `Bool`         | Forwarded from CSRs (`irq_pending_o`); fed back into ID's `irq_pending_i`. | :115, :667, :1103 |

### Debug

| Direction | Name                   | Type / Width    | Role | Cite |
|-----------|------------------------|-----------------|------|------|
| in        | `debug_req_i`          | `Bool`          | Halt request. Forwarded into ID (`controller_i.debug_req_i`). | :118, :677 |
| out       | `crash_dump_o`         | `crash_dump_t` (packed struct, 5 × `UInt<32>`) | Aggregated crash-dump record (current_pc, next_pc, last_data_addr, exception_pc, exception_addr). | :119, :961-:965 |
| out       | `double_fault_seen_o`  | `Bool`          | Forwarded from CSRs (`cs_registers_i.double_fault_seen_o`). | :122, :1149 |

### CPU control / alerts

| Direction | Name                       | Type / Width      | Role | Cite |
|-----------|----------------------------|-------------------|------|------|
| in        | `fetch_enable_i`           | `ibex_mubi_t` (`UInt<4>`) | Fetch-enable mubi. Under SecureIbex=0 only bit 0 is consumed; high 3 bits are absorbed by `unused_fetch_enable`. | :170, :545-:549 |
| out       | `alert_minor_o`            | `Bool`            | Equals `icache_ecc_error` (= 0 under ICache=0). | :171, :972 |
| out       | `alert_major_internal_o`   | `Bool`            | Equals `rf_ecc_err_comb \| pc_mismatch_alert \| csr_shadow_err`. Under RegFileECC=0 the first term is `0`. | :172, :975 |
| out       | `alert_major_bus_o`        | `Bool`            | Equals `lsu_load_resp_intg_err \| lsu_store_resp_intg_err \| instr_intg_err`. Under MemECC=0 all three are `0`. | :173, :977 |
| out       | `core_busy_o`              | `ibex_mubi_t` (`UInt<4>`) | `(ctrl_busy \| if_busy \| lsu_busy) ? IbexMuBiOn : IbexMuBiOff` (non-secure form). | :174, :421 |

### RVFI block

**Out of scope, do not implement.** Lines 127-166 of `ibex_core.sv`
declare the RVFI output bundle, gated by `` `ifdef RVFI ``. The
SoC build never defines `RVFI`, the `RISCV_FORMAL` define on line 6
is also unused, and the per-RVFI tracking pipeline (lines 1228+) is
explicitly deferred (proposal Out-of-scope §). See N-1.

## Sub-module instances

The IbexCore body is dominated by five sub-module `inst`s. The
parameter pass-through and port wiring are listed exhaustively here so
the ARCH implementer reproduces the upstream connectivity 1:1.

### `if_stage_i` — `ibex_if_stage` (ARCH `IbexIfStage`, B3)
Cite: `ibex_core.sv:428-:524`.

Parameter pass-through: `DmHaltAddr`, `DmExceptionAddr`,
`DummyInstructions=0`, `ICache=0`, `RV32ZC`, `ICacheECC=0`,
`ICacheTweakInfection=0`, `BusSizeECC`, `TagSizeECC`, `LineSizeECC`,
`PCIncrCheck=0`, `ResetAll=0`, `RndCnstLfsrSeed`, `RndCnstLfsrPerm`,
`BranchPredictor=0`, `MemECC=0`, `MemDataWidth=32`.

Selected internal-signal connections (full list at the cited lines):

| Outer signal           | IF port                      | Direction (IF side) |
|------------------------|------------------------------|---------------------|
| `boot_addr_i`          | `boot_addr_i`                | in                  |
| `instr_req_gated`      | `req_i`                      | in                  |
| `instr_req_o` (top)    | `instr_req_o`                | out                 |
| `instr_addr_o` (top)   | `instr_addr_o`               | out                 |
| `instr_gnt_i` (top)    | `instr_gnt_i`                | in                  |
| `instr_rvalid_i` (top) | `instr_rvalid_i`             | in                  |
| `instr_rdata_i` (top)  | `instr_rdata_i`              | in                  |
| `instr_err_i` (top)    | `instr_bus_err_i`            | in                  |
| `instr_intg_err`       | `instr_intg_err_o`           | out (= 0 under MemECC=0) |
| `ic_*` (top)           | `ic_*`                       | mirror              |
| `instr_valid_id`       | `instr_valid_id_o`           | out → ID            |
| `instr_new_id`         | `instr_new_id_o`             | out (used by RVFI; sink under SoC) |
| `instr_rdata_id`       | `instr_rdata_id_o`           | out → ID            |
| `instr_rdata_alu_id`   | `instr_rdata_alu_id_o`       | out → ID            |
| `instr_rdata_c_id`     | `instr_rdata_c_id_o`         | out → ID            |
| `instr_is_compressed_id` | `instr_is_compressed_id_o` | out → ID            |
| `instr_gets_expanded_id` | `instr_gets_expanded_id_o` | out (RVFI sink)     |
| `instr_expanded_id`    | `instr_expanded_id_o`        | out (RVFI sink)     |
| `instr_bp_taken_id`    | `instr_bp_taken_o`           | out (= 0 under BranchPredictor=0) → ID |
| `instr_fetch_err`      | `instr_fetch_err_o`          | out → ID            |
| `instr_fetch_err_plus2`| `instr_fetch_err_plus2_o`    | out → ID            |
| `illegal_c_insn_id`    | `illegal_c_insn_id_o`        | out → ID            |
| `dummy_instr_id`       | `dummy_instr_id_o`           | out (= 0 under DummyInstructions=0) |
| `pc_if`                | `pc_if_o`                    | out → CSRs (and crash_dump.next_pc) |
| `pc_id`                | `pc_id_o`                    | out → ID/WB/CSRs    |
| `pmp_req_err[PMP_I]`   | `pmp_err_if_i`               | in (= 0 under PMPEnable=0) |
| `pmp_req_err[PMP_I2]`  | `pmp_err_if_plus2_i`         | in (= 0 under PMPEnable=0) |
| `instr_valid_clear`    | `instr_valid_clear_i`        | in (← ID)           |
| `pc_set`               | `pc_set_i`                   | in (← ID)           |
| `pc_mux_id`            | `pc_mux_i`                   | in (← ID)           |
| `nt_branch_mispredict` | `nt_branch_mispredict_i`     | in (= 0 under BranchPredictor=0) |
| `exc_pc_mux_id`        | `exc_pc_mux_i`               | in (← ID)           |
| `exc_cause`            | `exc_cause`                  | in (← ID)           |
| `dummy_instr_*`        | `dummy_instr_*_i`            | in (← CSRs; = 0/0/0/0) |
| `icache_enable`        | `icache_enable_i`            | in (← CSRs)         |
| `icache_inval`         | `icache_inval_i`             | in (← ID)           |
| `icache_ecc_error`     | `icache_ecc_error_o`         | out (= 0 under ICache=0) |
| `branch_target_ex`     | `branch_target_ex_i`         | in (← EX)           |
| `nt_branch_addr`       | `nt_branch_addr_i`           | in (= 0 from ID)    |
| `csr_mepc`             | `csr_mepc_i`                 | in (← CSRs)         |
| `csr_depc`             | `csr_depc_i`                 | in (← CSRs)         |
| `csr_mtvec`            | `csr_mtvec_i`                | in (← CSRs)         |
| `csr_mtvec_init`       | `csr_mtvec_init_o`           | out → CSRs          |
| `id_in_ready`          | `id_in_ready_i`              | in (← ID)           |
| `pc_mismatch_alert`    | `pc_mismatch_alert_o`        | out → alert tree    |
| `if_busy`              | `if_busy_o`                  | out → core_busy mux |

### `id_stage_i` — `ibex_id_stage` (ARCH `IbexIdStage`, B5)
Cite: `ibex_core.sv:556-:718`.

Parameter pass-through: `RV32E=0`, `RV32M=RV32MFast`, `RV32B=RV32BNone`,
`BranchTargetALU=0`, `DataIndTiming=0`, `WritebackStage=0`,
`BranchPredictor=0`, `MemECC=0`.

Connections summary (cite the indicated source lines for the full
binding):

- IF→ID register inputs (`instr_valid_id`, `instr_rdata_id`,
  `instr_rdata_alu_id`, `instr_rdata_c_id`, `instr_is_compressed_id`,
  `instr_bp_taken_id`, `instr_fetch_err`, `instr_fetch_err_plus2`,
  `illegal_c_insn_id`, `pc_id`).
- IF redirect outputs: `instr_valid_clear`, `pc_set`, `pc_mux_id`,
  `nt_branch_mispredict` (= 0), `nt_branch_addr` (= 0), `exc_pc_mux_id`,
  `exc_cause`, `icache_inval`, `instr_req_int`,
  `instr_first_cycle_id`, `id_in_ready`.
- Branch decision input: `branch_decision` (← EX).
- EX-block dispatch: `alu_operator_ex`, `alu_operand_a_ex`,
  `alu_operand_b_ex`, `imd_val_q_ex` (out, fed to EX), `imd_val_d_ex`
  (in, from EX), `imd_val_we_ex` (in, from EX), `bt_a_operand` (= 0),
  `bt_b_operand` (= 0).
- Multdiv dispatch: `mult_en_ex`, `div_en_ex`, `mult_sel_ex`,
  `div_sel_ex`, `multdiv_operator_ex`, `multdiv_signed_mode_ex`,
  `multdiv_operand_a_ex`, `multdiv_operand_b_ex`, `multdiv_ready_id`.
- Stage flow control: `ex_valid` (in, from EX), `lsu_resp_valid` (in,
  from LSU).
- CSR dispatch: `csr_access`, `csr_op`, `csr_addr`, `csr_op_en`,
  `csr_save_if`, `csr_save_id`, `csr_save_wb` (= 0), `csr_restore_mret_id`,
  `csr_restore_dret_id`, `csr_save_cause`, `csr_mtval`, `priv_mode_id`
  (← CSRs), `csr_mstatus_tw` (← CSRs), `illegal_csr_insn_id` (← CSRs),
  `data_ind_timing` (= 0).
- LSU dispatch / response: `lsu_req`, `lsu_we`, `lsu_type`,
  `lsu_sign_ext`, `lsu_wdata`, `lsu_req_done` (← LSU),
  `lsu_addr_incr_req` (← LSU), `lsu_addr_last` (← LSU),
  `lsu_load_err` (← non-secure alias), `lsu_load_resp_intg_err` (= 0),
  `lsu_store_err` (← non-secure alias), `lsu_store_resp_intg_err` (= 0),
  `expecting_load_resp_id`, `expecting_store_resp_id` (sunk to unused
  under SecureIbex=0 — see `ibex_core.sv:887-:891`).
- IRQ / debug: `csr_mstatus_mie`, `irq_pending_o`, `irqs`, `irq_nm_i`,
  `nmi_mode`, `debug_mode`, `debug_mode_entering`, `debug_cause`,
  `debug_csr_save`, `debug_req_i`, `debug_single_step` (← CSRs),
  `debug_ebreakm` (← CSRs), `debug_ebreaku` (← CSRs), `trigger_match`
  (= 0 under DbgTriggerEn=0).
- Result paths: `result_ex` (← EX), `csr_rdata` (← CSRs).
- RF read/write: `rf_raddr_a`, `rf_rdata_a`, `rf_raddr_b`, `rf_rdata_b`,
  `rf_ren_a`, `rf_ren_b`, `rf_waddr_id`, `rf_wdata_id`, `rf_we_id`,
  `rf_rd_a_wb_match` (= 0 under WritebackStage=0), `rf_rd_b_wb_match`
  (= 0), `rf_waddr_wb` (← WB; = 0 under WritebackStage=0),
  `rf_wdata_fwd_wb` (← WB; = 0), `rf_write_wb` (← WB; = 0).
- WB-stage interface: `en_wb`, `instr_type_wb` (= `WB_INSTR_OTHER`),
  `instr_perf_count_id`, `ready_wb` (= 1), `outstanding_load_wb` (= 0),
  `outstanding_store_wb` (= 0).
- Performance counters: `perf_jump`, `perf_branch`, `perf_tbranch`,
  `perf_dside_wait`, `perf_mul_wait`, `perf_div_wait`, `instr_id_done`.

### `ex_block_i` — `ibex_ex_block` (ARCH `IbexExBlock`, B1)
Cite: `ibex_core.sv:723-:766`.

Parameter pass-through: `RV32M=RV32MFast`, `RV32B=RV32BNone`,
`BranchTargetALU=0`.

Connections:

| Outer signal              | EX port                  | Direction (EX side) |
|---------------------------|--------------------------|---------------------|
| `alu_operator_ex`         | `alu_operator_i`         | in                  |
| `alu_operand_a_ex`        | `alu_operand_a_i`        | in                  |
| `alu_operand_b_ex`        | `alu_operand_b_i`        | in                  |
| `instr_first_cycle_id`    | `alu_instr_first_cycle_i`| in                  |
| `bt_a_operand`            | `bt_a_operand_i`         | in (= 0)            |
| `bt_b_operand`            | `bt_b_operand_i`         | in (= 0)            |
| `multdiv_operator_ex`     | `multdiv_operator_i`     | in                  |
| `mult_en_ex`              | `mult_en_i`              | in                  |
| `div_en_ex`               | `div_en_i`               | in                  |
| `mult_sel_ex`             | `mult_sel_i`             | in                  |
| `div_sel_ex`              | `div_sel_i`              | in                  |
| `multdiv_signed_mode_ex`  | `multdiv_signed_mode_i`  | in                  |
| `multdiv_operand_a_ex`    | `multdiv_operand_a_i`    | in                  |
| `multdiv_operand_b_ex`    | `multdiv_operand_b_i`    | in                  |
| `multdiv_ready_id`        | `multdiv_ready_id_i`     | in (= 1 under WritebackStage=0) |
| `data_ind_timing`         | `data_ind_timing_i`      | in (= 0)            |
| `imd_val_we_ex`           | `imd_val_we_o`           | out                 |
| `imd_val_d_ex`            | `imd_val_d_o`            | out                 |
| `imd_val_q_ex`            | `imd_val_q_i`            | in                  |
| `alu_adder_result_ex`     | `alu_adder_result_ex_o`  | out → LSU           |
| `result_ex`               | `result_ex_o`            | out → ID            |
| `branch_target_ex`        | `branch_target_o`        | out → IF            |
| `branch_decision`         | `branch_decision_o`      | out → ID            |
| `ex_valid`                | `ex_valid_o`             | out → ID            |

### `load_store_unit_i` — `ibex_load_store_unit` (ARCH `IbexLoadStoreUnit`, A9)
Cite: `ibex_core.sv:775-:824`.

Parameter pass-through: `MemECC=0`, `MemDataWidth=32`.

Connections:

| Outer signal              | LSU port                  | Direction (LSU side) |
|---------------------------|---------------------------|----------------------|
| `data_req_out`            | `data_req_o`              | out (gated by `~pmp_req_err[PMP_D]` to top `data_req_o`; = `data_req_out` under PMPEnable=0) |
| `data_gnt_i` (top)        | `data_gnt_i`              | in                   |
| `data_rvalid_i` (top)     | `data_rvalid_i`           | in                   |
| `data_err_i` (top)        | `data_bus_err_i`          | in                   |
| `pmp_req_err[PMP_D]`      | `data_pmp_err_i`          | in (= 0 under PMPEnable=0) |
| `data_addr_o` (top)       | `data_addr_o`             | out                  |
| `data_we_o` (top)         | `data_we_o`               | out                  |
| `data_be_o` (top)         | `data_be_o`               | out                  |
| `data_wdata_o` (top)      | `data_wdata_o`            | out                  |
| `data_rdata_i` (top)      | `data_rdata_i`            | in                   |
| `lsu_we`                  | `lsu_we_i`                | in (← ID)            |
| `lsu_type`                | `lsu_type_i`              | in (← ID)            |
| `lsu_wdata`               | `lsu_wdata_i`             | in (← ID)            |
| `lsu_sign_ext`            | `lsu_sign_ext_i`          | in (← ID)            |
| `rf_wdata_lsu`            | `lsu_rdata_o`             | out → WB             |
| `lsu_rdata_valid`         | `lsu_rdata_valid_o`       | out → non-secure RF-write alias |
| `lsu_req`                 | `lsu_req_i`               | in (← ID)            |
| `lsu_req_done`            | `lsu_req_done_o`          | out → ID             |
| `alu_adder_result_ex`     | `adder_result_ex_i`       | in (← EX)            |
| `lsu_addr_incr_req`       | `addr_incr_req_o`         | out → ID             |
| `lsu_addr_last`           | `addr_last_o`             | out → ID, controller, crash_dump |
| `lsu_resp_valid`          | `lsu_resp_valid_o`        | out → ID, WB         |
| `lsu_load_err_raw`        | `load_err_o`              | out → non-secure alias |
| `lsu_load_resp_intg_err`  | `load_resp_intg_err_o`    | out (= 0 under MemECC=0) → alert_major_bus |
| `lsu_store_err_raw`       | `store_err_o`             | out → non-secure alias |
| `lsu_store_resp_intg_err` | `store_resp_intg_err_o`   | out (= 0 under MemECC=0) → alert_major_bus |
| `lsu_busy`                | `busy_o`                  | out → core_busy mux  |
| `perf_load`               | `perf_load_o`             | out → CSRs           |
| `perf_store`              | `perf_store_o`            | out → CSRs           |

### `wb_stage_i` — `ibex_wb_stage` (ARCH `IbexWbStage`, B2)
Cite: `ibex_core.sv:826-:870`.

Parameter pass-through: `ResetAll=0`, `WritebackStage=0`,
`DummyInstructions=0`.

Connections:

| Outer signal              | WB port                       | Direction (WB side) |
|---------------------------|-------------------------------|---------------------|
| `en_wb`                   | `en_wb_i`                     | in                  |
| `instr_type_wb`           | `instr_type_wb_i`             | in (= `WB_INSTR_OTHER`) |
| `pc_id`                   | `pc_id_i`                     | in                  |
| `instr_is_compressed_id`  | `instr_is_compressed_id_i`    | in                  |
| `instr_perf_count_id`     | `instr_perf_count_id_i`       | in                  |
| `ready_wb`                | `ready_wb_o`                  | out (= 1 under WritebackStage=0) |
| `rf_write_wb`             | `rf_write_wb_o`               | out (= 0)           |
| `outstanding_load_wb`     | `outstanding_load_wb_o`       | out (= 0)           |
| `outstanding_store_wb`    | `outstanding_store_wb_o`      | out (= 0)           |
| `pc_wb`                   | `pc_wb_o`                     | out → CSRs          |
| `perf_instr_ret_*`        | `perf_instr_ret_*_o`          | out → CSRs (4 signals: ret_wb, ret_compressed_wb, ret_wb_spec, ret_compressed_wb_spec) |
| `rf_waddr_id`             | `rf_waddr_id_i`               | in                  |
| `rf_wdata_id`             | `rf_wdata_id_i`               | in                  |
| `rf_we_id`                | `rf_we_id_i`                  | in                  |
| `dummy_instr_id`          | `dummy_instr_id_i`            | in                  |
| `rf_wdata_lsu`            | `rf_wdata_lsu_i`              | in                  |
| `rf_we_lsu`               | `rf_we_lsu_i`                 | in (non-secure alias of `lsu_rdata_valid`) |
| `rf_wdata_fwd_wb`         | `rf_wdata_fwd_wb_o`           | out → ID (= 0 under WritebackStage=0) |
| `rf_waddr_wb`             | `rf_waddr_wb_o`               | out → top RF port   |
| `rf_wdata_wb`             | `rf_wdata_wb_o`               | out → top RF port (via ECC bypass) |
| `rf_we_wb`                | `rf_we_wb_o`                  | out → top RF port   |
| `dummy_instr_wb`          | `dummy_instr_wb_o`            | out (= 0)           |
| `lsu_resp_valid`          | `lsu_resp_valid_i`            | in                  |
| `lsu_resp_err`            | `lsu_resp_err_i`              | in                  |
| `instr_done_wb`           | `instr_done_wb_o`             | out (used by RVFI; sink under SoC) |

### `cs_registers_i` — `ibex_cs_registers` (kept upstream-SV, see N-2)
Cite: `ibex_core.sv:1055-:1165`.

Parameter pass-through: `DbgTriggerEn=0`, `DbgHwBreakNum`,
`DataIndTiming=0`, `DummyInstructions=0`, `ShadowCSR=0`, `ICache=0`,
`MHPMCounterNum=0`, `MHPMCounterWidth=40`, `PMPEnable=0`,
`PMPGranularity`, `PMPNumRegions`, `PMPRstCfg`, `PMPRstAddr`,
`PMPRstMsecCfg`, `RV32E=0`, `RV32M=RV32MFast`, `RV32B=RV32BNone`,
`CsrMvendorId`, `CsrMimpId`.

Selected connections (the full set is at the cited lines):

- Identity / boot: `hart_id_i`, `boot_addr_i`.
- Privilege exports: `priv_mode_id_o` (→ ID), `priv_mode_lsu_o` (sunk
  to `unused_priv_lvl_ls` under PMPEnable=0; `ibex_core.sv:1213, 1217`).
- `csr_mtvec_o` (→ IF), `csr_mtvec_init_i` (← IF).
- CSR access port: `csr_access_i`, `csr_addr_i`, `csr_wdata_i` (=
  `alu_operand_a_ex`, see `:1053`), `csr_op_i`, `csr_op_en_i`,
  `csr_rdata_o`.
- IRQ aggregation: `irq_software_i`, `irq_timer_i`, `irq_external_i`,
  `irq_fast_i`, `nmi_mode_i` (← ID), `irq_pending_o` (→ top + ID),
  `irqs_o` (→ ID), `csr_mstatus_mie_o` (→ ID), `csr_mstatus_tw_o`
  (→ ID), `csr_mepc_o` (→ IF + crash_dump.exception_pc),
  `csr_mtval_o` (→ `crash_dump_mtval` → crash_dump.exception_addr).
- PMP outputs: `csr_pmp_cfg_o`, `csr_pmp_addr_o`, `csr_pmp_mseccfg_o`
  (sunk to `unused_csr_pmp_*` under PMPEnable=0;
  `ibex_core.sv:1214-:1220`).
- Debug: `csr_depc_o`, `debug_mode_i`, `debug_mode_entering_i`,
  `debug_cause_i`, `debug_csr_save_i`, `debug_single_step_o`,
  `debug_ebreakm_o`, `debug_ebreaku_o`, `trigger_match_o` (= 0 under
  DbgTriggerEn=0).
- PC stream: `pc_if_i`, `pc_id_i`, `pc_wb_i`.
- Misc CSR-driven signals: `data_ind_timing_o` (= 0), `dummy_instr_*_o`
  (= 0/0/0/0), `icache_enable_o` (= 0 under ICache=0),
  `csr_shadow_err_o` (= 0 under ShadowCSR=0), `ic_scr_key_valid_i`.
- Trap save/restore strobes: `csr_save_if_i`, `csr_save_id_i`,
  `csr_save_wb_i`, `csr_restore_mret_i`, `csr_restore_dret_i`,
  `csr_save_cause_i`, `csr_mcause_i` (= `exc_cause`),
  `csr_mtval_i`, `illegal_csr_insn_o`.
- `double_fault_seen_o` (→ top).
- Performance-counter inputs: `instr_ret_i` (= `perf_instr_ret_wb`),
  `instr_ret_compressed_i`, `instr_ret_spec_i`,
  `instr_ret_compressed_spec_i`, `iside_wait_i` (= `perf_iside_wait`),
  `jump_i`, `branch_i`, `branch_taken_i`, `mem_load_i`, `mem_store_i`,
  `dside_wait_i`, `mul_wait_i`, `div_wait_i`.

## Latched state regs

`ibex_core` itself owns no flops at module scope under our pinning.
All sequential state lives inside the sub-modules (`ibex_if_stage`,
`ibex_id_stage` and its `controller_i`/`decoder_i`, `ibex_ex_block`,
`ibex_load_store_unit`, `ibex_wb_stage`, `ibex_cs_registers`).

The only "near-flop" objects are:

- The `imd_val_q_ex` register pair used by multdiv. Despite the name,
  the actual flops live inside `IbexIdStage`'s `imd_val_q[2]` (B5 spec
  Latched-state-regs §). At the IbexCore level, `imd_val_d_ex`,
  `imd_val_we_ex`, `imd_val_q_ex` are pure wires routed between EX
  (driver of `_d_/_we_`) and ID (driver of `_q_`). See N-3.
- The `pc_at_fetch_disable` / `last_fetch_enable` flops at lines
  1019-1033 are inside the `` `ifdef INC_ASSERT `` block — sim-only,
  out of scope.

## Combinational logic blocks (module-scope glue)

Beyond the sub-module instances, ibex_core has a small number of
top-level combinational assignments that must be reproduced. Each is
a single `assign` upstream; they are listed grouped by purpose.

### Core-busy reduction (Requirement 9)
`ibex_core.sv:421` (g_core_busy_non_secure):
```
core_busy_o = (ctrl_busy | if_busy | lsu_busy) ? IbexMuBiOn : IbexMuBiOff
```
Inputs: `ctrl_busy` (from ID), `if_busy` (from IF), `lsu_busy` (from
LSU). Output: top `core_busy_o`.

### Fetch-enable gating (Requirement 10)
`ibex_core.sv:545-:549` (g_instr_req_gated_non_secure):
```
unused_fetch_enable = ^fetch_enable_i[3:1]
instr_req_gated     = instr_req_int & fetch_enable_i[0]
instr_exec          = fetch_enable_i[0]
```
`instr_req_int` comes from ID (`controller_i.instr_req_o`).
`instr_req_gated` feeds IF's `req_i`. `instr_exec` feeds ID's
`instr_exec_i`.

### iside-wait perf pulse
`ibex_core.sv:528`:
```
perf_iside_wait = id_in_ready & ~instr_valid_id
```
Feeds CSRs' `iside_wait_i`.

### LSU PMP-mask collapse and error reduction
`ibex_core.sv:772-:773`:
```
data_req_o   = data_req_out & ~pmp_req_err[PMP_D]   // = data_req_out under PMPEnable=0
lsu_resp_err = lsu_load_err | lsu_store_err
```

### Non-secure LSU error / RF-write aliases
`ibex_core.sv:880-:891` (g_no_check_mem_response):
```
lsu_load_err  = lsu_load_err_raw
lsu_store_err = lsu_store_err_raw
rf_we_lsu     = lsu_rdata_valid
unused_expecting_load_resp_id  = expecting_load_resp_id   // sink
unused_expecting_store_resp_id = expecting_store_resp_id  // sink
```

### RF passthrough (no ECC)
`ibex_core.sv:946-:953` (gen_no_regfile_ecc):
```
unused_rf_ren_a         = rf_ren_a
unused_rf_ren_b         = rf_ren_b
unused_rf_rd_a_wb_match = rf_rd_a_wb_match
unused_rf_rd_b_wb_match = rf_rd_b_wb_match
rf_wdata_wb_ecc_o = rf_wdata_wb
rf_rdata_a        = rf_rdata_a_ecc_i
rf_rdata_b        = rf_rdata_b_ecc_i
rf_ecc_err_comb   = 1'b0
```

### Top-level RF-port pass-through assigns
`ibex_core.sv:898-:903`:
```
dummy_instr_id_o = dummy_instr_id   // = 0
dummy_instr_wb_o = dummy_instr_wb   // = 0
rf_raddr_a_o     = rf_raddr_a
rf_waddr_wb_o    = rf_waddr_wb
rf_we_wb_o       = rf_we_wb
rf_raddr_b_o     = rf_raddr_b
```

### CSR write-port aliasing
`ibex_core.sv:1053`:
```
csr_wdata = alu_operand_a_ex   // feeds cs_registers_i.csr_wdata_i
```

### Crash-dump struct assembly
`ibex_core.sv:961-:965`:
```
crash_dump_o.current_pc     = pc_id
crash_dump_o.next_pc        = pc_if
crash_dump_o.last_data_addr = lsu_addr_last
crash_dump_o.exception_pc   = csr_mepc
crash_dump_o.exception_addr = crash_dump_mtval   // = csr_mtval_o from CSRs
```

### Alert-output OR trees
`ibex_core.sv:972-:977`:
```
alert_minor_o          = icache_ecc_error                                       // = 0
alert_major_internal_o = rf_ecc_err_comb | pc_mismatch_alert | csr_shadow_err   // = pc_mismatch_alert (other terms = 0)
alert_major_bus_o      = lsu_load_resp_intg_err | lsu_store_resp_intg_err | instr_intg_err  // = 0
```

### PMP tieoffs (g_no_pmp)
`ibex_core.sv:1213-:1225`:
```
unused_priv_lvl_ls    = priv_mode_lsu
unused_csr_pmp_addr   = csr_pmp_addr
unused_csr_pmp_cfg    = csr_pmp_cfg
unused_csr_pmp_mseccfg= csr_pmp_mseccfg
pmp_req_err[PMP_I]    = 1'b0
pmp_req_err[PMP_I2]   = 1'b0
pmp_req_err[PMP_D]    = 1'b0
```

### RVFI sink
`ibex_core.sv:721`:
```
unused_illegal_insn_id = illegal_insn_id   // for RVFI only; absorb under our pinning
```
The `illegal_insn_id` wire from ID is otherwise unused at top scope.

## Requirements (RFC 2119)

The IbexCore implementation SHALL satisfy all of the following. Each
Requirement MUST be reproducible by the implementer from
`ibex_core.sv` plus this spec without consulting any ARCH source.

### Requirement 1: Reset and boot

**R1.** On `~rst_ni`, `ibex_core` SHALL hold all observable outputs
(`instr_req_o`, `data_req_o`, `core_busy_o`, etc.) at their reset
values determined by the sub-module reset behaviors. After
`rst_ni` deasserts, IbexCore SHALL latch `boot_addr_i` (combinationally
forwarded into IF stage and CSRs) and the IF stage SHALL begin
fetching at `{boot_addr_i[31:8], 8'h80}`. CSRs SHALL initialise
`mtvec` from `boot_addr_i` on the first `csr_mtvec_init` strobe from
IF.

- *Given* the SoC binds `boot_addr_i = 32'h0010_0000`, *when* `rst_ni`
  rises, *then* the first `instr_addr_o` value SHALL be
  `32'h0010_0080` (`ibex_core.sv:63, :450, :517` and
  `ibex_if_stage.sv:218`).
- *Given* the IF-stage asserts `csr_mtvec_init_o` during the first
  PC_BOOT update, *when* CSRs see `csr_mtvec_init_i = 1`, *then*
  CSRs SHALL initialise `mtvec` (`ibex_core.sv:517, :1086`).

### Requirement 2: Stage instantiation and parameter pinning

**R2.** IbexCore SHALL instantiate exactly five sub-modules
(`if_stage_i`, `id_stage_i`, `ex_block_i`, `load_store_unit_i`,
`wb_stage_i`) plus `cs_registers_i` (kept upstream-SV per N-2). Each
sub-module SHALL be parameterised as listed in the "Sub-module
instances" section above; the pinned values from the SoC SHALL flow
through unchanged.

- *Given* `WritebackStage=0`, *when* `wb_stage_i` is instantiated,
  *then* its `ready_wb_o` SHALL be `1` and `rf_write_wb_o` SHALL be
  `0` for all cycles, and `rf_wdata_fwd_wb_o = 0`
  (`ibex_core.sv:828` and `ibex_wb_stage.sv:31, :33, :50`).
- *Given* `RV32M=RV32MFast`, *when* `ex_block_i` is instantiated,
  *then* multdiv arms inside EX are active (`ibex_core.sv:724`).

### Requirement 3: IF→ID handshake

**R3.** Instructions SHALL flow IF→ID via the IF stage's
`instr_valid_id_o` / `instr_rdata_id_o` register pair, gated by
ID's `id_in_ready_o`. The IF stage SHALL pop the IF→ID register on
`instr_valid_clear_i` (driven by ID's `instr_valid_clear_o`) and SHALL
hold the IF→ID register otherwise.

- *Given* IF has fetched a 32-bit instruction and stored it in the
  IF→ID register, *when* ID asserts `id_in_ready_o = 1` while IF holds
  `instr_valid_id_o = 1`, *then* ID consumes the instruction within
  the next cycle and IF advances (`ibex_core.sv:476, :520, :587`).
- *Given* ID asserts `instr_valid_clear_o = 1` (e.g. taken branch /
  exception / debug entry), *when* the IF stage observes
  `instr_valid_clear_i = 1`, *then* IF SHALL drop `instr_valid_id_o`
  to `0` for the next cycle (`ibex_core.sv:495, :586`).

### Requirement 4: ID→EX dispatch

**R4.** ID SHALL drive ALU/multdiv operands and operator codes
combinationally to EX in the FIRST_CYCLE of each instruction; EX
returns `result_ex` and `branch_decision` combinationally
(single-cycle ALU) or after multiple cycles (multdiv). EX's
`alu_adder_result_ex_o` SHALL flow combinationally into the LSU's
`adder_result_ex_i`.

- *Given* a non-multdiv non-LSU ALU instruction, *when* ID dispatches
  it, *then* `ex_valid` SHALL be `1` in the same cycle (single-cycle
  ALU; `ibex_core.sv:605, :765`) and ID SHALL retire it in the FIRST_CYCLE
  (B5 R9).
- *Given* a load or store instruction, *when* ID asserts `lsu_req_o`
  and the LSU consumes `alu_adder_result_ex` as the byte address,
  *then* the LSU SHALL drive `data_addr_o = adder_result_ex_i` for
  the bus request (`ibex_core.sv:759, :806`).

### Requirement 5: EX→ID multdiv intermediate-state feedback

**R5.** For multi-cycle multdiv operations, EX SHALL drive
`imd_val_d_o[2]` and `imd_val_we_o[2]` combinationally each cycle.
ID's flop pair `imd_val_q[2]` (per-lane) SHALL be updated when the
corresponding write-enable is `1` and SHALL otherwise hold; the
flopped value SHALL be re-presented to EX as `imd_val_q_i[2]` next
cycle. The flop ownership belongs to ID; ibex_core only routes the
three signals across stages.

- *Given* a `mulh*` or `div*` instruction in EX, *when* multdiv asserts
  `imd_val_we_o[k] = 1`, *then* the next cycle's `imd_val_q_i[k]` value
  SHALL equal the previous cycle's `imd_val_d_o[k]`
  (`ibex_core.sv:202-:204, :612-:614, :754-:756`).
- *Given* multdiv is mid-computation, *when* `ex_valid_o` stays `0`,
  *then* ID SHALL stay in MULTI_CYCLE and SHALL keep dispatching the
  same operand pair to EX (B5 R9; `ibex_core.sv:765`).

### Requirement 6: Branch / jump redirect (PC set)

**R6.** Branch and jump redirects SHALL flow EX → ID → IF as follows:
EX produces `branch_decision` (taken/not-taken) and `branch_target_ex`;
ID's controller asserts `pc_set_o` and selects `pc_mux_o` to
`PC_JUMP`/`PC_EXC`/`PC_ERET`/etc.; the IF stage on observing
`pc_set_i = 1` SHALL drop the in-flight prefetch and start a new
fetch from the muxed PC.

- *Given* a taken conditional branch in EX, *when* `branch_decision = 1`
  and ID asserts `pc_set = 1` with `pc_mux_id = PC_JUMP`, *then* IF
  SHALL fetch from `branch_target_ex` next cycle and SHALL drive
  `instr_valid_clear` to clear in-flight ID instructions
  (`ibex_core.sv:510, :582, :590-:591, :763`).
- *Given* `BranchPredictor = 0`, `nt_branch_mispredict` and
  `nt_branch_addr` SHALL be `0` for all cycles (driven so by ID's
  `g_n_calc_nt_addr` arm; `ibex_core.sv:498, :511, :592-:593`).

### Requirement 7: Multdiv stall

**R7.** While a multi-cycle multdiv operation is in flight, EX SHALL
hold `ex_valid_o = 0`, ID SHALL hold `id_in_ready_o = 0` (it stays in
MULTI_CYCLE), and IF SHALL stall (no IF→ID register pop). When EX
finally asserts `ex_valid_o = 1`, ID SHALL retire the multdiv in the
same cycle and accept the next instruction the following cycle.

- *Given* a `div` instruction reaches EX, *when* multdiv asserts
  `ex_valid_o = 0` for N cycles, *then* `instr_valid_id` SHALL hold
  the same value across all N cycles, no new IF→ID register pop SHALL
  occur, and ID SHALL not advance (`ibex_core.sv:605, :587, :765`).
- *Given* the same instruction, *when* multdiv finally asserts
  `ex_valid_o = 1`, *then* ID SHALL set `id_in_ready_o = 1` in the
  same cycle (B5 R9) and the IF→ID register SHALL update next cycle.

### Requirement 8: LSU stall and response routing

**R8.** Load / store instructions SHALL be dispatched from ID via
`lsu_req_o`/`lsu_we_o`/`lsu_type_o`/`lsu_sign_ext_o`/`lsu_wdata_o`.
The LSU SHALL drive `lsu_req_done_o` when the bus request is granted
(possibly after multiple cycles for misaligned 2-beat accesses) and
`lsu_resp_valid_o` when the read response or store completion lands.
Loaded data SHALL flow LSU → WB via `rf_wdata_lsu` and SHALL be
written into the RF via the WB-stage write port (`rf_we_lsu`,
`rf_we_wb`).

- *Given* a load instruction, *when* ID dispatches and the LSU sees
  `lsu_req_i = 1`, *then* the LSU SHALL drive `data_req_o = 1` and
  `data_we_o = 0` until `data_gnt_i = 1`; one or more cycles later the
  LSU SHALL drive `lsu_resp_valid_o = 1` exactly once and present the
  zero/sign-extended `lsu_rdata_o`. ID SHALL retire the load on the
  cycle of `lsu_resp_valid_i = 1` (`ibex_core.sv:606, :812`).
- *Given* a misaligned 4-byte load, *when* the LSU performs two bus
  beats, *then* `lsu_addr_incr_req_o` SHALL be `1` for the second
  beat, ID's operand-A mux SHALL select `OP_A_FWD` to forward
  `lsu_addr_last`, and `data_addr_o` SHALL increment to the second
  word boundary (`ibex_core.sv:654-:655, :808-:809`).
- *Given* a load fault, *when* the LSU sees a bus error
  (`data_err_i = 1` during the response), *then* it SHALL drive
  `load_err_o = 1`. Under SecureIbex=0 the alias `lsu_load_err =
  lsu_load_err_raw` flows directly into the controller
  (`ibex_core.sv:815, :881`).

### Requirement 9: Core-busy reduction

**R9.** Under SecureIbex=0, `core_busy_o` SHALL equal `IbexMuBiOn` if
any of `ctrl_busy`, `if_busy`, `lsu_busy` is high, and SHALL equal
`IbexMuBiOff` otherwise. The reduction is one combinational OR.

- *Given* the controller is in WAIT_SLEEP/SLEEP and IF/LSU are idle,
  *when* `ctrl_busy = 0`, `if_busy = 0`, `lsu_busy = 0`, *then*
  `core_busy_o = IbexMuBiOff` (`ibex_core.sv:421`).
- *Given* any of the three busy signals is high in any cycle, *when*
  read combinationally, *then* `core_busy_o = IbexMuBiOn` in the same
  cycle (`ibex_core.sv:421`).

### Requirement 10: Fetch-enable gating

**R10.** Under SecureIbex=0, only `fetch_enable_i[0]` SHALL be
consumed. The IF stage's `req_i` SHALL be `instr_req_int &
fetch_enable_i[0]`; the ID stage's `instr_exec_i` SHALL be
`fetch_enable_i[0]`. Bits `[3:1]` of `fetch_enable_i` SHALL be
absorbed into a lint sink (`unused_fetch_enable = ^fetch_enable_i[3:1]`).

- *Given* the SoC binds `fetch_enable_i = IbexMuBiOn (4'b0101)`, *when*
  read combinationally, *then* `fetch_enable_i[0] = 1` and IF receives
  un-gated `req_i = instr_req_int` (`ibex_core.sv:548-:549`).
- *Given* `fetch_enable_i[0]` falls to `0`, *when* read in the same
  cycle, *then* IF's `req_i` SHALL fall and the IF stage SHALL stop
  issuing new fetches (`ibex_if_stage.sv:39`).

### Requirement 11: CSR access path

**R11.** ID SHALL drive `csr_access`, `csr_op`, `csr_addr`, and the
strobe `csr_op_en` (combinational, equals `csr_access &
instr_executing & instr_id_done`). The CSRs SHALL accept the access
on `csr_op_en = 1`, return `csr_rdata` combinationally for ID's RF
write-mux, and SHALL drive `illegal_csr_insn_id` if the access is
illegal. The CSR write data is `csr_wdata = alu_operand_a_ex`
(continuous).

- *Given* a `csrrw` instruction in ID, *when* the controller deems
  `instr_executing = 1`, *then* `csr_access = 1`, `csr_op = CSR_OP_WRITE`,
  `csr_addr` indexes the target CSR, and after retire `csr_op_en = 1`
  for one cycle (`ibex_core.sv:630-:633, :1090-:1094`).
- *Given* `csr_op_en = 1`, *when* CSRs detect an illegal CSR (write to
  RO, missing privilege, unimplemented), *then* `illegal_csr_insn_id =
  1` SHALL flow back to ID and ID SHALL escalate via `illegal_insn_o`
  to the controller (B5 spec; `ibex_core.sv:643, :1147`).

### Requirement 12: CSR-driven exception entry (synchronous)

**R12.** When ID's controller detects a synchronous exception
(illegal instr, ECALL, EBREAK, instr fetch err, LSU fault), it SHALL
drive `csr_save_*` (one of `csr_save_if`, `csr_save_id`, `csr_save_wb`),
`csr_save_cause`, `exc_cause`, and `csr_mtval` and SHALL assert
`pc_set` with `pc_mux = PC_EXC` and `exc_pc_mux = EXC_PC_EXC`. CSRs
SHALL latch `mepc`, `mcause`, `mtval` accordingly. IF SHALL fetch from
`csr_mtvec` next cycle.

- *Given* a load access fault from the LSU, *when* the controller
  takes the exception, *then* `csr_save_cause = 1`, `exc_cause =
  ExcCauseLoadAccessFault`, `csr_mtval = lsu_addr_last`,
  `pc_set = 1`, `pc_mux = PC_EXC`, and IF redirects to
  `csr_mtvec` next cycle (`ibex_core.sv:594-:595, :639-:640, :516,
  :1145-:1146` plus `ibex_pkg.sv:357`).
- *Given* an `ecall` from M-mode, *when* the controller commits it,
  *then* `exc_cause = ExcCauseEcallMMode`, `csr_save_id = 1`, and the
  same redirect sequence as above (`ibex_pkg.sv:363`).

### Requirement 13: Asynchronous interrupt entry

**R13.** CSRs SHALL aggregate `irq_software_i`, `irq_timer_i`,
`irq_external_i`, `irq_fast_i[14:0]` into `irqs_o` (an `irqs_t`
struct) and a single-bit `irq_pending_o`. ID's controller SHALL
sample `irq_pending_i` and `csr_mstatus_mie_i` and SHALL transition
to IRQ_TAKEN when an enabled IRQ is pending and the pipeline is
quiescent. NMI takes priority over maskable IRQs and is not gated by
mstatus.MIE.

- *Given* `csr_mstatus_mie = 1`, `irq_timer_i = 1`, no other IRQ,
  *when* the controller is in DECODE, *then* `irq_pending_o = 1`,
  `exc_pc_mux = EXC_PC_IRQ`, `pc_set = 1`, and `csr_mcause` reflects
  `ExcCauseIrqTimerM` (`ibex_core.sv:1099, :1103, :594-:595, :1145`
  plus `ibex_pkg.sv:342-:343`).
- *Given* `irq_nm_i = 1`, *when* read, *then* the controller SHALL
  enter NMI handling regardless of `csr_mstatus_mie`, drive
  `nmi_mode = 1`, and use `ExcCauseIrqNm`
  (`ibex_core.sv:114, :669, :670, :1102` plus `ibex_pkg.sv:346-:347`).

### Requirement 14: Debug entry / WFI / dret

**R14.** When `debug_req_i = 1` (and the controller is not already in
debug mode), the controller SHALL transition to DBG_TAKEN_IF (or
DBG_TAKEN_ID), assert `pc_set` with `pc_mux = PC_EXC` and `exc_pc_mux
= EXC_PC_DBD`, drive `debug_csr_save = 1`, latch `debug_cause =
DBG_CAUSE_HALTREQ`, and CSRs SHALL save `dpc`. After `dret` from
debug, CSRs SHALL drive `csr_depc` to IF (via `pc_mux = PC_DRET`) and
`csr_restore_dret_id = 1`.

- *Given* `debug_req_i = 1` while running, *when* the controller
  takes it, *then* `debug_mode = 1` next cycle, `csr_depc` is updated
  to the saved PC, and IF SHALL fetch from the DM halt address
  (`ibex_core.sv:118, :515, :673-:677, :1116, :1119`).
- *Given* a `wfi` instruction in M-mode, *when* the pipeline drains
  and no IRQ is pending, *then* `ctrl_busy` SHALL fall to `0`,
  `if_busy` SHALL fall to `0`, `lsu_busy` SHALL fall to `0`, and
  `core_busy_o = IbexMuBiOff` (`ibex_core.sv:421`).
- *Given* `dret` while in debug mode, *when* the controller commits
  it, *then* `csr_restore_dret_id = 1`, `pc_set = 1`,
  `pc_mux = PC_DRET`, and IF fetches from `csr_depc`
  (`ibex_core.sv:638, :515, :1143`).

### Requirement 15: WritebackStage = 0 — no load-to-use hazard

**R15.** Under WritebackStage=0, ibex_core SHALL NOT contain
load-to-use forwarding logic at the top scope. ID writes the RF
directly via `rf_we_id` / `rf_wdata_id`; the LSU's load result
arrives at WB via `rf_wdata_lsu` and is muxed to the RF write-port
via WB-stage's internal mux. The WB-stage's outputs `ready_wb_o = 1`,
`rf_write_wb_o = 0`, `outstanding_load_wb_o = 0`,
`outstanding_store_wb_o = 0`, `rf_wdata_fwd_wb_o = 0` are constants.

- *Given* a `lw` instruction immediately followed by a dependent
  ALU instruction, *when* the LSU's `lsu_resp_valid` lands, *then* ID
  SHALL retire both back-to-back without any load-to-use forwarding
  bypass — the dependent instruction reads `rf_rdata_*` directly
  (load-use hazard absent because ID stalls until the LSU response
  arrives; `ibex_core.sv:606, :812, :883`).
- *Given* `WritebackStage=0`, *when* `wb_stage_i.ready_wb_o` is read,
  *then* it SHALL be `1` for all cycles (B2 spec; `ibex_core.sv:828`).

### Requirement 16: RF read/write routing (no ECC)

**R16.** Under RegFileECC=0, RF read data flows
`rf_rdata_*_ecc_i → rf_rdata_*` straight (no decoder). RF write data
flows `rf_wdata_wb → rf_wdata_wb_ecc_o` straight (no encoder).
`rf_ecc_err_comb` SHALL be `0`. The four match wires `rf_ren_a`,
`rf_ren_b`, `rf_rd_a_wb_match`, `rf_rd_b_wb_match` SHALL be absorbed
into `unused_*` lint sinks at module scope.

- *Given* a register read, *when* the RF presents `rf_rdata_a_ecc_i`,
  *then* `rf_rdata_a` immediately equals it (`ibex_core.sv:951`).
- *Given* a write retire, *when* WB drives `rf_wdata_wb`, *then*
  `rf_wdata_wb_ecc_o` immediately equals it (`ibex_core.sv:950`).

### Requirement 17: Crash-dump aggregation

**R17.** `crash_dump_o` SHALL be a packed struct with five fields,
populated combinationally from sub-module outputs and from CSRs.

- *Given* the field set, *when* read, *then* `current_pc = pc_id`,
  `next_pc = pc_if`, `last_data_addr = lsu_addr_last`, `exception_pc
  = csr_mepc`, `exception_addr = crash_dump_mtval` (= the CSRs'
  `csr_mtval_o`) (`ibex_core.sv:961-:965, :1108`).

### Requirement 18: Alert outputs

**R18.** Under our pinning the three alert outputs SHALL reduce to:

- `alert_minor_o = icache_ecc_error` (= 0 under ICache=0).
- `alert_major_internal_o = rf_ecc_err_comb | pc_mismatch_alert |
  csr_shadow_err`. Under RegFileECC=0 the first term is `0`; under
  ShadowCSR=0 the third term is `0`; only `pc_mismatch_alert` (from
  IF stage's PCIncrCheck arm — itself `0` because PCIncrCheck=0 under
  SecureIbex=0) can be non-zero. Net effect: this output is `0` under
  the SoC pinning.
- `alert_major_bus_o = lsu_load_resp_intg_err | lsu_store_resp_intg_err
  | instr_intg_err`. Under MemECC=0 all three terms are `0`, so the
  output is `0`.

Although the alert outputs reduce to `0` in our pinning, the
implementer SHALL still wire the OR-trees to the source signals so
the reduction is structural, not constant-folded — this preserves
upstream's port semantics for waveform debug and any future relaxation
of the pinning.

- *Given* the three alert outputs, *when* read in any cycle of normal
  operation under our pinning, *then* all three SHALL be `0`
  (`ibex_core.sv:972-:977`).

### Requirement 19: Performance-counter wire pass-through

**R19.** ibex_core SHALL aggregate the per-cycle perf-pulse signals
from sub-modules and pass them into the CSRs' performance-counter
inputs. The pulses originate as follows:

- `perf_iside_wait` (ibex_core glue, line 528): `id_in_ready &
  ~instr_valid_id`.
- `perf_jump`, `perf_branch`, `perf_tbranch`, `perf_dside_wait`,
  `perf_mul_wait`, `perf_div_wait`: from ID stage.
- `perf_load`, `perf_store`: from LSU.
- `perf_instr_ret_wb`, `perf_instr_ret_compressed_wb`,
  `perf_instr_ret_wb_spec`, `perf_instr_ret_compressed_wb_spec`: from
  WB stage.

These wires SHALL be passed unchanged into `cs_registers_i.{instr_ret_i,
instr_ret_compressed_i, instr_ret_spec_i,
instr_ret_compressed_spec_i, iside_wait_i, jump_i, branch_i,
branch_taken_i, mem_load_i, mem_store_i, dside_wait_i, mul_wait_i,
div_wait_i}`.

- *Given* a taken branch retires in EX, *when* ID drives `perf_branch
  = 1` and `perf_tbranch = 1` for one cycle, *then* CSRs receive both
  pulses simultaneously and SHALL increment the corresponding
  hpmcounters (`ibex_core.sv:712-:713, :1158-:1159`). The actual
  counter logic lives inside `ibex_cs_registers`; ibex_core only
  routes the increment pulses.

### Requirement 20: PMP tieoffs (g_no_pmp arm)

**R20.** Under PMPEnable=0, ibex_core SHALL emit:

- `pmp_req_err[PMP_I] = 0`, `pmp_req_err[PMP_I2] = 0`,
  `pmp_req_err[PMP_D] = 0` (these feed IF and the LSU PMP-mask
  collapse).
- Lint sinks for `priv_mode_lsu`, `csr_pmp_addr`, `csr_pmp_cfg`,
  `csr_pmp_mseccfg` (CSRs drive these but no consumer exists).

It SHALL NOT instantiate `ibex_pmp` (`ibex_core.sv:1211-:1226`).

### Requirement 21: Non-secure mem-response aliases

**R21.** Under SecureIbex=0, ibex_core SHALL alias the LSU's raw
error / valid signals through directly:

- `lsu_load_err = lsu_load_err_raw`,
- `lsu_store_err = lsu_store_err_raw`,
- `rf_we_lsu = lsu_rdata_valid`.

The "expecting" probes `expecting_load_resp_id` /
`expecting_store_resp_id` from ID SHALL be sunk into `unused_*`
absorbers — they exist for the SecureIbex=1 mem-response check
that's out of scope here.

- *Given* the LSU drives `lsu_rdata_valid_o = 1` for one cycle, *when*
  the alias is taken, *then* `rf_we_lsu = 1` for one cycle and the
  WB stage pops it onto `rf_wdata_wb`/`rf_we_wb`
  (`ibex_core.sv:883`).
- *Given* the controller is in any state, *when* a stale or
  mis-targeted bus response would arrive, *then* the non-secure path
  SHALL trust the bus protocol and not filter the response — see
  CS-3 below for the producer-side caller obligation
  (`ibex_core.sv:879-:891`).

## Integration constraints

These constraints span the IbexCore boundary and the SoC / sub-module
modules. They are required because unit tests of the IbexCore module
in isolation cannot demonstrate them (they depend on partner-module
behaviour). Per `feedback_unit_tests_dont_catch_integration.md`, the
implementer MUST treat these as first-class checks; missing one of
them is the kind of bug ISR-level regressions catch.

### Caller-side (CS-N)

**CS-1: `boot_addr_i` MUST be valid before `rst_ni` deasserts and
MUST be byte-aligned to 256.** The IF stage forms the boot fetch as
`{boot_addr_i[31:8], 8'h80}`; the upstream `IbexBootAddrUnaligned`
assertion (`ibex_if_stage.sv:831`) checks `boot_addr_i[7:0] == 8'h00`.
The SoC binds `boot_addr_i = 32'h0010_0000` constant, satisfying the
constraint trivially. Cite `ibex_if_stage.sv:218, :831`.

**CS-2: OBI instr-bus protocol — `instr_gnt_i` for a request, then
`instr_rvalid_i` later.** Once `instr_req_o = 1`, the SoC SHALL
return `instr_gnt_i = 1` in some cycle (no required latency); after
the grant, `instr_rvalid_i = 1` SHALL eventually arrive with valid
`instr_rdata_i`. Multiple requests can be outstanding (the IF stage's
prefetch buffer keeps a counter). Cite `ibex_if_stage.sv:42-:48`,
SoC `ibex_mini_soc.sv:127, :172-:179`.

**CS-3: OBI data-bus protocol — `data_gnt_i` for a request, then
`data_rvalid_i` later.** Same shape as CS-2 but for the data port.
The LSU expects exactly one `data_rvalid_i = 1` per accepted request.
Under SecureIbex=0 the core does NOT check that responses match
outstanding requests (the `g_check_mem_response` arm is dropped); the
SoC MUST guarantee response-to-request correspondence. Cite
`ibex_load_store_unit.sv:25-:35` and `ibex_core.sv:879-:891`.

**CS-4: `irq_*_i` levels MUST be sticky until acknowledged.** The
controller samples IRQ lines in the IRQ_TAKEN transition; the CSRs'
`mip` follows the input lines combinationally for the four standard
M-mode IRQs. The SoC's CLINT/PLIC SHALL hold the line high until the
ISR clears the source. Cite `ibex_cs_registers.sv` (kept upstream) and
`ibex_core.sv:1098-:1101`.

**CS-5: `irq_nm_i` (NMI) MUST remain asserted for at least one core
clock and SHALL be handled at the next instruction boundary.** The
controller's NMI path samples it in DECODE / FLUSH and uses
`ExcCauseIrqNm`. The SoC binds `irq_nm_i = 1'b0` (no NMI source); if
this changes, the caller is responsible for the latching. Cite
`ibex_core.sv:114, :669` and `ibex_pkg.sv:346-:347`.

**CS-6: `debug_req_i` MUST remain asserted until the core enters
debug mode.** The controller samples it in DECODE and transitions to
DBG_TAKEN_IF/ID; if the request drops before the transition, the
core may miss the entry. The SoC binds `debug_req_i = 1'b0` (no
debug source); if a debug module is added later, the caller is
responsible for level-holding the request. Cite
`ibex_core.sv:118, :677`.

**CS-7: `fetch_enable_i` SHALL be `IbexMuBiOn` to allow execution.**
Under SecureIbex=0 only `[0]` is consumed; the SoC binds the literal
`IbexMuBiOn = 4'b0101` (line 526 of mini_soc), so `[0]=1`. The
remaining bits do not matter under non-secure pinning. Cite
`ibex_core.sv:170, :548-:549` and `ibex_mini_soc.sv:526`.

**CS-8: External RF `rf_rdata_*_ecc_i` MUST present read data
combinationally.** The RF lives outside IbexCore (in `ibex_top`'s
`gen_regfile_*` arms); the read is registered (the RF flop array is
clocked by `clk_i`), but `rf_rdata_*_ecc_i` is a direct read of the
flop array — i.e. it tracks `rf_raddr_*_o` with combinational
latency. The ID stage's operand mux feeds `rf_rdata_*` directly into
`alu_operand_*_ex` in the same cycle. Cite `ibex_core.sv:687-:692,
:951-:952`.

**CS-9: External RF `rf_wdata_wb_ecc_o` / `rf_we_wb_o` /
`rf_waddr_wb_o` MUST be sampled on the rising edge with the same
clock.** The WB stage's write port outputs are flops in the WB stage
(WritebackStage=0 ⇒ direct combinational pass from ID); the RF
captures them on the next rising edge. Cite `ibex_core.sv:89-:91,
:849-:862, :901-:902`.

**CS-10: SoC IRQ-to-mip mapping for fast IRQs.** Bits of
`irq_fast_i[14:0]` correspond to mip bits 16-30 / mcause 16-30. The
SoC binds `irq_fast_i = {14'b0, irq_ctx1_fast}` so only `[0]` is
live. Cite `ibex_core.sv:113` and `ibex_mini_soc.sv:514`.

### Producer-side (PS-N)

**PS-1: `instr_req_o` SHALL be `0` immediately after `~rst_ni`.** The
IF stage's prefetch buffer resets to a state where `prefetch_busy =
0`, hence `instr_req_o = 0`, until `req_i` (= `instr_req_gated`) has
risen at least once. Cite `ibex_if_stage.sv:42, :626-:627`.

**PS-2: `data_req_o` SHALL be `0` immediately after `~rst_ni`.** The
LSU's request FSM resets to IDLE, `data_req_o = 0`. It only rises in
response to `lsu_req_i = 1` from ID (which itself requires
`instr_valid_id = 1`). Cite `ibex_load_store_unit.sv:25, :370, :388`.

**PS-3: `instr_addr_o` SHALL be 4-byte aligned (`[1:0] == 2'b00`).**
The IF stage rounds compressed-instruction PCs down to the next word
on fetch. Cite `ibex_if_stage.sv:837` (`IbexInstrAddrUnaligned`
assertion).

**PS-4: `core_busy_o` SHALL fall to `IbexMuBiOff` only after the
pipeline has fully drained.** This means: no in-flight bus request
on either port, no in-ID instruction, controller in WAIT_SLEEP /
SLEEP. The SoC's clock-gating wrapper (in `ibex_top`, not in
`ibex_core`) uses `core_busy_o` to decide when to gate the clock —
PS-4 ensures the clock only stops when sleep is observable. Cite
`ibex_core.sv:421, :570, :523, :820`.

**PS-5: `pc_set_o` events SHALL be 1-cycle pulses.** The controller
asserts `pc_set` for exactly one cycle on each redirect (taken
branch, jump, exception, IRQ entry, dret, mret, debug entry). IF
SHALL act on the rising edge — multi-cycle assertions of `pc_set` are
not produced. Cite `ibex_core.sv:590` and B5/B4 controller spec.

**PS-6: `instr_valid_clear_o` is a 1-cycle pulse aligned with
`pc_set_o`.** When the controller redirects the PC, it also clears
the IF→ID register so the in-flight instruction is squashed. Cite
`ibex_core.sv:586, :495`.

**PS-7: `crash_dump_o` SHALL be combinational.** It tracks the
underlying signals (`pc_id`, `pc_if`, `lsu_addr_last`, `csr_mepc`,
`csr_mtval`) every cycle. Consumers SHALL sample on a clock edge if
they need a stable snapshot. Cite `ibex_core.sv:961-:965`.

**PS-8: `alert_*_o` SHALL be combinational.** All three alerts are
straight ORs of raw alert sources. Under our pinning all three are
`0` (see R18). Cite `ibex_core.sv:972-:977`.

**PS-9: `irq_pending_o` SHALL track the union of enabled M-mode
IRQs.** It comes from the CSRs' aggregation of `mip & mie & ~mideleg`
(combinational). Cite `ibex_core.sv:1103`.

**PS-10: `double_fault_seen_o` SHALL only assert when a second
exception fires while the first hasn't been retired.** Internal CSRs
behaviour; ibex_core just forwards. Cite `ibex_core.sv:122, :1149`.

**PS-11: Same-cycle `branch_target_ex` → IF.** When EX produces
`branch_target_ex`, IF samples it combinationally (no stage register
between them). The implementer MUST NOT insert a register on this
path. Cite `ibex_core.sv:510, :762`.

**PS-12: `imd_val_q_ex` is read by EX in the same cycle ID
presents it.** EX uses the value combinationally for the next
multdiv micro-step. The flop is owned by ID (Latched-state-regs §);
ibex_core only routes the wire. Cite `ibex_core.sv:612, :754-:756`.

**PS-13: `data_addr_o` SHALL track `alu_adder_result_ex`
combinationally for the request beat.** EX produces the byte
address; the LSU forwards it to the bus on the same cycle the request
fires. Cite `ibex_core.sv:759, :806, :789`.

## Spec notes (N-N)

**N-1: RVFI is out of scope, do not implement.** The block bracketed
by `` `ifdef RVFI `` (port declarations at lines 127-166 and the
~700-LoC tracking pipeline at lines 1228+) is never compiled in our
SoC build (`RVFI` is not defined). The implementer MUST NOT add an
RVFI emission path; doing so would require the RVFI tracking flops
(`rvfi_stage_*`, `rvfi_*_d/q` regs) which are entirely out of scope.
The single `unused_illegal_insn_id = illegal_insn_id` sink at
`ibex_core.sv:721` is the only RVFI-related artifact that should be
preserved (as a lint sink for `illegal_insn_id`).

**N-2: `ibex_cs_registers` stays upstream-SV.** Per the proposal §
"Out of scope", `cs_registers_i` is instantiated as an upstream-SV
module from inside ibex_core. The CSR file is the responsibility of
the `rdl2arch-riscv` workstream (separate from C1). The implementer
MUST treat `ibex_cs_registers` as a black-box `inst` with the port
list from `ibex_core.sv:1055-:1165`. There is no .arch source for
CSRs to consult; do not invent one.

**N-3: `imd_val_*` flop ownership lives in ID, not in ibex_core.**
The proposal flagged this in Risks §2/§5: although `imd_val_q_ex` is
declared at module scope on `ibex_core.sv:203`, the actual flop array
is inside `IbexIdStage`. ibex_core's `imd_val_q_ex` is the
out-of-`IbexIdStage`'s `imd_val_q_ex_o` port (a wire), not a separate
register. The B5 spec (Latched state regs §) confirms: `imd_val_q[0/1]`
are flops inside id_stage. ibex_core simply routes
`imd_val_d_ex`/`imd_val_we_ex` from EX to ID and `imd_val_q_ex` from
ID back to EX. No top-level flop is needed.

**N-4: `BranchPredictor=0` means `nt_branch_*` are constant 0.** The
two signals `nt_branch_mispredict` and `nt_branch_addr` exist as
wires for upstream port-shape compatibility. Under our pinning ID's
`g_n_calc_nt_addr` arm drives both to `0`; IF accepts them but their
arms are inert. The implementer MUST NOT skip wiring these signals
just because they're constant — they're part of the IF / ID port
contract.

**N-5: `BranchTargetALU=0` means `bt_a_operand` / `bt_b_operand` are
constant 0.** Same shape as N-4 but for the BTALU operands. ID's
`g_no_btalu_muxes` arm drives both to `32'h0`, and EX's BTALU arm is
inert. The wires still exist and must be plumbed through.

**N-6: `instr_intg_err`, `lsu_load_resp_intg_err`,
`lsu_store_resp_intg_err` are constant 0 under MemECC=0.** These feed
the `alert_major_bus_o` OR-tree (R18). The implementer SHOULD wire
them structurally rather than constant-fold.

**N-7: Non-secure mubi pattern.** `IbexMuBiOn = 4'b0101` and
`IbexMuBiOff = 4'b1010` are defined in `ibex_pkg.sv:676-:677`. The
core-busy reduction (R9) and the fetch-enable gate (R10) both rely
on the LSB encoding (`IbexMuBiOn[0] = 1`, `IbexMuBiOff[0] = 0`). The
two `` `ASSERT_INIT `` checks at `ibex_core.sv:533-:534` are sim-only
and not required in the ARCH source.

**N-8: `pc_mismatch_alert` is `0` under our pinning.** It's driven by
the IF stage's PCIncrCheck arm; PCIncrCheck is `localparam bit
PCIncrCheck = SecureIbex` (`ibex_core.sv:180`), so PCIncrCheck = 0
under our pinning. The wire exists for waveform / future relaxation.

**N-9: `csr_shadow_err` is `0` under our pinning.** Driven by the
CSRs' ShadowCSR arm; `localparam bit ShadowCSR = 1'b0`
(`ibex_core.sv:181`). Same disposition as N-8.

**N-10: `icache_ecc_error` is `0` under our pinning.** ICache=0 ⇒
`icache_ecc_error = 0` from IF stage. `alert_minor_o = 0`
unconditionally.

**N-11: `priv_mode_lsu` is sunk to unused under PMPEnable=0.** CSRs
emit it (`ibex_core.sv:1082`) because it's needed for PMP D-channel
priv-level-checking; with no PMP it has no consumer. The
`unused_priv_lvl_ls = priv_mode_lsu` lint sink at `:1217` is required.

**N-12: `data_ind_timing` is `0` from CSRs.** It's a CSR-controlled
bit; the CSRs drive it to `0` because `DataIndTiming = SecureIbex = 0`
in the localparam derivation. Wire exists; consumer arms in EX/ID are
inert.

**N-13: `csr_wdata = alu_operand_a_ex` is a bare assign.** Line 1053
of `ibex_core.sv` aliases the EX block's operand-A as the CSR write
data. This is a continuous assignment, not a registered path, and
the timing relationship is "EX presents `alu_operand_a` in the same
cycle ID drives `csr_op_en = 1`". Implementer MUST keep this aliasing
combinational.

**N-14: `crash_dump_t` is a packed struct.** Defined at
`ibex_pkg.sv:15-:21` with five `logic [31:0]` fields. ARCH must
emit a corresponding struct typedef (likely in
`IbexCoreSharedPkg.arch`, per proposal Approach §). The five field
assigns are the standard form.

**N-15: `irqs_t` is a packed struct routed unchanged.** Defined at
`ibex_pkg.sv:326-:332`. CSRs produce `irqs_o`, ID consumes
`irqs_i`. ibex_core just routes the bundle. The implementer SHOULD
keep the struct shape (per `feedback_arch_syntax_pitfalls`) rather
than flatten to bits.

**N-16: `exc_cause_t` is a packed struct routed unchanged.** Defined
at `ibex_pkg.sv:334-:338`. ID's `controller_i.exc_cause_o` produces
it; CSRs consume it as `csr_mcause_i`. ibex_core just routes the
struct via the named wire `exc_cause` (`:224`).

**N-17: Reset polarity is async-low single-edge.** All sub-modules
use `posedge clk_i or negedge rst_ni`. ARCH `Reset<Async, Low>` is
the matching type. Per `feedback_arch_syntax_pitfalls`, the
implementer should propagate `clk_i, rst_ni` into all five sub-module
`inst` blocks.

**N-18: Single clock domain.** All flops in ibex_core's sub-modules
clock on `clk_i`; no synchronizers. `feedback_arch_syntax_pitfalls`'s
"clkgate" / "synchronizer" don't apply.

**N-19: Stage decomposition in ARCH is the implementer's choice (per
proposal § Stage decomposition).** The proposal recommends mapping IF/
ID/EX/(WB+LSU) to four `pipeline` stages. The spec does NOT prescribe
which ARCH construct to use; what it does prescribe is the upstream
behaviour (R1-R21) and integration constraints (CS-1-CS-10,
PS-1-PS-13). The implementer is free to use `pipeline`, plain
`module`, or a hybrid as long as the requirements above hold.

**N-20: SV instances inside ARCH stages.** `cs_registers_i` is an
upstream-SV instance. The proposal Risks §3 flags as an open question
whether arch-com supports SV instances inside `pipeline` stages or
requires module-scope placement. This is a tooling question for the
implementer and not a behavioural ambiguity in the upstream — the
spec does not prescribe a placement, only that the CSR ports are
wired per the cited connections list.

**N-21: `ASSERT*` macros are sim-only.** All `` `ASSERT_INIT ``,
`` `ASSERT_KNOWN_IF ``, `` `ASSERT `` invocations in `ibex_core.sv`
(lines 533-534, 1014-1015, 1043-1045, 1168-1174) are not part of the
behavioural spec. ARCH does not model SVAs; the implementer SHALL
NOT attempt to express these as functional logic.

**N-22: The `INC_ASSERT`-only flops (`pc_at_fetch_disable`,
`last_fetch_enable`) are out of scope.** They exist purely to drive
the `NoExecWhenFetchEnableNotOn` assertion (lines 1019-1045). No
synthesizable logic depends on them.

**N-23: `unused_*` lint sinks are required for clean lint.** Several
signals exist only to drive `unused_*` absorbers under our pinning:
`unused_fetch_enable`, `unused_illegal_insn_id`,
`unused_expecting_load_resp_id`, `unused_expecting_store_resp_id`,
`unused_rf_ren_a`, `unused_rf_ren_b`, `unused_rf_rd_a_wb_match`,
`unused_rf_rd_b_wb_match`, `unused_priv_lvl_ls`, `unused_csr_pmp_addr`,
`unused_csr_pmp_cfg`, `unused_csr_pmp_mseccfg`. The implementer SHOULD
emit equivalent sinks (or rely on arch-com's lint configuration) so
these signals don't trip lint warnings in the emitted SV. Cite
`ibex_core.sv:545, :721, :887-:891, :943-:949, :1213-:1220`.

**N-24: `instr_new_id`, `instr_gets_expanded_id`, `instr_expanded_id`,
`instr_done_wb` are RVFI-only producers under our pinning.** IF and WB
drive them, but the only consumer is the RVFI block (out of scope per
N-1). They MAY be sunk to `unused_*` under our SoC build; the
upstream `ibex_core.sv` does not have explicit `unused_*` for them
because the RVFI block is conditionally compiled in. The implementer
SHOULD wire them to lint sinks at module scope.

**N-25: `instr_first_cycle_id` is shared between ID, EX and (in
upstream) WB.** Driven from ID (`:585`); consumed by EX
(`:735` for `alu_instr_first_cycle_i`). Under WritebackStage=0 it's
not consumed by WB. It's a 1-bit combinational signal.

**N-26: `outstanding_load_wb` / `outstanding_store_wb` are `0` under
WritebackStage=0.** WB stage drives both to `0`; they are forwarded
into ID for the SecureIbex-only mem-response check arm (out of scope
under SecureIbex=0). They MUST be wired but their value is constant.

**N-27: ICache RAM port shapes use unpacked Vec.** The
`ic_tag_rdata_i`, `ic_data_rdata_i` ports are SV's `logic [W-1:0] x
[N]` shape (i.e. unpacked array of vectors). Per
`feedback_arch_syntax_pitfalls` rule #5, ARCH `Vec<UInt<W>, N>` ports
that interop with this shape need the `unpacked` modifier. Under
ICache=0 the contents are tied off in IF, but the port shape MUST
match for SoC binding.

**N-28: `irq_fast_i[14:0]` is packed.** Single 15-bit vector, not
unpacked array. Maps to ARCH `UInt<15>`. Cite `ibex_core.sv:113`.

**N-29: `pmp_req_err` is internally-declared, not a port.** The
3-channel error signal `pmp_req_err[PMPNumChan]` is local
(`ibex_core.sv:344`). Under PMPEnable=0 it's tied to `0` in three
explicit assigns (R20). The implementer can declare it as a
3-element constant or 3-bit zero, depending on which form composes
better with the LSU PMP-mask collapse (R8 producer side).

**N-30: `MemDataWidth = MemECC ? 32+7 : 32` collapses to 32.** Under
MemECC=0 the bus widths on `instr_rdata_i`, `data_rdata_i`,
`data_wdata_i` are all 32 bits, matching the SoC. The 7-bit ECC tail
is not present.

**N-31: `csr_mtval` from controller vs. `crash_dump_mtval` from
CSRs.** There are two distinct `mtval` paths: ID's controller drives
`csr_mtval` (`:640`) into CSRs as the *trap value to commit*; CSRs
drive `crash_dump_mtval` (= their `csr_mtval_o`, `:1108`) back into
ibex_core as the *committed mtval value*. The crash_dump struct uses
the latter (R17). Don't confuse the two — they have different
producers and different timing.

**N-32: `instr_executing` is internal to ID, not exported.** The
ID stage's `instr_executing` wire is used inside ID for stall logic
(B5 spec). It does not appear at the IbexIdStage port and is not
visible at the IbexCore boundary. The spec does not require the
implementer to recover or expose this signal.

**N-33: Behavioural ambiguity to flag (controller trap source
priority).** The exact priority order for simultaneous synchronous
exceptions (e.g. `illegal_insn` and `lsu_load_err` arriving at the
controller in the same cycle) is implemented in
`ibex_controller.sv` (B4). It is not visible from `ibex_core.sv`.
The implementer SHOULD trust the controller's existing logic — no
new prioritisation is required at the IbexCore scope.

**N-34: Behavioural ambiguity to flag (mubi-encoding of `core_busy_o`
under non-secure).** The non-secure form (`ibex_core.sv:421`) emits
the full mubi pattern, not just the LSB. This means `core_busy_o`
toggles between `4'b0101` and `4'b1010`, and the SoC's clock-gating
wrapper (`ibex_top.sv:280`) consumes the inverted top-level clock
gate `~clock_en` derived from this. The implementer MUST emit the
mubi pattern, not just a 1-bit equivalent. Cite `ibex_core.sv:421`
and `ibex_pkg.sv:676-:677`.

**N-35: `pc_if`, `pc_id`, `pc_wb` are produced by IF, IF, WB
respectively.** A common confusion is to think `pc_id` is produced by
ID — it is not. IF maintains `pc_id` (the PC of the instruction
currently in the IF→ID register) and exports it; ID consumes it; WB
consumes it; CSRs consume all three. Cite
`ibex_if_stage.sv:88`, `ibex_core.sv:200, :490, :602`.

**N-36: ARCH-side construct selection is in the proposal, not here.**
Per the methodology, this spec describes upstream behaviour only. The
proposal's `pipeline` decomposition (proposal § Stage decomposition)
and the construct enumeration table are guidance for the
implementer; they are reproduced there, not here. If the
implementer's pilot encounters a tooling block (e.g. SV-in-pipeline
inst, module-scope `comb` alongside `pipeline`), the proposal Risks
§3, §4 enumerate fallbacks.
