# IbexTop — port contract + behavior

## Module overview

`ibex_top` is the SoC-facing wrapper around the Ibex CPU pipeline. Under
the SoC pinning frozen by the C2 proposal it is structural glue, not a
pipelined CPU body: it instantiates one `ibex_core` (the C1 ARCH leaf),
one `ibex_register_file_ff` (the A2 ARCH leaf), one `prim_clock_gating`
cell (upstream-SV), and one `prim_buf` cell (upstream-SV). Around those
four instances it wires (a) the gated clock derived from `core_busy_q`
+ debug/IRQ inputs, (b) the register-file read/write paths between the
core and the register file, (c) memory-data integrity bits (collapsed
to no-op under `MemECC=0`), (d) ICache RAM port tieoffs (collapsed
under `ICache=0`), (e) Lockstep / shadow-core output tieoffs
(collapsed under `SecureIbex=0`), (f) ICache scramble state tieoffs
(collapsed under `ICacheScramble=0`), and (g) the final alert OR-trees.

The single piece of state at the `ibex_top` scope is the 4-bit mubi
flop `core_busy_q` clocked on the **ungated** `clk_i` so a single IRQ
pin or `debug_req_i` can re-open the gate.

Upstream file: `~/github/ibex/rtl/ibex_top.sv` (1394 LoC; ~250 LoC
effective under SoC pinning, after subtracting the
`if (Lockstep) gen_lockstep` arm, the `if (ICache) gen_rams` arm, the
`if (ICacheScramble) gen_scramble` arm, the `if (RegFile == FPGA /
Latch)` arms, the `` `ifdef RVFI `` ports, and the `` `ifdef
INC_ASSERT `` blocks).

## Pinned parameter values

This spec is restricted to the parameter values bound by
`soc/ibex_mini_soc.sv` via `ibex_top_tracing` defaults and SoC-side
overrides. Branches / generate arms guarded by their opposite values
are out of scope and are not required to be ported.

| Parameter                     | Pinned value           | Effect on this spec |
|-------------------------------|------------------------|---------------------|
| `RV32E`                       | `1'b0`                 | Pass-through into `u_ibex_core` and `register_file_i`. |
| `RV32M`                       | `RV32MFast`            | Pass-through into `u_ibex_core`. |
| `RV32B`                       | `RV32BNone`            | Pass-through into `u_ibex_core`. |
| `RV32ZC`                      | `RV32ZcaZcbZcmp`       | Pass-through into `u_ibex_core`. |
| `RegFile`                     | `RegFileFF`            | Selects `gen_regfile_ff` arm at `ibex_top.sv:462`; the FPGA / Latch arms are dead and out of scope. |
| `BranchTargetALU`             | `1'b0`                 | Pass-through. |
| `WritebackStage`              | `1'b0`                 | Pass-through. |
| `ICache`                      | `1'b0`                 | Selects `gen_norams` arm at `ibex_top.sv:753`; the `gen_rams` arm collapses; ICache RAM cfg outputs / `ic_*_rdata` internal wires are tied to `0`. |
| `ICacheECC`                   | `1'b0`                 | `BusSizeECC = BUS_SIZE = 32`, `TagSizeECC = IC_TAG_SIZE`. Pass-through. |
| `BranchPredictor`             | `1'b0`                 | Pass-through. |
| `DbgTriggerEn`                | `1'b0`                 | Pass-through. |
| `DbgHwBreakNum`               | `1`                    | Pass-through. |
| `SecureIbex`                  | `1'b0`                 | Selects the `g_clock_en_non_secure` arm at `ibex_top.sv:264` for `core_busy_q`; selects `gen_no_lockstep` at `ibex_top.sv:1119`. Drives `Lockstep = 0`, `DummyInstructions = 0`, `MemECC = 0`, `ICacheTweakInfection = 0` via local-param derivations. |
| `Lockstep` (`localparam`)     | `1'b0` (= `SecureIbex`)| `gen_lockstep` collapses; only `gen_no_lockstep` ties emit. Cite `ibex_top.sv:187`. |
| `ResetAll` (`localparam`)     | `1'b0` (= `Lockstep`)  | Pass-through; no per-flop async-reset insertion under our pins. Cite `ibex_top.sv:188`. |
| `DummyInstructions` (`localparam`) | `1'b0` (= `SecureIbex`) | `dummy_instr_id` and `dummy_instr_wb` are pinned `0` by `u_ibex_core`. Cite `ibex_top.sv:189`. |
| `RegFileECC` (`localparam`)   | `1'b0`                 | The regfile is non-ECC; the data path between `u_ibex_core.rf_*_ecc` ports and `register_file_i` is plain 32-bit. Cite `ibex_top.sv:190`. |
| `RegFileLockstepECC` (`localparam`) | `1'b0`           | Unused (lockstep dead). Cite `ibex_top.sv:191`. |
| `RegFileDataWidth` (`localparam`) | `32`               | Cite `ibex_top.sv:192`. |
| `RegFileDataEccWidth` (`localparam`) | `39`            | Unused under `MemECC=0`. Cite `ibex_top.sv:193`. |
| `BusSizeECC` (`localparam`)   | `BUS_SIZE = 32`        | Pass-through into `u_ibex_core`. Cite `ibex_top.sv:195-196`. |
| `LineSizeECC` (`localparam`)  | `BusSizeECC * IC_LINE_BEATS` | Pass-through into `u_ibex_core`. Cite `ibex_top.sv:197`. |
| `TagSizeECC` (`localparam`)   | `IC_TAG_SIZE`          | Pass-through into `u_ibex_core`. Cite `ibex_top.sv:198-199`. |
| `NumAddrScrRounds` (`localparam`) | `0`                | Unused under `ICacheScramble=0`. Cite `ibex_top.sv:201`. |
| `LockstepOffset`              | `1`                    | Unused under `Lockstep=0`. |
| `MemECC`                      | `1'b0` (= `SecureIbex`)| Selects `gen_non_mem_rdata_ecc` (`ibex_top.sv:307`) and `gen_no_mem_ecc` (`ibex_top.sv:779`); the upper 7 ECC bits of `data_rdata_core` / `instr_rdata_core` / `data_wdata_core` are not wired; `data_wdata_intg_o` is constant `0`. |
| `MemDataWidth`                | `32`                   | Width of `data_rdata_core`, `instr_rdata_core`, `data_wdata_core`. Cite `ibex_top.sv:39`. |
| `ICacheScramble`              | `1'b0`                 | Selects `gen_noscramble` arm at `ibex_top.sv:568`; the `gen_scramble` flop bank collapses; `scramble_*_q` are constant ties; `scramble_req_o = 0`. |
| `ICacheTweakInfection` (`localparam`) | `1'b0`         | Pass-through. Cite `ibex_top.sv:42`. |
| `ICacheScrNumPrinceRoundsHalf`| `2`                    | Unused under `ICacheScramble=0`. |
| `PMPEnable`                   | `1'b0`                 | Pass-through into `u_ibex_core`. |
| `PMPGranularity`              | `0`                    | Pass-through. |
| `PMPNumRegions`               | `4`                    | Pass-through. |
| `PMPRstCfg`, `PMPRstAddr`, `PMPRstMsecCfg` | typed-array defaults from `ibex_pkg` | Pass-through into `u_ibex_core`. |
| `MHPMCounterNum`              | `0`                    | Pass-through. |
| `MHPMCounterWidth`            | `40`                   | Pass-through. |
| `RndCnstLfsrSeed`, `RndCnstLfsrPerm` | typed defaults from `ibex_pkg` | Pass-through into `u_ibex_core`. |
| `RndCnstIbexKey`, `RndCnstIbexNonce` | typed defaults from `ibex_pkg` | Reach only the `gen_scramble` flop bank, which is dead; no consumer at this scope. |
| `DmBaseAddr`                  | `32'h0000_0000` (SoC overrides line 472) | Pass-through into `u_ibex_core`. |
| `DmAddrMask`                  | `32'h0000_0003` (SoC overrides line 473) | Pass-through into `u_ibex_core`. |
| `DmHaltAddr`                  | `32'h0000_0000` (SoC overrides line 470) | Pass-through into `u_ibex_core`. |
| `DmExceptionAddr`             | `32'h0000_0000` (SoC overrides line 471) | Pass-through into `u_ibex_core`. |
| `CsrMvendorId`                | `32'b0`                | Pass-through into `u_ibex_core`. |
| `CsrMimpId`                   | `32'b0`                | Pass-through into `u_ibex_core`. |

The two `ibex_pkg` mubi constants this spec relies on:

| Constant       | Bit pattern | Cite |
|----------------|-------------|------|
| `IbexMuBiOn`   | `4'b0101`   | `ibex_pkg.sv` (named) |
| `IbexMuBiOff`  | `4'b1010`   | `ibex_pkg.sv` (named) |

Both mubi values are 4-bit; only their LSB is consumed by IbexTop's
`clock_en` reduction under `SecureIbex=0` (cite `ibex_top.sv:274`).

## Ports

The port list mirrors upstream `ibex_top` excluding:

- the `` `ifdef RVFI `` block (lines 120-159) — **out of scope, do not
  implement** (see N-1).
- the `` `ifdef INC_ASSERT `` blocks (lines 1178-1342) — sim-only.
- the `` `ASSERT_KNOWN `` / `` `ASSERT `` calls (lines 1150-1174,
  1344-1391) — sim-only.

All ports below cite `ibex_top.sv:LINE`.

### Clock + reset

| Direction | Name      | Type / Width        | Role | Cite |
|-----------|-----------|---------------------|------|------|
| in        | `clk_i`   | `Clock<SysDomain>`  | System clock, ungated. Drives `core_busy_q` directly and feeds `core_clock_gate_i.clk_i`. | :63 |
| in        | `rst_ni`  | `Reset<Async, Low>` | Active-low asynchronous reset. Resets `core_busy_q` to `IbexMuBiOff`. | :64 |

### DFT / test-mode

| Direction | Name           | Type / Width        | Role | Cite |
|-----------|----------------|---------------------|------|------|
| in        | `test_en_i`    | `Bool`              | Test-mode clock-gate bypass. Wired into `core_clock_gate_i.test_en_i` AND into `register_file_i.test_en_i`. | :67 |
| in        | `scan_rst_ni`  | `Reset<Async, Low>` (or `Bool` lint sink) | DFT bypass; under `Lockstep=0` it is consumed only by the `unused_scan` lint sink. | :169 |

### ICache RAM configuration (boundary-only under ICache=0)

These ports cross the IbexTop boundary so the SoC binding remains
stable; under `ICache=0` they are absorbed by `unused_ram_cfg` /
driven to `0` rather than connected to RAM cells.

| Direction | Name                          | Type / Width                                          | Role | Cite |
|-----------|-------------------------------|-------------------------------------------------------|------|------|
| in        | `ram_cfg_icache_tag_i`        | `prim_ram_1p_pkg::ram_1p_cfg_t` (struct)              | SoC-side cfg input for tag RAM. Sunk by `unused_ram_cfg`. | :68 |
| out       | `ram_cfg_rsp_icache_tag_o`    | `prim_ram_1p_pkg::ram_1p_cfg_rsp_t [IC_NUM_WAYS-1:0]` (packed Vec of struct) | Driven to `0` by `gen_norams`. | :69 |
| in        | `ram_cfg_icache_data_i`       | `prim_ram_1p_pkg::ram_1p_cfg_t` (struct)              | Same as tag input. Sunk. | :70 |
| out       | `ram_cfg_rsp_icache_data_o`   | `prim_ram_1p_pkg::ram_1p_cfg_rsp_t [IC_NUM_WAYS-1:0]` | Driven to `0` by `gen_norams`. | :71 |

### Hart identity / boot

| Direction | Name           | Type / Width  | Role | Cite |
|-----------|----------------|---------------|------|------|
| in        | `hart_id_i`    | `UInt<32>`    | Pure pass-through into `u_ibex_core.hart_id_i`. | :73 |
| in        | `boot_addr_i`  | `UInt<32>`    | Pure pass-through into `u_ibex_core.boot_addr_i`. | :74 |

### Instruction memory interface (OBI)

| Direction | Name                  | Type / Width  | Role | Cite |
|-----------|-----------------------|---------------|------|------|
| out       | `instr_req_o`         | `Bool`        | Direct from `u_ibex_core.instr_req_o`. | :77 |
| in        | `instr_gnt_i`         | `Bool`        | Direct to `u_ibex_core.instr_gnt_i`. | :78 |
| in        | `instr_rvalid_i`      | `Bool`        | Direct to `u_ibex_core.instr_rvalid_i`. | :79 |
| out       | `instr_addr_o`        | `UInt<32>`    | Direct from `u_ibex_core.instr_addr_o`. | :80 |
| in        | `instr_rdata_i`       | `UInt<32>`    | Routed to `u_ibex_core.instr_rdata_i` via the `instr_rdata_core` aliasing wire (R6). | :81 |
| in        | `instr_rdata_intg_i`  | `UInt<7>`     | Sunk by `unused_intg` under `MemECC=0`. | :82 |
| in        | `instr_err_i`         | `Bool`        | Direct to `u_ibex_core.instr_err_i`. | :83 |

### Data memory interface (OBI)

| Direction | Name                  | Type / Width  | Role | Cite |
|-----------|-----------------------|---------------|------|------|
| out       | `data_req_o`          | `Bool`        | Direct from `u_ibex_core.data_req_o`. | :86 |
| in        | `data_gnt_i`          | `Bool`        | Direct to `u_ibex_core.data_gnt_i`. | :87 |
| in        | `data_rvalid_i`       | `Bool`        | Direct to `u_ibex_core.data_rvalid_i`. | :88 |
| out       | `data_we_o`           | `Bool`        | Direct from `u_ibex_core.data_we_o`. | :89 |
| out       | `data_be_o`           | `UInt<4>`     | Direct from `u_ibex_core.data_be_o`. | :90 |
| out       | `data_addr_o`         | `UInt<32>`    | Direct from `u_ibex_core.data_addr_o`. | :91 |
| out       | `data_wdata_o`        | `UInt<32>`    | Equals `data_wdata_core[31:0]` (R6). | :92, :772 |
| out       | `data_wdata_intg_o`   | `UInt<7>`     | Constant `0` under `MemECC=0` (R6). | :93, :780 |
| in        | `data_rdata_i`        | `UInt<32>`    | Routed to `u_ibex_core.data_rdata_i` via `data_rdata_core` (R6). | :94, :301 |
| in        | `data_rdata_intg_i`   | `UInt<7>`     | Sunk by `unused_intg` under `MemECC=0`. | :95, :310 |
| in        | `data_err_i`          | `Bool`        | Direct to `u_ibex_core.data_err_i`. | :96 |

### Interrupt inputs

| Direction | Name              | Type / Width       | Role | Cite |
|-----------|-------------------|--------------------|------|------|
| in        | `irq_software_i`  | `Bool`             | Direct to `u_ibex_core.irq_software_i`. | :99 |
| in        | `irq_timer_i`     | `Bool`             | Direct to `u_ibex_core.irq_timer_i`. | :100 |
| in        | `irq_external_i`  | `Bool`             | Direct to `u_ibex_core.irq_external_i`. | :101 |
| in        | `irq_fast_i`      | `UInt<15>` (packed)| Direct to `u_ibex_core.irq_fast_i`. | :102 |
| in        | `irq_nm_i`        | `Bool`             | Direct to `u_ibex_core.irq_nm_i` AND a term in the `clock_en` reduction (R4). | :104 |

### Scrambling Interface (boundary-only under ICacheScramble=0)

| Direction | Name                   | Type / Width  | Role | Cite |
|-----------|------------------------|---------------|------|------|
| in        | `scramble_key_valid_i` | `Bool`        | Sunk by `unused_scramble_inputs`. | :107 |
| in        | `scramble_key_i`       | `UInt<SCRAMBLE_KEY_W>` | Sunk. | :108 |
| in        | `scramble_nonce_i`     | `UInt<SCRAMBLE_NONCE_W>` | Sunk. | :109 |
| out       | `scramble_req_o`       | `Bool`        | Constant `0` (R8). | :110, :578 |

### Debug

| Direction | Name                   | Type / Width    | Role | Cite |
|-----------|------------------------|-----------------|------|------|
| in        | `debug_req_i`          | `Bool`          | Direct to `u_ibex_core.debug_req_i` AND a term in the `clock_en` reduction (R4). | :113 |
| out       | `crash_dump_o`         | `crash_dump_t` (packed struct, 5 × `UInt<32>`) | Direct from `u_ibex_core.crash_dump_o`. | :114 |
| out       | `double_fault_seen_o`  | `Bool`          | Direct from `u_ibex_core.double_fault_seen_o`. | :115 |

### CPU control

| Direction | Name                       | Type / Width    | Role | Cite |
|-----------|----------------------------|-----------------|------|------|
| in        | `fetch_enable_i`           | `ibex_mubi_t` (`UInt<4>`) | Routed to `u_ibex_core.fetch_enable_i` via `u_fetch_enable_buf` (R3). | :162, :294, :451 |
| out       | `alert_minor_o`            | `Bool`          | Final OR-tree (R10). Equals `core_alert_minor` under our pins. | :163, :1147 |
| out       | `alert_major_internal_o`   | `Bool`          | Final OR-tree (R10). Equals `core_alert_major_internal` under our pins. | :164, :1143 |
| out       | `alert_major_bus_o`        | `Bool`          | Final OR-tree (R10). Equals `core_alert_major_bus` under our pins. | :165, :1146 |
| out       | `core_sleep_o`             | `Bool`          | `~clock_en` (R4). | :166, :280 |

### Lockstep / shadow-core outputs (constant-tied under SecureIbex=0)

These outputs cross the IbexTop boundary so `ibex_top_tracing`'s
binding remains stable. Under `Lockstep=0` they are constant-tied per
the `gen_no_lockstep` block.

| Direction | Name                       | Type / Width        | Role | Cite |
|-----------|----------------------------|---------------------|------|------|
| out       | `lockstep_cmp_en_o`        | `ibex_mubi_t`       | Constant `IbexMuBiOff`. | :172, :1124 |
| out       | `data_req_shadow_o`        | `Bool`              | Constant `0`. | :175, :1125 |
| out       | `data_we_shadow_o`         | `Bool`              | Constant `0`. | :176, :1126 |
| out       | `data_be_shadow_o`         | `UInt<4>`           | Constant `0`. | :177, :1127 |
| out       | `data_addr_shadow_o`       | `UInt<32>`          | Constant `0`. | :178, :1128 |
| out       | `data_wdata_shadow_o`      | `UInt<32>`          | Constant `0`. | :179, :1129 |
| out       | `data_wdata_intg_shadow_o` | `UInt<7>`           | Constant `0`. | :180, :1130 |
| out       | `instr_req_shadow_o`       | `Bool`              | Constant `0`. | :183, :1131 |
| out       | `instr_addr_shadow_o`      | `UInt<32>`          | Constant `0`. | :184, :1132 |

### RVFI block

**Out of scope, do not implement.** Lines 120-159 of `ibex_top.sv`
declare the RVFI output bundle, gated by `` `ifdef RVFI ``. The SoC
build never defines `RVFI`. The `ibex_top_tracing` wrapper layered
above us also compiles without these ports. See N-1.

## Sub-module instances

The IbexTop body contains four `inst`s — two ARCH leaves
(`u_ibex_core`, `register_file_i`) and two upstream-SV cells
(`core_clock_gate_i`, `u_fetch_enable_buf`).

### `u_ibex_core` — `ibex_core` (ARCH leaf, C1)
Cite: `ibex_top.sv:313-:456`.

Parameter pass-through (1:1 from IbexTop's params to `u_ibex_core`):

| IbexTop param        | `ibex_core` param   |
|----------------------|---------------------|
| `PMPEnable`          | `PMPEnable`         |
| `PMPGranularity`     | `PMPGranularity`    |
| `PMPNumRegions`      | `PMPNumRegions`     |
| `PMPRstCfg`          | `PMPRstCfg`         |
| `PMPRstAddr`         | `PMPRstAddr`        |
| `PMPRstMsecCfg`      | `PMPRstMsecCfg`     |
| `MHPMCounterNum`     | `MHPMCounterNum`    |
| `MHPMCounterWidth`   | `MHPMCounterWidth`  |
| `RV32E`              | `RV32E`             |
| `RV32M`              | `RV32M`             |
| `RV32B`              | `RV32B`             |
| `RV32ZC`             | `RV32ZC`            |
| `BranchTargetALU`    | `BranchTargetALU`   |
| `ICache`             | `ICache`            |
| `ICacheECC`          | `ICacheECC`         |
| `ICacheTweakInfection` | `ICacheTweakInfection` |
| `BusSizeECC`         | `BusSizeECC`        |
| `TagSizeECC`         | `TagSizeECC`        |
| `LineSizeECC`        | `LineSizeECC`       |
| `BranchPredictor`    | `BranchPredictor`   |
| `DbgTriggerEn`       | `DbgTriggerEn`      |
| `DbgHwBreakNum`      | `DbgHwBreakNum`     |
| `WritebackStage`     | `WritebackStage`    |
| `ResetAll`           | `ResetAll`          |
| `RndCnstLfsrSeed`    | `RndCnstLfsrSeed`   |
| `RndCnstLfsrPerm`    | `RndCnstLfsrPerm`   |
| `SecureIbex`         | `SecureIbex`        |
| `DummyInstructions`  | `DummyInstructions` |
| `RegFileECC`         | `RegFileECC`        |
| `RegFileDataWidth`   | `RegFileDataWidth`  |
| `MemECC`             | `MemECC`            |
| `MemDataWidth`       | `MemDataWidth`      |
| `DmBaseAddr`         | `DmBaseAddr`        |
| `DmAddrMask`         | `DmAddrMask`        |
| `DmHaltAddr`         | `DmHaltAddr`        |
| `DmExceptionAddr`    | `DmExceptionAddr`   |
| `CsrMvendorId`       | `CsrMvendorId`      |
| `CsrMimpId`          | `CsrMimpId`         |

Note: `ibex_core` also has parameters `DataIndTiming` and `PCIncrCheck`
that are **not** explicitly passed at the upstream `u_ibex_core`
instantiation; they default inside `ibex_core` to `SecureIbex` (= 0
under our pins). Cite `ibex_top.sv:313-:351` (no override).

Port wiring (the full list at the cited lines):

| Outer signal                   | `u_ibex_core` port            | Direction (core side) |
|--------------------------------|-------------------------------|-----------------------|
| `clk` (gated)                  | `clk_i`                       | in                    |
| `rst_ni`                       | `rst_ni`                      | in                    |
| `hart_id_i`                    | `hart_id_i`                   | in                    |
| `boot_addr_i`                  | `boot_addr_i`                 | in                    |
| `instr_req_o` (top)            | `instr_req_o`                 | out                   |
| `instr_gnt_i` (top)            | `instr_gnt_i`                 | in                    |
| `instr_rvalid_i` (top)         | `instr_rvalid_i`              | in                    |
| `instr_addr_o` (top)           | `instr_addr_o`                | out                   |
| `instr_rdata_core`             | `instr_rdata_i`               | in                    |
| `instr_err_i` (top)            | `instr_err_i`                 | in                    |
| `data_req_o` (top)             | `data_req_o`                  | out                   |
| `data_gnt_i` (top)             | `data_gnt_i`                  | in                    |
| `data_rvalid_i` (top)          | `data_rvalid_i`               | in                    |
| `data_we_o` (top)              | `data_we_o`                   | out                   |
| `data_be_o` (top)              | `data_be_o`                   | out                   |
| `data_addr_o` (top)            | `data_addr_o`                 | out                   |
| `data_wdata_core`              | `data_wdata_o`                | out                   |
| `data_rdata_core`              | `data_rdata_i`                | in                    |
| `data_err_i` (top)             | `data_err_i`                  | in                    |
| `dummy_instr_id` (internal)    | `dummy_instr_id_o`            | out                   |
| `dummy_instr_wb` (internal)    | `dummy_instr_wb_o`            | out                   |
| `rf_raddr_a` (internal)        | `rf_raddr_a_o`                | out                   |
| `rf_raddr_b` (internal)        | `rf_raddr_b_o`                | out                   |
| `rf_waddr_wb` (internal)       | `rf_waddr_wb_o`               | out                   |
| `rf_we_wb` (internal)          | `rf_we_wb_o`                  | out                   |
| `rf_wdata_wb` (internal)       | `rf_wdata_wb_ecc_o`           | out                   |
| `rf_rdata_a` (internal)        | `rf_rdata_a_ecc_i`            | in                    |
| `rf_rdata_b` (internal)        | `rf_rdata_b_ecc_i`            | in                    |
| `ic_tag_req` (internal)        | `ic_tag_req_o`                | out                   |
| `ic_tag_write` (internal)      | `ic_tag_write_o`              | out                   |
| `ic_tag_addr` (internal)       | `ic_tag_addr_o`               | out                   |
| `ic_tag_wdata` (internal)      | `ic_tag_wdata_o`              | out                   |
| `ic_tag_rdata` (internal)      | `ic_tag_rdata_i`              | in                    |
| `ic_data_req` (internal)       | `ic_data_req_o`               | out                   |
| `ic_data_write` (internal)     | `ic_data_write_o`             | out                   |
| `ic_data_addr` (internal)      | `ic_data_addr_o`              | out                   |
| `ic_data_wdata` (internal)     | `ic_data_wdata_o`             | out                   |
| `ic_data_rdata` (internal)     | `ic_data_rdata_i`             | in                    |
| `scramble_key_valid_q` (internal) | `ic_scr_key_valid_i`       | in                    |
| `ic_scr_key_req` (internal)    | `ic_scr_key_req_o`            | out                   |
| `irq_software_i` (top)         | `irq_software_i`              | in                    |
| `irq_timer_i` (top)            | `irq_timer_i`                 | in                    |
| `irq_external_i` (top)         | `irq_external_i`              | in                    |
| `irq_fast_i` (top)             | `irq_fast_i`                  | in                    |
| `irq_nm_i` (top)               | `irq_nm_i`                    | in                    |
| `irq_pending` (internal)       | `irq_pending_o`               | out                   |
| `debug_req_i` (top)            | `debug_req_i`                 | in                    |
| `crash_dump_o` (top)           | `crash_dump_o`                | out                   |
| `double_fault_seen_o` (top)    | `double_fault_seen_o`         | out                   |
| `fetch_enable_buf` (internal)  | `fetch_enable_i`              | in                    |
| `core_alert_minor` (internal)  | `alert_minor_o`               | out                   |
| `core_alert_major_internal`   | `alert_major_internal_o`      | out                   |
| `core_alert_major_bus`        | `alert_major_bus_o`           | out                   |
| `core_busy_d` (internal)       | `core_busy_o`                 | out                   |

The **clock** input is the **gated `clk`** produced by
`core_clock_gate_i`, NOT the ungated `clk_i`. Cite `ibex_top.sv:353`.

### `register_file_i` — `ibex_register_file_ff` (ARCH leaf, A2)
Cite: `ibex_top.sv:462-:483` (the `gen_regfile_ff` arm).

Parameter pass-through:

| IbexTop value             | `ibex_register_file_ff` param |
|---------------------------|-------------------------------|
| `RV32E` (0)               | `RV32E`                       |
| `RegFileDataWidth` (32)   | `DataWidth`                   |
| `DummyInstructions` (0)   | `DummyInstructions`           |
| `RegFileDataWidth'(prim_secded_pkg::SecdedInv3932ZeroWord)` | `WordZeroVal` |

The `WordZeroVal` upstream expression is functionally a don't-care
under `RegFileECC=0` (see N-3); the ARCH inst MAY pass `WordZeroVal =
0`.

Port wiring:

| Outer signal              | RegFileFf port    | Direction (RF side) |
|---------------------------|-------------------|---------------------|
| `clk` (gated)             | `clk_i`           | in                  |
| `rst_ni`                  | `rst_ni`          | in                  |
| `test_en_i` (top)         | `test_en_i`       | in                  |
| `dummy_instr_id`          | `dummy_instr_id_i`| in                  |
| `dummy_instr_wb`          | `dummy_instr_wb_i`| in                  |
| `rf_raddr_a`              | `raddr_a_i`       | in                  |
| `rf_rdata_a`              | `rdata_a_o`       | out                 |
| `rf_raddr_b`              | `raddr_b_i`       | in                  |
| `rf_rdata_b`              | `rdata_b_o`       | out                 |
| `rf_waddr_wb`             | `waddr_a_i`       | in                  |
| `rf_wdata_wb`             | `wdata_a_i`       | in                  |
| `rf_we_wb`                | `we_a_i`          | in                  |

The **clock** input is the **gated `clk`**, NOT `clk_i`. Cite
`ibex_top.sv:469`.

The `gen_regfile_fpga` arm (lines 484-505) and `gen_regfile_latch` arm
(lines 506-527) **collapse to nothing** under `RegFile=RegFileFF`.

### `core_clock_gate_i` — `prim_clock_gating` (upstream-SV cell)
Cite: `ibex_top.sv:282-:287`.

Pure pass-through wiring; no parameters at the upstream instance. The
cell's stub interface is:

| Pin       | Connection            | Direction |
|-----------|-----------------------|-----------|
| `clk_i`   | `clk_i` (top)         | in        |
| `en_i`    | `clock_en` (internal) | in        |
| `test_en_i` | `test_en_i` (top)   | in        |
| `clk_o`   | `clk` (internal)      | out       |

The implementer SHALL keep this as an upstream-SV `inst` against a
hand-written `.archi` stub (`prim_clock_gating.archi`). See N-4.

### `u_fetch_enable_buf` — `prim_buf` (upstream-SV cell)
Cite: `ibex_top.sv:294-:297`.

Single parameter `Width = $bits(ibex_mubi_t) = 4`. Single 4-bit
input/output buffer.

| Pin     | Connection                     | Direction |
|---------|--------------------------------|-----------|
| `in_i`  | `fetch_enable_i` (top)         | in        |
| `out_o` | `fetch_enable_buf` (internal)  | out       |

The implementer SHALL keep this as an upstream-SV `inst` against a
hand-written `.archi` stub (`prim_buf.archi`). See N-4.

### Collapsed sub-module arms

The following upstream generate arms collapse entirely under our pins
and the ARCH implementer MUST NOT emit them:

| Arm                         | Lines       | Collapse trigger | Replacement |
|-----------------------------|-------------|------------------|-------------|
| `g_clock_en_secure`         | :252-:263   | `SecureIbex=0`   | `g_clock_en_non_secure` (R1+R4) |
| `gen_regfile_fpga`          | :484-:505   | `RegFile=RegFileFF` | `gen_regfile_ff` (R5) |
| `gen_regfile_latch`         | :506-:527   | `RegFile=RegFileFF` | `gen_regfile_ff` (R5) |
| `gen_scramble`              | :534-:567   | `ICacheScramble=0`| `gen_noscramble` (R8) |
| `gen_rams`                  | :592-:751   | `ICache=0`       | `gen_norams` (R7) |
| `gen_mem_rdata_ecc`         | :304-:306   | `MemECC=0`       | `gen_non_mem_rdata_ecc` (R6) |
| `gen_mem_wdata_ecc`         | :774-:778   | `MemECC=0`       | `gen_no_mem_ecc` (R6) |
| `gen_lockstep`              | :784-:1118  | `Lockstep=0`     | `gen_no_lockstep` (R9) |
| `g_mem_ecc_asserts`         | :1369-:1392 | `MemECC=0` (and `INC_ASSERT`) | none — sim-only |
| `g_dside_tracker`           | :1194-:1235 | `INC_ASSERT`     | none — sim-only |
| `g_secure_ibex_mem_assert`  | :1248-:1252 | `SecureIbex=0`+`INC_ASSERT` | `g_no_secure_ibex_mem_assert` — sim-only |

## Latched state regs

There is exactly one architecturally observable register at the
IbexTop scope under `SecureIbex=0`:

### `core_busy_q` (4-bit mubi flop)
Cite: `ibex_top.sv:205, :267-:273`.

- **Width**: 4 bits (`ibex_mubi_t`).
- **Clock**: `clk_i` — the **ungated** system clock, NOT the gated
  `clk`. Cite `ibex_top.sv:267`.
- **Reset**: async, low-active (`rst_ni`); reset value is
  `IbexMuBiOff` (`4'b1010`). Cite `ibex_top.sv:268-:269`.
- **D input**: `core_busy_d`, sourced from `u_ibex_core.core_busy_o`.
  Cite `ibex_top.sv:271, :455`.

Under `SecureIbex=0` (the `g_clock_en_non_secure` arm):
- only `core_busy_q[0]` is consumed by `clock_en` (R4);
- the remaining 3 bits feed `unused_core_busy = ^core_busy_q[3:1]`
  (`ibex_top.sv:277`) — a lint-sink XOR reduction with no architectural
  consumer.

The upstream `g_clock_en_secure` arm (lines 252-263) instantiates
`prim_flop` instead of an `always_ff`. That arm collapses under our
pins; the implementer SHALL emit the `always_ff`-equivalent (a plain
`reg` with async-low reset to `IbexMuBiOff` clocked on `clk_i`).

## Combinational logic blocks (module-scope glue)

The body has six module-scope combinational reductions, one
gated-clock production, and a small set of constant-tied output
assignments. Each is described below; the Requirements section
formalises the contract.

### CG-1: `clock_en` (non-secure form)
`clock_en = core_busy_q[0] | debug_req_i | irq_pending | irq_nm_i`.
Cite `ibex_top.sv:274`.

`irq_pending` is `u_ibex_core.irq_pending_o` (sourced from CSRs).

### CG-2: `core_sleep_o`
`core_sleep_o = ~clock_en`. Cite `ibex_top.sv:280`.

### CG-3: Gated clock production
`clk = prim_clock_gating(clk_i, clock_en, test_en_i)`. The output
`clk` drives every internal flop except `core_busy_q` itself.
Cite `ibex_top.sv:282-:287, :353, :469`.

### CG-4: Memory-data integrity merge (collapsed under MemECC=0)
- `data_rdata_core[31:0] = data_rdata_i` (`ibex_top.sv:301`).
- `instr_rdata_core[31:0] = instr_rdata_i` (`ibex_top.sv:302`).
- `gen_non_mem_rdata_ecc` arm (`:307-:311`):
  `unused_intg = ^{instr_rdata_intg_i, data_rdata_intg_i}` — lint
  sink.
- `data_wdata_o = data_wdata_core[31:0]` (`:772`). Under `MemECC=0`
  `data_wdata_core` is 32-bit, so the slice is the whole vector.
- `gen_no_mem_ecc` arm (`:779-:781`): `data_wdata_intg_o = '0`.

### CG-5: Fetch-enable buffer
`fetch_enable_buf = prim_buf<Width=4>(fetch_enable_i)`. Pure
combinational buffer with no functional change other than synthesis
optimization-barrier semantics. Cite `ibex_top.sv:294-:297`.

### CG-6: Register-file passthrough
The eight signals `dummy_instr_id`, `dummy_instr_wb`, `rf_raddr_a`,
`rf_raddr_b`, `rf_waddr_wb`, `rf_we_wb`, `rf_wdata_wb` (out of
`u_ibex_core`) and `rf_rdata_a`, `rf_rdata_b` (out of
`register_file_i`) are direct internal-wire connections. No
intermediate logic. Cite `ibex_top.sv:209-:217, :376-:384, :476-:482`.

### CG-7: ICache RAM tieoffs (`gen_norams`, ICache=0)
Cite `ibex_top.sv:753-:770`.

- `unused_ram_cfg = |{ram_cfg_icache_tag_i, ram_cfg_icache_data_i}` —
  lint sink (`:758`).
- `ram_cfg_rsp_icache_tag_o = '0` (`:759`).
- `ram_cfg_rsp_icache_data_o = '0` (`:760`).
- `unused_ram_inputs = (|ic_tag_req) & ic_tag_write & (|ic_tag_addr) &
  (|ic_tag_wdata) & (|ic_data_req) & ic_data_write & (|ic_data_addr) &
  (|ic_data_wdata) & (|NumAddrScrRounds)` — lint sink (`:761-:763`).
- `ic_tag_rdata = '{default:'b0}` (`:765`).
- `ic_data_rdata = '{default:'b0}` (`:766`).
- `icache_tag_alert = '{default:'b0}` (`:768`).
- `icache_data_alert = '{default:'b0}` (`:769`).

`ic_tag_rdata` and `ic_data_rdata` are upstream-declared **unpacked**
arrays (`logic [W-1:0] x [IC_NUM_WAYS]`). See N-7.

### CG-8: Scramble tieoffs (`gen_noscramble`, ICacheScramble=0)
Cite `ibex_top.sv:568-:583`.

- `unused_scramble_inputs` — large `&`-reduction lint sink absorbing
  every scramble-related input and internal wire (`:570-:574`).
- `scramble_req_d = 1'b0` (`:576`).
- `scramble_req_q = 1'b0` (`:577`).
- `scramble_req_o = 1'b0` (`:578`).
- `scramble_key_q = '0` (`:579`).
- `scramble_nonce_q = '0` (`:580`).
- `scramble_key_valid_q = 1'b1` (`:581`).
- `scramble_key_valid_d = 1'b1` (`:582`).

`scramble_key_valid_q` (constant `1`) feeds
`u_ibex_core.ic_scr_key_valid_i` (`:396`).

### CG-9: Lockstep / shadow-core tieoffs (`gen_no_lockstep`, Lockstep=0)
Cite `ibex_top.sv:1119-:1136`.

- `lockstep_alert_major_internal = 1'b0` (`:1120`).
- `lockstep_alert_major_bus = 1'b0` (`:1121`).
- `lockstep_alert_minor = 1'b0` (`:1122`).
- `lockstep_cmp_en_o = IbexMuBiOff` (`:1124`).
- `data_req_shadow_o = 1'b0` (`:1125`).
- `data_we_shadow_o = 1'b0` (`:1126`).
- `data_be_shadow_o = '0` (`:1127`).
- `data_addr_shadow_o = '0` (`:1128`).
- `data_wdata_shadow_o = '0` (`:1129`).
- `data_wdata_intg_shadow_o = '0` (`:1130`).
- `instr_req_shadow_o = 1'b0` (`:1131`).
- `instr_addr_shadow_o = '0` (`:1132`).
- `unused_scan = scan_rst_ni` — lint sink (`:1135`).

### CG-10: Final alert OR-trees
Cite `ibex_top.sv:1140-:1147`.

- `icache_alert_major_internal = (|icache_tag_alert) |
  (|icache_data_alert)` (`:1141`). Under `ICache=0` both reduce to
  `0`.
- `alert_major_internal_o = core_alert_major_internal |
  lockstep_alert_major_internal | icache_alert_major_internal`
  (`:1143-:1145`). Under our pins reduces to
  `core_alert_major_internal`.
- `alert_major_bus_o = core_alert_major_bus |
  lockstep_alert_major_bus` (`:1146`). Under our pins reduces to
  `core_alert_major_bus`.
- `alert_minor_o = core_alert_minor | lockstep_alert_minor`
  (`:1147`). Under our pins reduces to `core_alert_minor`.

The implementer SHALL emit the OR-trees structurally (not
constant-fold the dead terms) so the port semantics remain stable
under future relaxation of `Lockstep` / `ICache` pinning.

## Requirements (RFC 2119)

### Requirement 1: Reset state — `core_busy_q` and `core_sleep_o`

**R1.** Out of reset (`rst_ni` low), IbexTop SHALL drive:
- `core_busy_q = IbexMuBiOff` (`4'b1010`),
- `clock_en = 0` (since `core_busy_q[0] = 0` and the SoC binds
  `debug_req_i = 0`, `irq_*_i = 0` at reset),
- `core_sleep_o = 1`.

The async-low reset takes effect on the negedge of `rst_ni` and is
released on the next posedge of `clk_i` after `rst_ni` rises.

- *Given* `rst_ni = 0`, *when* observed combinationally, *then*
  `core_busy_q SHALL be `IbexMuBiOff` and `core_sleep_o = 1`
  (`ibex_top.sv:267-:269, :274, :280`).
- *Given* `rst_ni` rises with all of `core_busy_d`, `debug_req_i`,
  `irq_pending`, `irq_nm_i` low, *when* the next `clk_i` posedge
  arrives, *then* `core_busy_q` SHALL still be `IbexMuBiOff` and
  `core_sleep_o` SHALL still be `1` (`ibex_top.sv:267-:274`).

### Requirement 2: Sub-module instantiation

**R2.** IbexTop SHALL instantiate exactly four cells under our pins:

1. `u_ibex_core` of type `ibex_core` (ARCH leaf, C1) with parameter
   pass-through per the table in § Sub-module instances. Cite
   `ibex_top.sv:313-:456`.
2. `register_file_i` of type `ibex_register_file_ff` (ARCH leaf, A2,
   the `gen_regfile_ff` arm only) with parameter pass-through per the
   table. Cite `ibex_top.sv:462-:483`.
3. `core_clock_gate_i` of type `prim_clock_gating` (upstream-SV cell)
   with the four pins `clk_i`, `en_i`, `test_en_i`, `clk_o`. Cite
   `ibex_top.sv:282-:287`.
4. `u_fetch_enable_buf` of type `prim_buf` (upstream-SV cell) with
   `Width=4` and the two pins `in_i`, `out_o`. Cite
   `ibex_top.sv:294-:297`.

It SHALL NOT instantiate `ibex_register_file_fpga`,
`ibex_register_file_latch`, `ibex_lockstep`, `prim_ram_1p`,
`prim_ram_1p_scr`, `prim_secded_inv_39_32_dec`, the
`u_prim_buf_data_wdata_intg` buffer, or the secure-form `prim_flop`
for `core_busy_q`.

The clock fed to `u_ibex_core.clk_i` and `register_file_i.clk_i`
SHALL be the **gated** `clk` produced by `core_clock_gate_i.clk_o`,
not the raw `clk_i`. Cite `ibex_top.sv:353, :469`.

### Requirement 3: Fetch-enable buffering

**R3.** IbexTop SHALL route `fetch_enable_i` through `u_fetch_enable_buf`
(a `prim_buf` with `Width = 4`) before presenting it to
`u_ibex_core.fetch_enable_i`. The buffer is a combinational
optimization-barrier; its output `fetch_enable_buf` SHALL equal
`fetch_enable_i` in every cycle.

- *Given* `fetch_enable_i = X` (any 4-bit value), *when* observed in
  the same cycle, *then* `u_ibex_core.fetch_enable_i` SHALL equal `X`
  (`ibex_top.sv:294-:297, :451`).

### Requirement 4: `clock_en` reduction and `core_sleep_o`

**R4.** IbexTop SHALL produce the gate-enable signal `clock_en` and
the sleep output `core_sleep_o` per the non-secure form:
- `clock_en = core_busy_q[0] | debug_req_i | irq_pending | irq_nm_i`
  (`ibex_top.sv:274`),
- `core_sleep_o = ~clock_en` (`ibex_top.sv:280`),

where `irq_pending = u_ibex_core.irq_pending_o`.

- *Given* `core_busy_q = IbexMuBiOff` and `debug_req_i = irq_pending
  = irq_nm_i = 0`, *when* observed, *then* `clock_en = 0` and
  `core_sleep_o = 1`.
- *Given* `irq_software_i` rises and the CSRs have it enabled in
  `mie`, *when* `irq_pending` rises in the same cycle, *then*
  `clock_en` SHALL rise combinationally and `core_sleep_o` SHALL fall
  to `0` in that cycle. (Wakes the gate without waiting for
  `core_busy_q` to update.) Cite `ibex_top.sv:274, :280`.
- *Given* `debug_req_i` rises while `core_busy_q = IbexMuBiOff` and
  IRQs are quiet, *when* observed, *then* `clock_en` SHALL rise
  combinationally and `core_sleep_o` SHALL fall in the same cycle
  (`ibex_top.sv:274`).
- *Given* `irq_nm_i` rises, *when* observed, *then* `clock_en` SHALL
  rise combinationally (`ibex_top.sv:274`).
- *Given* `core_busy_q[0]` is `1` (i.e. `core_busy_q == IbexMuBiOn`)
  and all three async wake terms are `0`, *when* observed, *then*
  `clock_en = 1` and `core_sleep_o = 0` (`ibex_top.sv:274, :280`).

The 3 upper bits of `core_busy_q` SHALL NOT participate in `clock_en`
under `SecureIbex=0`; they feed `unused_core_busy` only
(`ibex_top.sv:277`).

### Requirement 5: `core_busy_q` flop on ungated `clk_i`

**R5.** The `core_busy_q` register SHALL be clocked on the **ungated**
`clk_i`, NOT on the gated `clk`. Its D-input is `core_busy_d` from
`u_ibex_core.core_busy_o`; its async reset value is `IbexMuBiOff`.

- *Given* the gated clock has stopped (`clock_en=0` ⇒ `clk` is
  static), *when* a wake-up arrives via `irq_*_i` or `debug_req_i`,
  *then* `clock_en` rises combinationally, `core_clock_gate_i`
  reopens, and `clk` resumes ticking — but `core_busy_q` was already
  on `clk_i` so it had been sampling `core_busy_d` continuously. Cite
  `ibex_top.sv:267, :282-:287`.
- *Given* the gated clock is running and `u_ibex_core.core_busy_o`
  transitions from `IbexMuBiOff` to `IbexMuBiOn` in cycle `N`, *when*
  the next `clk_i` posedge arrives, *then* `core_busy_q` SHALL update
  to `IbexMuBiOn` (1-cycle latency), and on the same cycle
  `clock_en` SHALL be `1` (because `core_busy_q[0] = 1`). Cite
  `ibex_top.sv:267-:273`.

This is the keystone integration constraint at the IbexTop scope:
keeping `core_busy_q` on the ungated clock is what makes the
combinational wake-up via IRQ pins / `debug_req_i` work.

### Requirement 6: Memory-data integrity bits collapse under MemECC=0

**R6.** Under `MemECC=0`, IbexTop SHALL handle the memory data buses
as follows:
- `data_rdata_core[31:0] = data_rdata_i` (`ibex_top.sv:301`).
- `instr_rdata_core[31:0] = instr_rdata_i` (`ibex_top.sv:302`).
- `instr_rdata_intg_i` and `data_rdata_intg_i` SHALL be sunk by a
  `unused_intg = ^{instr_rdata_intg_i, data_rdata_intg_i}` lint
  reduction (`ibex_top.sv:308-:310`).
- `data_wdata_o = data_wdata_core` (the 32-bit slice equals the whole
  vector under `MemDataWidth=32`; `ibex_top.sv:772`).
- `data_wdata_intg_o = '0` (`ibex_top.sv:780`, `gen_no_mem_ecc` arm).

It SHALL NOT instantiate the `u_prim_buf_data_wdata_intg` buffer
(`ibex_top.sv:775-:778`) or the `prim_secded_inv_39_32_dec` decoders
(`ibex_top.sv:1374, :1383`).

- *Given* the SoC bus presents `data_rdata_i = X` and any value of
  `data_rdata_intg_i`, *when* observed, *then*
  `u_ibex_core.data_rdata_i` SHALL equal `X` and the integrity bits
  SHALL be absorbed into the lint sink with no functional effect
  (`ibex_top.sv:301, :310`).
- *Given* the core drives `data_wdata_core = Y` and `data_req_o =
  1`, *when* observed at the IbexTop boundary, *then* `data_wdata_o
  = Y` and `data_wdata_intg_o = 7'b0` (`ibex_top.sv:772, :780`).

### Requirement 7: ICache RAM port handling under ICache=0

**R7.** Under `ICache=0`, IbexTop SHALL emit the `gen_norams` ties:

- `ram_cfg_rsp_icache_tag_o = 0` and `ram_cfg_rsp_icache_data_o = 0`
  in every cycle (`ibex_top.sv:759-:760`).
- The internal feedback wires `ic_tag_rdata` and `ic_data_rdata` (fed
  back into `u_ibex_core.ic_tag_rdata_i` and `ic_data_rdata_i`)
  SHALL be tied to `0` for all ways (`ibex_top.sv:765-:766`).
- The internal alert vectors `icache_tag_alert` and
  `icache_data_alert` SHALL be tied to `0` for all ways
  (`ibex_top.sv:768-:769`).
- The input port `ram_cfg_icache_tag_i` and `ram_cfg_icache_data_i`,
  and the internal driver wires `ic_tag_req`, `ic_tag_write`,
  `ic_tag_addr`, `ic_tag_wdata`, `ic_data_req`, `ic_data_write`,
  `ic_data_addr`, `ic_data_wdata`, plus the `NumAddrScrRounds`
  localparam, SHALL be absorbed by the lint sinks `unused_ram_cfg`
  and `unused_ram_inputs` (`ibex_top.sv:758, :761-:763`).

It SHALL NOT instantiate `prim_ram_1p` or `prim_ram_1p_scr`
(`ibex_top.sv:707, :728, :600, :637`).

- *Given* the SoC drives any value on `ram_cfg_icache_tag_i` /
  `ram_cfg_icache_data_i`, *when* observed at the IbexTop outputs,
  *then* `ram_cfg_rsp_icache_tag_o` and `ram_cfg_rsp_icache_data_o`
  SHALL be `0` (`ibex_top.sv:759-:760`).
- *Given* `u_ibex_core` drives any non-zero value on `ic_tag_req`
  etc., *when* observed at the `ic_tag_rdata_i` feedback, *then*
  `u_ibex_core.ic_tag_rdata_i` SHALL be `0` for every way
  (`ibex_top.sv:765`).

### Requirement 8: Scramble interface tieoffs under ICacheScramble=0

**R8.** Under `ICacheScramble=0`, IbexTop SHALL emit the
`gen_noscramble` ties:

- `scramble_req_o = 1'b0` (`ibex_top.sv:578`).
- The internal scramble state wires `scramble_req_q`,
  `scramble_req_d`, `scramble_key_q`, `scramble_nonce_q`,
  `scramble_key_valid_d` SHALL be `0`, except `scramble_key_valid_q`
  and `scramble_key_valid_d` which SHALL be `1` (`:577, :576, :579,
  :580, :581, :582`).
- `scramble_key_valid_q = 1'b1` SHALL feed
  `u_ibex_core.ic_scr_key_valid_i` (`:396`); from the core's
  perspective this means "scramble key is always valid".
- The input ports `scramble_key_valid_i`, `scramble_key_i`,
  `scramble_nonce_i`, plus the parameters `RndCnstIbexKey`,
  `RndCnstIbexNonce`, plus the internal scramble wires, SHALL be
  absorbed by the `unused_scramble_inputs` lint sink (`:570-:574`).

It SHALL NOT instantiate any flop bank for `scramble_*_q` (those flops
exist only inside `gen_scramble`, which is dead).

### Requirement 9: Lockstep / shadow-core tieoffs under SecureIbex=0

**R9.** Under `SecureIbex=0` (⇒ `Lockstep=0`), IbexTop SHALL emit the
`gen_no_lockstep` ties:

- `lockstep_alert_major_internal = 0`,
  `lockstep_alert_major_bus = 0`, `lockstep_alert_minor = 0`
  (`:1120-:1122`).
- `lockstep_cmp_en_o = IbexMuBiOff` (`:1124`).
- `data_req_shadow_o = 0`, `data_we_shadow_o = 0`,
  `data_be_shadow_o = 0`, `data_addr_shadow_o = 0`,
  `data_wdata_shadow_o = 0`, `data_wdata_intg_shadow_o = 0`
  (`:1125-:1130`).
- `instr_req_shadow_o = 0`, `instr_addr_shadow_o = 0`
  (`:1131-:1132`).
- `scan_rst_ni` SHALL be absorbed by `unused_scan = scan_rst_ni`
  (`:1135`).

It SHALL NOT instantiate `ibex_lockstep`, the `prim_buf
u_signals_prim_buf`, the `gen_ways` per-way `prim_buf` cells, or the
three `prim_buf u_prim_buf_alert_*` cells.

### Requirement 10: Alert OR-trees

**R10.** IbexTop SHALL produce its three alert outputs as the OR
combination of three sources each (one from `u_ibex_core`, one from
the lockstep tieoffs, one from the icache alert reduction):

- `icache_alert_major_internal = (|icache_tag_alert) |
  (|icache_data_alert)` (`:1141`).
- `alert_major_internal_o = core_alert_major_internal |
  lockstep_alert_major_internal | icache_alert_major_internal`
  (`:1143-:1145`).
- `alert_major_bus_o = core_alert_major_bus |
  lockstep_alert_major_bus` (`:1146`).
- `alert_minor_o = core_alert_minor | lockstep_alert_minor` (`:1147`).

Under our pins, `lockstep_*` are constant `0` (R9) and
`icache_*_alert` are constant `0` (R7), so each output reduces to its
`core_*` term — but the implementer SHALL emit the OR structurally,
not constant-fold the dead terms.

- *Given* `u_ibex_core.alert_minor_o = 1`, *when* observed, *then*
  `alert_minor_o = 1` (`:1147`).
- *Given* `u_ibex_core.alert_major_internal_o = 1`, *when* observed,
  *then* `alert_major_internal_o = 1` (`:1143-:1145`).
- *Given* `u_ibex_core.alert_major_bus_o = 1`, *when* observed, *then*
  `alert_major_bus_o = 1` (`:1146`).

### Requirement 11: Boot signaling and hart identity

**R11.** The boot-vector input `boot_addr_i` and the hart-identity
input `hart_id_i` SHALL be presented combinationally at
`u_ibex_core.boot_addr_i` and `u_ibex_core.hart_id_i` respectively,
with no IbexTop-side latching, gating, or transformation. Cite
`ibex_top.sv:73-:74, :356-:357`.

- *Given* the SoC drives `boot_addr_i = 32'h0010_0000`, *when*
  observed, *then* `u_ibex_core.boot_addr_i = 32'h0010_0000` in the
  same cycle.

### Requirement 12: Debug interface pass-through

**R12.** IbexTop SHALL pass `debug_req_i` directly into
`u_ibex_core.debug_req_i` AND use it as a wake-term in `clock_en`
(R4). The two output signals `crash_dump_o` and
`double_fault_seen_o` SHALL be direct combinational pass-throughs from
`u_ibex_core.crash_dump_o` and `u_ibex_core.double_fault_seen_o`
respectively.

- *Given* `u_ibex_core.crash_dump_o = X`, *when* observed at the
  IbexTop boundary, *then* `crash_dump_o = X` (`:114, :407`).
- *Given* `u_ibex_core.double_fault_seen_o = 1`, *when* observed,
  *then* `double_fault_seen_o = 1` (`:115, :408`).

### Requirement 13: IRQ pass-through

**R13.** IbexTop SHALL pass the five IRQ-pin inputs directly into
`u_ibex_core` with no IbexTop-side gating or registering:

- `irq_software_i` → `u_ibex_core.irq_software_i` (`:99, :399`).
- `irq_timer_i` → `u_ibex_core.irq_timer_i` (`:100, :400`).
- `irq_external_i` → `u_ibex_core.irq_external_i` (`:101, :401`).
- `irq_fast_i[14:0]` → `u_ibex_core.irq_fast_i[14:0]` (`:102, :402`).
- `irq_nm_i` → `u_ibex_core.irq_nm_i` AND a wake-term in `clock_en`
  (`:104, :274, :403`).

The `irq_pending` signal driven by `u_ibex_core.irq_pending_o` is an
INTERNAL wire (NOT an IbexTop port); it feeds only the `clock_en`
reduction. It is NOT exported as a top-level output.

### Requirement 14: Register-file passthrough

**R14.** IbexTop SHALL connect `u_ibex_core` and `register_file_i`
directly via the seven internal wires `rf_raddr_a`, `rf_raddr_b`,
`rf_waddr_wb`, `rf_we_wb`, `rf_wdata_wb`, `rf_rdata_a`, `rf_rdata_b`,
plus `dummy_instr_id` and `dummy_instr_wb` per the table in §
Sub-module instances. There SHALL be no intermediate combinational
logic on this path beyond the implicit ECC encode/decode (which is a
no-op under `RegFileECC=0`):

- `u_ibex_core.rf_wdata_wb_ecc_o` → `register_file_i.wdata_a_i` is a
  direct wire connection (RegFileECC=0 means the "ecc-out" port from
  the core just carries the raw 32-bit value). Cite `ibex_top.sv:382,
  :481`.
- `register_file_i.rdata_a_o` → `u_ibex_core.rf_rdata_a_ecc_i` is a
  direct wire connection (`:383, :477`). Same for `b`.

- *Given* `u_ibex_core` drives `rf_raddr_a = a` and `rf_raddr_b = b`
  in cycle `N`, *when* the register file responds combinationally,
  *then* `rf_rdata_a` and `rf_rdata_b` SHALL be presented to
  `u_ibex_core.rf_rdata_*_ecc_i` in cycle `N` (combinational read
  through IbexTop). Cite `ibex_top.sv:378-:384, :476-:479`.
- *Given* `u_ibex_core` drives `rf_waddr_wb = w`, `rf_wdata_wb = d`,
  `rf_we_wb = 1` in cycle `N`, *when* the next gated-clock posedge
  arrives, *then* the register file SHALL latch `d` into entry `w`
  (the latching is `register_file_i`'s responsibility; IbexTop only
  routes the wires). Cite `ibex_top.sv:380-:382, :469, :480-:482`.

### Requirement 15: DFT / test-mode port routing

**R15.** IbexTop SHALL route `test_en_i` to two consumers:

- `core_clock_gate_i.test_en_i` (clock-gate test bypass; `:285`).
- `register_file_i.test_en_i` (`:472`).

It SHALL NOT route `test_en_i` to `u_ibex_core` (no such port at the
core).

The `scan_rst_ni` port SHALL be present at the IbexTop boundary for
SoC binding compatibility, but is consumed only by the
`unused_scan = scan_rst_ni` lint sink under `Lockstep=0` (`:1135`).

## Integration constraints

These constraints span the IbexTop boundary and the SoC / sub-module
modules. Per `feedback_unit_tests_dont_catch_integration.md` the
implementer MUST treat these as first-class checks; they cannot be
demonstrated by IbexTop unit tests alone.

### Caller-side (CS-N)

**CS-1: Single clock, single async reset.** The SoC SHALL drive
`clk_i` from a single source and `rst_ni` from a single async-low
reset. There is no IbexTop-side CDC. The `core_busy_q` flop is on the
ungated `clk_i`; the gated `clk` derives from it via
`core_clock_gate_i`. Cite `ibex_top.sv:63-:64, :267, :282-:287`.

**CS-2: `boot_addr_i` MUST be valid before `rst_ni` rises and stable
afterwards.** The IF stage inside `u_ibex_core` forms the boot fetch
as `{boot_addr_i[31:8], 8'h80}`. The SoC binds
`boot_addr_i = 32'h0010_0000` constant. Cite C1 spec CS-1 and
`ibex_top.sv:74, :357`.

**CS-3: `test_en_i` SHALL be `0` during normal operation.** `test_en_i`
is a clock-gate bypass for DFT; if asserted during normal operation it
disables the gate. The SoC binds `test_en_i = 0`. Cite
`ibex_top.sv:67, :285`.

**CS-4: `scan_rst_ni` MAY be tied to any value during normal
operation.** Under `Lockstep=0` it is consumed only by `unused_scan`
and has no architectural effect. Cite `ibex_top.sv:169, :1135`.

**CS-5: `ram_cfg_icache_tag_i` and `ram_cfg_icache_data_i` SHALL be
tied to `prim_ram_1p_pkg::RAM_1P_CFG_DEFAULT` (or any constant) during
normal operation.** Under `ICache=0` they are sunk by `unused_ram_cfg`.
Cite `ibex_top.sv:68, :70, :758`.

**CS-6: Scramble inputs SHALL be tied off during normal operation.**
The SoC SHALL drive `scramble_key_valid_i = 0` (or any value),
`scramble_key_i = 0`, `scramble_nonce_i = 0`. Under `ICacheScramble=0`
all three are sunk. Cite `ibex_top.sv:107-:109, :570-:574`.

**CS-7: OBI bus protocol obligations are inherited from `ibex_core`.**
The `instr_*_i/o` and `data_*_i/o` ports at the IbexTop boundary are
direct passes-through from `u_ibex_core`. The SoC's OBI obligations
(per C1's CS-2, CS-3) apply unchanged: grant follows request, rvalid
follows grant, exactly one rvalid per accepted request, etc. Cite
`ibex_top.sv:77-:96, :359-:374` and C1 spec CS-2/CS-3.

**CS-8: `irq_*_i` level obligations are inherited from `ibex_core`.**
The five IRQ pins (`irq_software_i`, `irq_timer_i`, `irq_external_i`,
`irq_fast_i[14:0]`, `irq_nm_i`) are direct passes-through. The SoC's
CLINT/PLIC SHALL hold each line high until acknowledged. Cite
`ibex_top.sv:99-:104, :399-:403` and C1 spec CS-4/CS-5.

**CS-9: `debug_req_i` level obligation is inherited from `ibex_core`.**
The SoC SHALL hold `debug_req_i` high until the core enters debug
mode. Cite `ibex_top.sv:113, :406` and C1 spec CS-6.

**CS-10: `fetch_enable_i` SHALL be `IbexMuBiOn` to allow execution.**
The SoC binds `IbexMuBiOn = 4'b0101`. Under `SecureIbex=0` only bit 0
matters at `u_ibex_core` (per C1 spec CS-7); the `prim_buf` is just an
optimization barrier. Cite `ibex_top.sv:162, :294-:297, :451`.

### Producer-side (PS-N)

**PS-1: `core_sleep_o` SHALL fall combinationally on any wake-up
input.** When `irq_software_i`, `irq_timer_i`, `irq_external_i`, any
bit of `irq_fast_i & mie`, `irq_nm_i`, or `debug_req_i` rises, the
`clock_en` reduction (R4) responds in the same cycle, so
`core_sleep_o` falls in the same cycle. The SoC SHALL NOT expect
single-cycle latency. Cite `ibex_top.sv:274, :280`.

**PS-2: `core_sleep_o` SHALL only rise when the core is fully drained
AND no async wake-term is asserted.** Per C1's PS-4, `core_busy_o`
from `u_ibex_core` only falls to `IbexMuBiOff` when the pipeline has
fully drained. Combined with R5, `core_busy_q[0]` becomes `0` one
cycle after the core's `core_busy_o` reaches `IbexMuBiOff`; if all
async wake-terms are then `0`, `clock_en` falls and `core_sleep_o`
rises. Cite `ibex_top.sv:274, :280` and C1 spec PS-4.

**PS-3: `crash_dump_o` SHALL be combinational pass-through.** It
tracks `u_ibex_core.crash_dump_o` every cycle; consumers SHALL sample
on a clock edge if they need a stable snapshot. Cite C1 spec PS-7 and
`ibex_top.sv:407`.

**PS-4: `double_fault_seen_o` SHALL be combinational pass-through.**
Same shape as PS-3. Cite C1 spec PS-10 and `ibex_top.sv:408`.

**PS-5: `data_wdata_intg_o` SHALL be constant `0` in every cycle
under `MemECC=0`.** Cite `ibex_top.sv:780`.

**PS-6: `instr_req_o` and `instr_addr_o` SHALL pass through directly
from `u_ibex_core`.** Cite `ibex_top.sv:359, :362`. The 4-byte
alignment / X-known guarantees are inherited from C1 (PS-1, PS-3).

**PS-7: `data_req_o`, `data_we_o`, `data_be_o`, `data_addr_o`,
`data_wdata_o` SHALL pass through from `u_ibex_core` (with
`data_wdata_o = data_wdata_core[31:0]`).** Cite
`ibex_top.sv:366-:372, :772`.

**PS-8: All Lockstep / shadow-core outputs SHALL be 0 in every cycle
under `SecureIbex=0`.** Per R9. Includes `lockstep_cmp_en_o =
IbexMuBiOff`, `data_*_shadow_o = 0`, `instr_*_shadow_o = 0`. Cite
`ibex_top.sv:1119-:1132`.

**PS-9: `scramble_req_o` SHALL be `0` in every cycle under
`ICacheScramble=0`.** Cite `ibex_top.sv:578`.

**PS-10: `ram_cfg_rsp_icache_tag_o` and `ram_cfg_rsp_icache_data_o`
SHALL be `0` in every cycle under `ICache=0`.** Cite
`ibex_top.sv:759-:760`.

**PS-11: `alert_*_o` SHALL be combinational reductions of the source
signals.** All three alert OR-trees (R10) are combinational. Under
our pins they reduce to their `core_*` terms; under any future
relaxation of `Lockstep` / `ICache` pinning they pick up the
additional terms. Cite `ibex_top.sv:1141-:1147`.

## Spec notes (N-N)

**N-1: RVFI is out of scope, do not implement.** The block bracketed
by `` `ifdef RVFI `` in the IbexTop port list (lines 120-159) and the
matching `u_ibex_core` connections (lines 410-449) are never
compiled in the SoC build (`RVFI` is not defined). The
`ibex_top_tracing` wrapper that the SoC binds does not pull RVFI ports
through the boundary; instead it reads `u_ibex.rvfi_pc_rdata` via SV
hierarchical reference (SoC line 548). The implementer SHALL omit the
RVFI block entirely from IbexTop. Note that `ibex_core` itself has
RVFI ports in its auto-emitted `.archi` stub — those ports remain
unconnected at the `u_ibex_core` instantiation.

**N-2: `ibex_top_tracing` wrapper.** The SoC's `u_ibex` binds to
`ibex_top_tracing`, NOT to `ibex_top` directly (`soc/ibex_mini_soc.sv`
line 469 binds `ibex_top_tracing #(...) u_ibex(...)`). The tracing
wrapper is upstream-SV; it instantiates `ibex_top` by name and stays
in place. The conftest's swap-shadow logic targets
`build/ibex_top.sv` (basename match); the ARCH source is
`IbexTop.arch` (CamelCase) per the snake-case-vs-CamelCase
convention.

**N-3: `WordZeroVal` is observably equivalent to `0` under
`RegFileECC=0`.** Upstream passes
`RegFileDataWidth'(prim_secded_pkg::SecdedInv3932ZeroWord)` (line
467) — a cross-package SV constant cast that materializes a specific
ECC-encoded zero pattern. Under `RegFileECC=0` the regfile does not
do ECC decode on read, so the literal value of `WordZeroVal` is only
observable when reading register x0 (the hard-wired-zero register).
The IbexCore's RV32I architecture mandates x0 reads return `0`; the
upstream regfile achieves this by hard-coding entry 0 to
`WordZeroVal` and re-decoding through ECC. Under our pins the
implementer MAY pass `WordZeroVal = 0` literally; the resulting
behaviour is observably equivalent.

**N-4: Two upstream-SV cells stay against hand-written `.archi`
stubs.** `prim_clock_gating` (4 single-bit pins, no params) and
`prim_buf` (2 same-width pins, single param `Width`) are vendor
primitives that arch-com does not lower. The implementer SHALL keep
them as upstream-SV `inst`s against hand-written `prim_clock_gating.archi`
and `prim_buf.archi` stubs (same pattern as B4's `ibex_cs_registers.archi`).

**N-5: Single clock domain.** Although `core_clock_gate_i` produces a
gated `clk` from the ungated `clk_i`, this is NOT a new clock domain —
it is the same clock with periods removed. No CDC, no synchronizer.
The `core_busy_q` flop is on the ungated source; everything else
(inside `u_ibex_core` and `register_file_i`) is on the gated form.

**N-6: Reset polarity is async-low single-edge.** The non-secure
`always_ff` for `core_busy_q` uses `posedge clk_i or negedge rst_ni`.
ARCH `Reset<Async, Low>` is the matching type. Sub-modules use the
same convention.

**N-7: `ic_tag_rdata` / `ic_data_rdata` are upstream **unpacked**
arrays.** Upstream `ibex_top.sv:229, :234` declares them as
`logic [W-1:0] x [IC_NUM_WAYS]` — SV unpacked array. The connection
into `u_ibex_core.ic_tag_rdata_i` / `ic_data_rdata_i` (`:390, :395`)
must therefore use the same shape.

The auto-emitted C1 stub `src/ibex_core.archi` declares those ports
as packed `Vec<UInt<W>, N>` (lines 76, 81 of the stub) without an
`unpacked` modifier. This is a **port-shape ambiguity** that the
implementer MUST verify before binding: either the C1-emitted SV
declares them packed (in which case IbexTop's internal wires must
match packed) or unpacked. Under our pins both wires are tied to `0`
inside IbexTop (`gen_norams`), so a wrong packing choice may not be
exercised at run time but would still trip a compile-time port
binding error.

If the C1-emitted `build/ibex_core.sv` declares these as unpacked,
the IbexTop ARCH source MUST use the `unpacked` Vec modifier on the
internal `ic_tag_rdata` and `ic_data_rdata` wires (per arch-com's
unpacked-Vec port shape). If it declares them packed, the ARCH
internal wires SHALL be packed `Vec`. The implementer SHALL inspect
`build/ibex_core.sv` after C1 build and match. This is a tooling
question, not a behavioural ambiguity in upstream — upstream is
unambiguously unpacked at IbexTop's declaration site.

**N-8: `ram_cfg_rsp_icache_*_o` are packed Vecs of struct.** Upstream
declares them `prim_ram_1p_pkg::ram_1p_cfg_rsp_t [IC_NUM_WAYS-1:0]`
(lines 69, 71) — packed Vec of struct, NOT unpacked. The `prim_ram_1p_pkg`
package types `ram_1p_cfg_t` and `ram_1p_cfg_rsp_t` need to be
imported via `use` at the ARCH file scope.

**N-9: The dummy_instr seed flop chain is absent under our pins.**
Upstream's `ibex_top` does not contain dummy_instr LFSR/seed flops —
those flops live INSIDE `u_ibex_core` (under
`DummyInstructions=1`). At IbexTop scope, `dummy_instr_id` and
`dummy_instr_wb` are wires from `u_ibex_core` that are guaranteed `0`
(C1 N-pinned `DummyInstructions=0`) and feed `register_file_i`
directly. No additional IbexTop flops needed.

**N-10: `core_busy_d` width.** It is the full 4-bit mubi pattern from
`u_ibex_core.core_busy_o` (per C1 R9 / N-34: the non-secure form
emits the full mubi pattern, not just the LSB). The IbexTop flop
captures the full pattern; only the LSB is consumed by `clock_en`
under our pins.

**N-11: `unused_*` lint-sink reductions are required for clean lint.**
Upstream has six `unused_*` absorbers under our pins:
- `unused_core_busy = ^core_busy_q[3:1]` (`:277`).
- `unused_intg = ^{instr_rdata_intg_i, data_rdata_intg_i}` (`:310`).
- `unused_ram_cfg = |{ram_cfg_icache_tag_i, ram_cfg_icache_data_i}` (`:758`).
- `unused_ram_inputs = ...` large `&`-reduction (`:761-:763`).
- `unused_scramble_inputs = ...` large `&`-reduction (`:570-:574`).
- `unused_scan = scan_rst_ni` (`:1135`).

The implementer SHOULD emit equivalent `let unused_x = ...;` sinks
in `comb` blocks (per `feedback_arch_syntax_pitfalls` rule #13) so
these signals don't trip lint warnings in the emitted SV.

**N-12: `unused_scramble_inputs` mixes RHS sources from different
arms.** The upstream sink at line 570-574 references:
`scramble_key_valid_i`, `scramble_key_i`, `RndCnstIbexKey`,
`scramble_nonce_i`, `RndCnstIbexNonce`, `scramble_req_q`,
`ic_scr_key_req`, `scramble_key_valid_d`, `scramble_req_d`,
`scramble_key_q`, `scramble_nonce_q`, `scramble_key_valid_q`,
`scramble_key_valid_d` (twice). Under `ICacheScramble=0` all of
`scramble_*_q`, `scramble_*_d`, and `scramble_key_valid_d` are
constant ties (R8). The sink absorbs the input ports + the
parameters + the internal wires. The implementer MAY simplify to a
single XOR over the input ports / parameters that have no other
consumer.

**N-13: `irq_pending` is internal-only.** The wire `irq_pending`
(`ibex_top.sv:207`) is sourced from `u_ibex_core.irq_pending_o`
(`:404`) and consumed by the `clock_en` reduction (`:274`). It is NOT
an IbexTop port. Don't expose it.

**N-14: `core_busy_q` width-mismatch under `SecureIbex=0`.** The
upstream non-secure form (`:267-:273`) declares `core_busy_q` as
`ibex_mubi_t` (4-bit) but uses only `core_busy_q[0]` in the gate;
synthesis will optimize away the upper 3 bits. The ARCH source SHALL
keep the 4-bit width to preserve waveform-name equivalence. The
upper-3 lint sink (`:277`) is required to keep the 3 bits "live" for
the lint pass.

**N-15: No `Verilator` in doc comments.** Per
`feedback_avoid_verilator_in_comments.md` (B2 lesson), the
implementer SHALL NOT use the literal capital-V `Verilator` in `///`
doc comments — use lowercase `verilator` or "the simulator". The
upstream-SV comments inside `ibex_top.sv` use various capitalisations
of "Verilator"; the ARCH source MAY rephrase.

**N-16: `MemDataWidth` const-folded under `MemECC=0`.** Upstream's
parameter declaration `MemDataWidth = MemECC ? 32 + 7 : 32` (line 39)
is a ternary on a parameter. Per `feedback_arch_syntax_pitfalls` rule
#12, the IbexTop ARCH source SHALL declare `MemDataWidth` as a `local
param` with the const-folded value `32`, not as a ternary on
`MemECC`. This matches the C1 stub's approach.

**N-17: `RegFileLockstepECC` is `Lockstep` (= 0).** The
`RegFileLockstepECC` localparam (`:191`) is `Lockstep`, which is
`SecureIbex = 0`. It only affects the lockstep regfile arm (out of
scope under `Lockstep=0`); the implementer MAY drop it.

**N-18: `ResetAll` is `Lockstep` (= 0).** The `ResetAll` localparam
(`:188`) controls per-flop async-reset insertion in sub-modules. It
is `0` under our pins; the implementer SHALL pass it as `0` into
`u_ibex_core`.

**N-19: `BusSizeECC`, `LineSizeECC`, `TagSizeECC` derive from
`ICacheECC=0`.** Per upstream lines 195-199, under `ICacheECC=0`:
- `BusSizeECC = BUS_SIZE = 32`.
- `LineSizeECC = BusSizeECC * IC_LINE_BEATS` (a compile-time integer
  derived from `ibex_pkg`).
- `TagSizeECC = IC_TAG_SIZE` (also from `ibex_pkg`).

The implementer SHALL declare these as `local param` const values
matching `u_ibex_core`'s declarations. Under `ICache=0` they are
unused at the IbexTop scope (the `ic_*_rdata_i` unpacked Vec ports of
`u_ibex_core` use `TagSizeECC` and `LineSizeECC` for shape; tying the
internal wires to `0` requires those types but no functional logic).

**N-20: `NumAddrScrRounds` is `0` under `ICacheScramble=0`.** The
localparam (`:201`) is referenced only inside `gen_scramble` and the
`unused_ram_inputs` sink (`:763`). Under our pins it is `0` and may
appear in a lint sink only.

**N-21: Behavioural ambiguity to flag — what does the upstream
`unused_scramble_inputs` declaration `logic
unused_scramble_inputs = ...` mean syntactically?** Upstream uses
inline-assign-on-declare form (`:570`). This is SystemVerilog
shorthand for "declare and continuously assign in one statement". The
ARCH equivalent is `let unused_scramble_inputs = ...;` in a `comb`
block. The implementer should treat this as semantically equivalent
to the assign-after-declare form.

**N-22: `ibex_pkg` import.** Upstream uses `module ibex_top import
ibex_pkg::*;` (line 15) — wildcard import. The ARCH source SHALL `use
IbexPkg;` (or the equivalent ARCH-side package name) at file scope to
get the `ibex_mubi_t`, `IbexMuBiOff`, `RV32MFast`, etc. names. The
`prim_ram_1p_pkg` types (`ram_1p_cfg_t`, `ram_1p_cfg_rsp_t`) and the
`prim_secded_pkg` constants are also referenced; check that the
arch-com-allowed `use` list includes them, or stub the relevant types
locally (the cfg ports are sunk under `ICache=0`, so a typedef alias
suffices).

**N-23: `scramble_key_valid_q` constant-`1` is a contract with
`u_ibex_core`.** Under `ICacheScramble=0`, the `gen_noscramble` arm
ties `scramble_key_valid_q = 1`. This wire feeds
`u_ibex_core.ic_scr_key_valid_i` (`:396`), telling the core "the
scramble key is always valid". This is a deliberate contract; the
implementer MUST keep this `1` (NOT `0`).

**N-24: `core_alert_*` internal wires.** The three internal wires
`core_alert_minor`, `core_alert_major_internal`, `core_alert_major_bus`
are sourced from `u_ibex_core` (`:452-:454`) and consumed by the
final OR-trees (`:1143-:1147`). Per C1 R18, all three are `0` in
every cycle under our pinning. The implementer SHALL keep them as
named internal wires (not constant-fold) for waveform stability.

**N-25: `lockstep_alert_*` internal wires.** Same shape as N-24 but
sourced from the `gen_no_lockstep` ties (R9) instead of a sub-module
output. Constant `0`.

**N-26: `crash_dump_t` packed-struct definition.** Defined at
`ibex_pkg.sv:15-:21` with five `logic [31:0]` fields. The C1 spec
(N-14) flagged this; the IbexTop source receives the struct from
`u_ibex_core` and presents it at `crash_dump_o` unchanged. No
IbexTop-side struct manipulation is required.

**N-27: `IC_NUM_WAYS = 2` under our pins.** Defined in `ibex_pkg`;
the auto-emitted C1 stub (`src/ibex_core.archi:26`) declares
`IC_NUM_WAYS = 2` as a const param. The IbexTop source SHALL use the
same value for the `ic_*_rdata` array depths and the `ram_cfg_rsp_*`
packed-Vec depth.

**N-28: `IC_INDEX_W`, `IC_TAG_SIZE`, `IC_LINE_BEATS`, `BUS_SIZE`,
`SCRAMBLE_KEY_W`, `SCRAMBLE_NONCE_W`.** All defined in `ibex_pkg`.
Under `ICache=0` they only matter for port-shape declarations; the
internal wires they size are tied to `0`. The implementer SHALL
import them via `use IbexPkg;` and reference them by name (not
materialize numeric values).

**N-29: Behavioural ambiguity to flag (`prim_buf` semantics under
verilator/synth).** Upstream `prim_buf` is documented as a synthesis
optimization barrier — semantically a wire, but flagged with
`size_only` / `keep` attributes so synthesis doesn't fold it into
the surrounding logic. ARCH lowering SHALL preserve the
upstream-SV instance verbatim; the ARCH source MUST NOT replace the
`prim_buf` with a bare wire alias, or the synthesis-time
optimization barrier is lost.

**N-30: `ASSERT*` macros are sim-only.** All `` `ASSERT_KNOWN ``,
`` `ASSERT_KNOWN_IF ``, `` `ASSERT `` invocations in `ibex_top.sv`
(lines 1150-1174, 1344-1391) are not part of the behavioural spec.
ARCH does not model SVAs; the implementer SHALL NOT attempt to
express these as functional logic. The `INC_ASSERT`-only
`g_dside_tracker` flop chain (lines 1190-1235) and the `g_mem_ecc_asserts`
SECDED decoders (lines 1374, 1383) are likewise out of scope.

**N-31: `crash_dump_o` connectivity assertions are sim-only.** Upstream
lines 1357-1364 sample `u_ibex_core.pc_id`, `pc_if`,
`load_store_unit_i.addr_last_q`, `cs_registers_i.mepc_q`, and
`cs_registers_i.mtval_q` via SV hierarchical reference and check that
they match `crash_dump_o.{current_pc, next_pc, last_data_addr,
exception_pc, exception_addr}`. These are sim-only assertions; the
behavioural contract (R12) is just "direct pass-through from
`u_ibex_core.crash_dump_o`".

**N-32: Behavioural ambiguity to flag — the `unused_ram_inputs`
sink uses `&` reduction over multi-bit signals.** Upstream `:761-:763`:
```
unused_ram_inputs = (|ic_tag_req) & ic_tag_write & (|ic_tag_addr) & ...
```
This is `|`-reduction of multi-bit signals followed by `&` of
1-bit results. Under our pins all the RHS values are `0` so the
overall result is `0`. The implementer SHALL emit a semantically
equivalent reduction (any reduction that absorbs every term works for
lint).

**N-33: The `pmp_cfg_t [16]`, `[33:0] [16]`, `pmp_mseccfg_t`
parameter-default expressions.** Upstream lines 21-23 declare:
- `PMPRstCfg[PMP_MAX_REGIONS] = ibex_pkg::PmpCfgRst`,
- `PMPRstAddr[PMP_MAX_REGIONS] = ibex_pkg::PmpAddrRst`,
- `PMPRstMsecCfg = ibex_pkg::PmpMseccfgRst`.

The auto-emitted C1 stub already accepts these as typed-array params
(lines 39-41 of `src/ibex_core.archi`). The IbexTop source SHALL pass
them through as the same names; no const-expression evaluation is
required at the IbexTop scope. If arch-com cannot accept
`pmp_cfg_t [16]` as an IbexTop param shape, the fallback is to
inline-default to `0`-initialized arrays and let the SoC override at
the bind site.

**N-34: `RndCnst*` parameter pass-through.** `RndCnstLfsrSeed` and
`RndCnstLfsrPerm` reach `u_ibex_core` (where they seed an internal
LFSR). `RndCnstIbexKey` and `RndCnstIbexNonce` reach the dead
`gen_scramble` flop bank only (R8); under our pins they are absorbed
by `unused_scramble_inputs`. All four SHALL be passed as IbexTop
params.

**N-35: `ibex_top` does not see performance counters.** The HPM
counters live inside `ibex_cs_registers` (which is instantiated
inside `u_ibex_core`); they are not visible at the IbexTop boundary.
`MHPMCounterNum` and `MHPMCounterWidth` are pure pass-through
parameters.

**N-36: ARCH-side construct selection is in the proposal, not here.**
Per the methodology, this spec describes upstream behaviour only.
The proposal selects `module` (not `pipeline` / `fsm` / `thread`) for
IbexTop; that decision is documented in the proposal's construct
enumeration table. If the implementer's pilot encounters a tooling
block, the proposal Risks section is the reference, not this spec.
