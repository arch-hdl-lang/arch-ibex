# IbexIfStage — port contract + behavior

## Purpose

`IbexIfStage` is the instruction-fetch (IF) stage container of the Ibex
pipeline. It selects the next program counter (PC), drives the
prefetch buffer to fetch the corresponding 32-bit instruction word
from the instruction bus, expands compressed (RV32C) instructions into
their full 32-bit form, combines bus-side and PMP-side fetch errors,
and latches the result into the IF→ID pipeline registers consumed by
the ID stage. It sits between the controller / exception PC sources
(producers driving `pc_mux_i`, `exc_pc_mux_i`, `branch_target_ex_i`,
the various CSR PC inputs) and the ID stage (consuming the
`instr_*_id_o` outputs).

This spec describes behavior under the following pinned parameter
values (matching `~/github/arch-ibex/soc/ibex_mini_soc.sv`):

| Parameter           | Pinned value             | Effect on this spec |
|---------------------|--------------------------|---------------------|
| `ICache`            | `1'b0`                   | Only the prefetch-buffer fetch path exists. ICache outputs are tied to 0. |
| `BranchPredictor`   | `1'b0`                   | No skid buffer; `predict_branch_taken = 0`, `predict_branch_pc = 0`, `instr_bp_taken_o = 0`. |
| `DummyInstructions` | `1'b0`                   | No dummy-instruction insertion; `dummy_instr_id_o = 0`, `stall_dummy_instr = 0`. |
| `MemECC`            | `1'b0`                   | No SECDED decode; `instr_intg_err = 0`, `MemDataWidth = 32`. |
| `PCIncrCheck`       | `1'b0`                   | `pc_mismatch_alert_o = 0`. |
| `ResetAll`          | `1'b0`                   | IF→ID pipeline registers use no-reset clocked write-enable. The two state regs (`instr_valid_id_q`, `instr_new_id_q`) keep async-low reset. |
| `RV32ZC`            | `RV32ZcaZcbZcmp`         | Forwarded to the compressed decoder; affects which compressed encodings expand. |
| `DmHaltAddr`        | `32'h1A11_0800`          | Constant `EXC_PC_DBD` mux output. |
| `DmExceptionAddr`   | `32'h1A11_0808`          | Constant `EXC_PC_DBG_EXC` mux output. |

## Port contract

### Clock + reset

| Direction | Name      | Type / Width             | Role |
|-----------|-----------|--------------------------|------|
| in        | `clk_i`   | `Clock<SysDomain>`       | System clock (rising-edge sampled). |
| in        | `rst_ni`  | `Reset<Async, Low>`      | Active-low asynchronous reset. |

### Boot

| Direction | Name          | Type / Width   | Role |
|-----------|---------------|----------------|------|
| in        | `boot_addr_i` | `UInt<32>`     | Boot PC base; bits `[31:8]` form the upper half of the boot/`PC_BOOT` and (under `BranchPredictor=0`) `PC_BP` mux outputs. Bits `[7:0]` are unused. |

### Instruction-bus side (driven by the SoC)

| Direction | Name             | Type / Width   | Role |
|-----------|------------------|----------------|------|
| in        | `req_i`          | `Bool`         | Instruction-fetch enable from the controller. |
| out       | `instr_req_o`    | `Bool`         | Forwarded from the prefetch buffer's `instr_req_o`. |
| out       | `instr_addr_o`   | `UInt<32>`     | Forwarded from the prefetch buffer's `instr_addr_o`. |
| in        | `instr_gnt_i`    | `Bool`         | Bus grant; consumed by the prefetch buffer. |
| in        | `instr_rvalid_i` | `Bool`         | Bus rvalid; consumed by the prefetch buffer. |
| in        | `instr_rdata_i`  | `UInt<32>`     | Bus read data (32 bits under `MemECC=0`). |
| in        | `instr_bus_err_i`| `Bool`         | Bus error flag from the SoC. |
| out       | `instr_intg_err_o` | `Bool`       | Always 0 under `MemECC=0`. |

### ICache tieoff outputs (must be driven 0)

| Direction | Name                   | Type / Width   | Constant value |
|-----------|------------------------|----------------|----------------|
| out       | `ic_tag_req_o`         | `UInt<IC_NUM_WAYS>` | `0` |
| out       | `ic_tag_write_o`       | `Bool`         | `0` |
| out       | `ic_tag_addr_o`        | `UInt<IC_INDEX_W>` | `0` |
| out       | `ic_tag_wdata_o`       | `UInt<TagSizeECC>` | `0` |
| out       | `ic_data_req_o`        | `UInt<IC_NUM_WAYS>` | `0` |
| out       | `ic_data_write_o`      | `Bool`         | `0` |
| out       | `ic_data_addr_o`       | `UInt<IC_INDEX_W>` | `0` |
| out       | `ic_data_wdata_o`      | `UInt<LineSizeECC>` | `0` |
| out       | `ic_scr_key_req_o`     | `Bool`         | `0` |
| out       | `icache_ecc_error_o`   | `Bool`         | `0` |

### Unused inputs (drive into `let unused_*` absorbers)

`ic_tag_rdata_i` (unpacked Vec), `ic_data_rdata_i` (unpacked Vec),
`ic_scr_key_valid_i`, `icache_enable_i`, `icache_inval_i`,
`dummy_instr_en_i`, `dummy_instr_mask_i: UInt<3>`,
`dummy_instr_seed_en_i`, `dummy_instr_seed_i: UInt<32>`,
`boot_addr_i[7:0]`, `csr_mtvec_i[7:0]`, `exc_cause.irq_ext`,
`exc_cause.irq_int`.

### IF→ID pipeline outputs (consumed by ID stage)

| Direction | Name                       | Type / Width  | Role |
|-----------|----------------------------|---------------|------|
| out       | `instr_valid_id_o`         | `Bool`        | An instruction sits in the IF→ID register and is valid for ID consumption. |
| out       | `instr_new_id_o`           | `Bool`        | An instruction *just landed* in the IF→ID register this cycle (one-cycle pulse). |
| out       | `instr_rdata_id_o`         | `UInt<32>`    | The 32-bit instruction (post-compressed-expansion). |
| out       | `instr_rdata_alu_id_o`     | `UInt<32>`    | Replicated copy of `instr_rdata_id_o` for ALU-side fan-out timing. |
| out       | `instr_rdata_c_id_o`       | `UInt<16>`    | The original lower-16-bit half-word from fetch (for debug / tracing). |
| out       | `instr_is_compressed_id_o` | `Bool`        | Latched from compressed decoder's `is_compressed_o`. |
| out       | `instr_gets_expanded_id_o` | `InstrExp`    | Latched from compressed decoder's `gets_expanded_o`. Enum: `INSTR_NOT_EXPANDED` / `INSTR_EXPANDED` / `INSTR_EXPANDED_LAST`. |
| out       | `instr_expanded_id_o`      | `UInt<16>`    | Latched copy of the original 16-bit half-word (separate from `instr_rdata_c_id_o` only under DummyInstructions=1; under DummyInstructions=0 the two regs hold the same value). |
| out       | `illegal_c_insn_id_o`      | `Bool`        | Latched from compressed decoder's `illegal_instr_o`. |
| out       | `instr_fetch_err_o`        | `Bool`        | Latched combined fetch error (bus + PMP). |
| out       | `instr_fetch_err_plus2_o`  | `Bool`        | Latched: error came from the second 16-bit half (`fetch_addr[1] & ~is_compressed & pmp_err_if_plus2_i`). |
| out       | `pc_id_o`                  | `UInt<32>`    | Latched current PC at the time the instruction was registered. |
| out       | `dummy_instr_id_o`         | `Bool`        | Always 0 under `DummyInstructions=0`. |
| out       | `instr_bp_taken_o`         | `Bool`        | Always 0 under `BranchPredictor=0`. |

### ID→IF control inputs

| Direction | Name                      | Type / Width  | Role |
|-----------|---------------------------|---------------|------|
| in        | `instr_valid_clear_i`     | `Bool`        | Synchronous clear for `instr_valid_id_q` (e.g. instruction completion or exception). |
| in        | `id_in_ready_i`           | `Bool`        | ID stage can accept a new instruction this cycle. |
| in        | `pc_set_i`                | `Bool`        | A new PC has been driven on `pc_mux_i`; take the branch. |
| in        | `pc_mux_i`                | `PcSel`       | PC mux selector: `PC_BOOT`, `PC_JUMP`, `PC_EXC`, `PC_ERET`, `PC_DRET`, `PC_BP`. Under `BranchPredictor=0`, `PC_BP` collapses to the boot path. |
| in        | `nt_branch_mispredict_i`  | `Bool`        | Not-taken branch in ID/EX was mispredicted (predicted taken). Mutually exclusive with `pc_set_i` (see Integration constraints). |
| in        | `nt_branch_addr_i`        | `UInt<32>`    | Replay address for not-taken-mispredict path. |
| in        | `exc_pc_mux_i`            | `ExcPcSel`    | Exception PC selector: `EXC_PC_EXC`, `EXC_PC_IRQ`, `EXC_PC_DBD`, `EXC_PC_DBG_EXC`. |
| in        | `exc_cause`               | `ExcCause`    | Struct: `{irq_int: Bool, irq_ext: Bool, lower_cause: UInt<5>}`. Only `lower_cause` is read for IRQ vectoring; `irq_int` selects NMI vs vectorised IRQ. |
| in        | `branch_target_ex_i`      | `UInt<32>`    | EX-stage branch target (used by `PC_JUMP`). |
| in        | `csr_mepc_i`              | `UInt<32>`    | M-mode exception PC (used by `PC_ERET`). |
| in        | `csr_depc_i`              | `UInt<32>`    | Debug exception PC (used by `PC_DRET`). |
| in        | `csr_mtvec_i`             | `UInt<32>`    | M-mode trap vector base (used by `PC_EXC` / `PC_IRQ` exception PC mux). Bits `[7:0]` are unused. |
| out       | `csr_mtvec_init_o`        | `Bool`        | Pulses high on the cycle ID issues a `PC_BOOT` set; signals the CS register file to initialise `mtvec`. |
| in        | `pmp_err_if_i`            | `Bool`        | PMP error on current instruction address. |
| in        | `pmp_err_if_plus2_i`      | `Bool`        | PMP error on second 16-bit half (for unaligned uncompressed instructions crossing a region boundary). |
| out       | `pc_if_o`                 | `UInt<32>`    | Current IF-stage PC. Equals the prefetch buffer's `addr_o` (= `fetch_addr`). |
| out       | `if_busy_o`               | `Bool`        | Equals the prefetch buffer's `busy_o`. |
| out       | `pc_mismatch_alert_o`     | `Bool`        | Always 0 under `PCIncrCheck=0`. |

## Requirements

### Requirement 1: Exception PC mux

The IF stage MUST drive an internal `exc_pc: UInt<32>` signal selected
by `exc_pc_mux_i` per the table below. This signal is one source for
the fetch address mux (Requirement 2).

It MUST also drive an internal `irq_vec: UInt<5>` selector that takes
`exc_cause.lower_cause` by default but is forced to `5'd31` (the NMI
vector) when `exc_cause.irq_int = 1`.

| `exc_pc_mux_i` | `exc_pc` value                                      |
|----------------|-----------------------------------------------------|
| `EXC_PC_EXC`   | `{csr_mtvec_i[31:8], 8'h00}`                        |
| `EXC_PC_IRQ`   | `{csr_mtvec_i[31:8], 1'b0, irq_vec, 2'b00}`         |
| `EXC_PC_DBD`   | `DmHaltAddr` (= `32'h1A11_0800` under SoC pinning)  |
| `EXC_PC_DBG_EXC` | `DmExceptionAddr` (= `32'h1A11_0808`)             |
| (default)      | `{csr_mtvec_i[31:8], 8'h00}`                        |

#### Scenario: vectorised external IRQ

Inputs: `exc_pc_mux_i = EXC_PC_IRQ`, `csr_mtvec_i = 32'h1000_2000`,
`exc_cause = {irq_int: 0, irq_ext: 1, lower_cause: 5'd11}`.
Expected: `irq_vec = 5'd11`, `exc_pc = {24'h1000_20, 1'b0, 5'd11, 2'b00}` =
`32'h1000_202C`.

#### Scenario: NMI override

Inputs: `exc_pc_mux_i = EXC_PC_IRQ`, `csr_mtvec_i = 32'h1000_2000`,
`exc_cause = {irq_int: 1, irq_ext: 0, lower_cause: 5'd03}`.
Expected: `irq_vec = 5'd31` (override; the `lower_cause: 5'd03` is
ignored), `exc_pc = 32'h1000_207C`.

#### Scenario: synchronous exception entry

Inputs: `exc_pc_mux_i = EXC_PC_EXC`, `csr_mtvec_i = 32'h1000_2000`.
Expected: `exc_pc = 32'h1000_2000` (lower 8 bits forced to zero).

#### Scenario: debug entry

Inputs: `exc_pc_mux_i = EXC_PC_DBD`. Expected: `exc_pc =
32'h1A11_0800`.

#### Scenario: debug exception

Inputs: `exc_pc_mux_i = EXC_PC_DBG_EXC`. Expected: `exc_pc =
32'h1A11_0808`.

### Requirement 2: Fetch address mux

The IF stage MUST drive an internal `fetch_addr_n: UInt<32>` selected
by an internal `pc_mux_internal: PcSel` signal. Under
`BranchPredictor=0`, `pc_mux_internal = pc_mux_i` directly (no skid
override).

| `pc_mux_internal` | `fetch_addr_n` value                            |
|-------------------|-------------------------------------------------|
| `PC_BOOT`         | `{boot_addr_i[31:8], 8'h80}`                    |
| `PC_JUMP`         | `branch_target_ex_i`                            |
| `PC_EXC`          | `exc_pc` (Requirement 1)                        |
| `PC_ERET`         | `csr_mepc_i`                                    |
| `PC_DRET`         | `csr_depc_i`                                    |
| `PC_BP`           | `{boot_addr_i[31:8], 8'h80}` (BranchPredictor=0 collapse) |
| (default)         | `{boot_addr_i[31:8], 8'h80}`                    |

#### Scenario: boot PC

Inputs: `pc_mux_i = PC_BOOT`, `boot_addr_i = 32'h0010_0000`.
Expected: `fetch_addr_n = 32'h0010_0080`.

#### Scenario: jump-target

Inputs: `pc_mux_i = PC_JUMP`, `branch_target_ex_i = 32'h0010_1234`.
Expected: `fetch_addr_n = 32'h0010_1234`.

#### Scenario: ERET / mret return

Inputs: `pc_mux_i = PC_ERET`, `csr_mepc_i = 32'h0010_2000`.
Expected: `fetch_addr_n = 32'h0010_2000`.

#### Scenario: BP collapse

Inputs: `pc_mux_i = PC_BP`, `boot_addr_i = 32'h0010_0000`. Under
`BranchPredictor=0`: Expected: `fetch_addr_n = 32'h0010_0080`.

### Requirement 3: Branch request synthesis

The IF stage MUST drive an internal `branch_req: Bool` to `pc_set_i`
under `BranchPredictor=0`. (In the unrestricted upstream this is
`pc_set_i | predict_branch_taken`; with `predict_branch_taken = 0`
hard-tied this collapses.)

It MUST drive `prefetch_branch = branch_req | nt_branch_mispredict_i`
and `prefetch_addr = branch_req ? {fetch_addr_n[31:1], 1'b0} :
nt_branch_addr_i`.

`prefetch_addr` MUST force bit 0 to zero on the branch path so the
prefetch buffer always sees a half-word-aligned target.

#### Scenario: regular `pc_set_i`

Inputs: `pc_set_i = 1`, `nt_branch_mispredict_i = 0`, `fetch_addr_n =
32'h0010_0083`.
Expected: `branch_req = 1`, `prefetch_branch = 1`, `prefetch_addr =
32'h0010_0082` (bit 0 forced to 0).

#### Scenario: nt-branch misprediction replay

Inputs: `pc_set_i = 0`, `nt_branch_mispredict_i = 1`, `nt_branch_addr_i
= 32'h0010_4000`.
Expected: `branch_req = 0`, `prefetch_branch = 1`, `prefetch_addr =
32'h0010_4000` (no bit-0 force; the replay address is the source).

### Requirement 4: Prefetch buffer wiring + valid squash

The IF stage MUST instantiate `IbexPrefetchBuffer` with the parameter
`ResetAll = 1'b0`. Its inputs and outputs MUST be wired as follows:

| Sub-port             | Connected to (in the IF stage)                          |
|----------------------|---------------------------------------------------------|
| `clk_i`              | `clk_i` |
| `rst_ni`             | `rst_ni` |
| `req_i`              | `req_i` |
| `branch_i`           | `prefetch_branch` (Requirement 3) |
| `addr_i`             | `prefetch_addr` (Requirement 3) |
| `ready_i`            | `fetch_ready` (= `id_in_ready_i & ~stall_dummy_instr` = `id_in_ready_i` under DummyInstructions=0) |
| `valid_o`            | `fetch_valid_raw` |
| `rdata_o`            | `fetch_rdata` |
| `addr_o`             | `fetch_addr` |
| `err_o`              | `fetch_err` |
| `err_plus2_o`        | `fetch_err_plus2` |
| `instr_req_o`        | `instr_req_o` (forwarded to module port) |
| `instr_addr_o`       | `instr_addr_o` (forwarded) |
| `instr_gnt_i`        | `instr_gnt_i` |
| `instr_rvalid_i`     | `instr_rvalid_i` |
| `instr_rdata_i`      | `instr_rdata_i[31:0]` (32 bits under MemECC=0) |
| `instr_err_i`        | `instr_err` (= `instr_intg_err | instr_bus_err_i` = `instr_bus_err_i` under MemECC=0) |
| `busy_o`             | `prefetch_busy` (forwarded to `if_busy_o`) |

The IF stage MUST squash the prefetch-buffer valid output on
misprediction:

`fetch_valid = fetch_valid_raw & ~nt_branch_mispredict_i;`

#### Scenario: clean fetch passes through

Inputs: `fetch_valid_raw = 1`, `nt_branch_mispredict_i = 0`.
Expected: `fetch_valid = 1`.

#### Scenario: fetch valid squashed on misprediction

Inputs: `fetch_valid_raw = 1`, `nt_branch_mispredict_i = 1`.
Expected: `fetch_valid = 0`.

### Requirement 5: Compressed decoder wiring

The IF stage MUST instantiate `IbexCompressedDecoder` with parameters
`RV32ZC = RV32ZcaZcbZcmp` and `ResetAll = 1'b0`. Its inputs MUST be:

| Sub-port            | Connected to                                  |
|---------------------|-----------------------------------------------|
| `clk_i`             | `clk_i` |
| `rst_ni`            | `rst_ni` |
| `valid_i`           | `fetch_valid & ~fetch_err` |
| `id_in_ready_i`     | `id_in_ready_i & ~pc_set_i` |
| `instr_i`           | `if_instr_rdata` (= `fetch_rdata`) |
| `instr_o`           | `instr_decompressed` |
| `is_compressed_o`   | `instr_is_compressed` |
| `gets_expanded_o`   | `instr_gets_expanded` |
| `illegal_instr_o`   | `illegal_c_insn` |

The decoder's `valid_i` qualifier `& ~fetch_err` ensures fetch errors
do not trigger spurious compressed-instruction handling. The
`id_in_ready_i & ~pc_set_i` qualifier on the decoder's
`id_in_ready_i` ensures that a pending PC-set (branch) prevents the
decoder from advancing.

### Requirement 6: Instruction-error combination

The IF stage MUST combine bus-side and PMP-side errors into a single
`if_instr_err: Bool` signal:

```
if_instr_pmp_err   = pmp_err_if_i
                   | (if_instr_addr[1] & ~instr_is_compressed & pmp_err_if_plus2_i);
if_instr_err       = if_instr_bus_err | if_instr_pmp_err;
if_instr_err_plus2 = ((if_instr_addr[1] & ~instr_is_compressed & pmp_err_if_plus2_i)
                      | fetch_err_plus2)
                     & ~pmp_err_if_i;
```

Where `if_instr_bus_err = fetch_err`, `if_instr_addr = fetch_addr`,
`if_instr_rdata = fetch_rdata`, `if_instr_valid = fetch_valid &
~stall_dummy_instr` (= `fetch_valid` under DummyInstructions=0).

`instr_intg_err_o` MUST equal `instr_intg_err & instr_rvalid_i`
(= `0` under MemECC=0 since `instr_intg_err = 0`).

#### Scenario: bus error only

Inputs: `fetch_err = 1`, `pmp_err_if_i = 0`, `pmp_err_if_plus2_i = 0`.
Expected: `if_instr_err = 1`, `if_instr_err_plus2 = fetch_err_plus2`.

#### Scenario: PMP plus2 on misaligned uncompressed

Inputs: `fetch_err = 0`, `pmp_err_if_i = 0`, `pmp_err_if_plus2_i = 1`,
`fetch_addr[1] = 1`, `instr_is_compressed = 0`.
Expected: `if_instr_err = 1`, `if_instr_err_plus2 = 1`.

#### Scenario: PMP first-half overrides plus2

Inputs: `pmp_err_if_i = 1`, `pmp_err_if_plus2_i = 1`. Expected:
`if_instr_err = 1`, `if_instr_err_plus2 = 0` (the `& ~pmp_err_if_i`
mask suppresses plus2 when the first half already errored).

### Requirement 7: IF→ID pipeline-register write enable

The IF stage MUST compute:

```
instr_valid_id_d = (if_instr_valid & id_in_ready_i & ~pc_set_i)
                 | (instr_valid_id_q & ~instr_valid_clear_i);
instr_new_id_d   = if_instr_valid & id_in_ready_i & ~pc_set_i;
if_id_pipe_reg_we = instr_new_id_d;
```

The IF→ID pipeline registers are written on a rising edge of `clk_i`
ONLY when `if_id_pipe_reg_we = 1`. They have NO reset (under
`ResetAll=0`) — at reset their values are X / unspecified, but
`instr_valid_id_q = 0` ensures no consumer treats them as valid.

The latched values are:

| Pipe reg                 | Source on the writing cycle |
|--------------------------|-----------------------------|
| `instr_rdata_id_o`       | `instr_decompressed` (DummyInstructions=0 path) |
| `instr_rdata_alu_id_o`   | `instr_decompressed` (replicated for fan-out) |
| `instr_fetch_err_o`      | `if_instr_err` |
| `instr_fetch_err_plus2_o`| `if_instr_err_plus2` |
| `instr_rdata_c_id_o`     | `if_instr_rdata[15:0]` |
| `instr_is_compressed_id_o` | `instr_is_compressed` |
| `instr_gets_expanded_id_o` | `instr_gets_expanded` |
| `instr_expanded_id_o`    | `if_instr_rdata[15:0]` (same as `instr_rdata_c_id_o` under DummyInstructions=0) |
| `illegal_c_insn_id_o`    | `illegal_c_insn` |
| `pc_id_o`                | `pc_if_o` (= `fetch_addr`) |

#### Scenario: clean register write

Setup at posedge: `if_instr_valid = 1`, `id_in_ready_i = 1`, `pc_set_i
= 0`, `instr_decompressed = 32'hDEAD_BEEF`, `fetch_addr =
32'h0010_0084`, `instr_is_compressed = 0`,
`instr_gets_expanded = INSTR_NOT_EXPANDED`, `if_instr_err = 0`.
Expected after posedge: `instr_rdata_id_o = 32'hDEAD_BEEF`, `pc_id_o =
32'h0010_0084`, `instr_is_compressed_id_o = 0`, `instr_fetch_err_o = 0`.

#### Scenario: write suppressed by `pc_set_i`

Setup: `if_instr_valid = 1`, `id_in_ready_i = 1`, `pc_set_i = 1` (a
branch is being taken).
Expected: `if_id_pipe_reg_we = 0` → none of the pipe regs change.

#### Scenario: write suppressed by `~id_in_ready_i`

Setup: `if_instr_valid = 1`, `id_in_ready_i = 0`.
Expected: `if_id_pipe_reg_we = 0` → no pipe-reg update; the prefetched
instruction is held by the prefetch buffer (its `ready_i` is `0`).

### Requirement 8: `instr_valid_id_q` / `instr_new_id_q` state register

These two state registers are async-low-reset clocked flops driven by
the `_d` signals from Requirement 7:

```
@(posedge clk_i, negedge rst_ni)
  if (!rst_ni)  { instr_valid_id_q, instr_new_id_q } <= 2'b00;
  else          { instr_valid_id_q, instr_new_id_q } <= { instr_valid_id_d, instr_new_id_d };
```

The IF stage MUST drive `instr_valid_id_o = instr_valid_id_q` and
`instr_new_id_o = instr_new_id_q` (both registered, NOT combinational
from the `_d` signals).

#### Scenario: valid latches and holds across stalls

At cycle T, the conditions for `instr_new_id_d = 1` hold (new
instruction lands). At T+1, `instr_valid_clear_i = 0` and the
new-instruction conditions are false (e.g. ID stalls).
Expected: `instr_valid_id_o` is `1` at T+1 (held by the
`(instr_valid_id_q & ~instr_valid_clear_i)` self-feedback);
`instr_new_id_o` is `0` at T+1 (one-cycle pulse).

#### Scenario: explicit clear

At cycle T, `instr_valid_id_q = 1`. At T, `instr_valid_clear_i = 1`
and the new-instruction conditions are false.
Expected: `instr_valid_id_q` becomes 0 at T+1.

#### Scenario: reset

`rst_ni` falls. Expected: `instr_valid_id_q = 0`, `instr_new_id_q = 0`
asynchronously.

### Requirement 9: `csr_mtvec_init_o`

`csr_mtvec_init_o = (pc_mux_i == PC_BOOT) & pc_set_i;` (pure
combinational).

#### Scenario: boot pulse

Inputs: `pc_mux_i = PC_BOOT`, `pc_set_i = 1`.
Expected: `csr_mtvec_init_o = 1`.

#### Scenario: any other PC mux

Inputs: `pc_mux_i = PC_JUMP`, `pc_set_i = 1`. Expected:
`csr_mtvec_init_o = 0`.

### Requirement 10: ICache + branch-predictor + dummy-instruction tieoffs

Under the SoC's parameter pinning, the following outputs MUST be
driven to the constants below combinationally (no register storage):

| Output                | Value |
|-----------------------|-------|
| `ic_tag_req_o`        | `0`   |
| `ic_tag_write_o`      | `0`   |
| `ic_tag_addr_o`       | `0`   |
| `ic_tag_wdata_o`      | `0`   |
| `ic_data_req_o`       | `0`   |
| `ic_data_write_o`     | `0`   |
| `ic_data_addr_o`      | `0`   |
| `ic_data_wdata_o`     | `0`   |
| `ic_scr_key_req_o`    | `0`   |
| `icache_ecc_error_o`  | `0`   |
| `dummy_instr_id_o`    | `0`   |
| `instr_bp_taken_o`    | `0`   |
| `pc_mismatch_alert_o` | `0`   |
| `instr_intg_err_o`    | `0`   |

`if_busy_o = prefetch_busy`. `pc_if_o = fetch_addr`.

The unused inputs (`icache_enable_i`, `icache_inval_i`,
`ic_scr_key_valid_i`, `ic_tag_rdata_i`, `ic_data_rdata_i`,
`dummy_instr_en_i`, `dummy_instr_mask_i`, `dummy_instr_seed_en_i`,
`dummy_instr_seed_i`, `boot_addr_i[7:0]`, `csr_mtvec_i[7:0]`,
`exc_cause.irq_ext`, `exc_cause.irq_int`) MUST each be absorbed into
an `let unused_*` (or equivalent) so SoC-level lint doesn't flag them
as undriven loads.

## Integration constraints

### Producer-side

1. `pc_set_i` and `nt_branch_mispredict_i` are mutually exclusive:
   the upstream `NoMispredBranch` assertion states that
   `nt_branch_mispredict_i` implies `~branch_req` (= `~pc_set_i` under
   `BranchPredictor=0`). The IF stage's `prefetch_branch =
   branch_req | nt_branch_mispredict_i` and `prefetch_addr` mux assume
   this exclusivity — they don't define behavior when both are high
   simultaneously, and the controller MUST not assert both.

2. `pc_mux_i` is meaningful only on cycles where `pc_set_i = 1`.
   On other cycles its value is don't-care (the fetch_addr_n mux
   output is consumed only when `branch_req = 1` →
   `prefetch_branch = 1` → prefetch buffer takes the new address).

3. `exc_pc_mux_i`, `csr_mtvec_i`, `csr_mepc_i`, `csr_depc_i`,
   `branch_target_ex_i`, `exc_cause` are meaningful only when their
   corresponding `pc_mux_i` value selects them. On other cycles they
   may glitch.

4. `pmp_err_if_i` and `pmp_err_if_plus2_i` are evaluated by the PMP
   in parallel with the prefetch fetch and must be valid in the same
   cycle as `fetch_valid`.

### Consumer-side (ID stage)

1. `instr_valid_id_o` MUST be held by the IF stage until
   `instr_valid_clear_i` is asserted (per upstream comment "Valid is
   held until it is explicitly cleared (due to an instruction
   completing or an exception)"). Requirement 8's self-feedback
   `(instr_valid_id_q & ~instr_valid_clear_i)` carries this.

2. `instr_new_id_o` is a single-cycle pulse. The ID stage / RVFI uses
   it to detect "an instruction just landed" without confusing it
   with held-valid.

3. The ID stage samples `instr_rdata_id_o`, `instr_rdata_c_id_o`,
   `instr_is_compressed_id_o`, `instr_gets_expanded_id_o`,
   `instr_expanded_id_o`, `illegal_c_insn_id_o`, `instr_fetch_err_o`,
   `instr_fetch_err_plus2_o`, `pc_id_o` on cycles where
   `instr_valid_id_o = 1`. These MUST all be coherent (latched on the
   same cycle by the same `if_id_pipe_reg_we`).

4. `instr_intg_err_o` is gated by `instr_rvalid_i` so it pulses only
   on the bus-side cycle the integrity error was detected. Under
   MemECC=0 this output is constant 0.

5. `if_busy_o` propagates the prefetch buffer's `busy_o` directly so
   the controller can wait for in-flight fetches to drain at debug /
   reset entry.

### Sub-module-side

1. `IbexPrefetchBuffer.ready_i` is wired to `id_in_ready_i &
   ~stall_dummy_instr` in upstream. Under DummyInstructions=0 the
   `~stall_dummy_instr` factor is constant 1, so `ready_i =
   id_in_ready_i`. The prefetch buffer holds its head value when
   `ready_i = 0`.

2. `IbexCompressedDecoder.id_in_ready_i` is wired to `id_in_ready_i &
   ~pc_set_i`. The `~pc_set_i` factor ensures a pending branch
   prevents the decoder from advancing past an instruction that's
   about to be discarded.

3. `IbexCompressedDecoder.valid_i` is wired to `fetch_valid &
   ~fetch_err`. A fetch with a bus / PMP error must not be presented
   to the decoder as valid; the IF stage routes the error through
   `if_instr_err` to the IF→ID pipeline register instead.

4. The compressed-decoder output `gets_expanded_o: InstrExp` is an
   enum (`INSTR_NOT_EXPANDED` / `INSTR_EXPANDED` /
   `INSTR_EXPANDED_LAST`). It is registered into
   `instr_gets_expanded_id_o` of the same enum type without
   translation.

## Spec notes

None — the upstream SoC pinning is unambiguous and every
parameter-gated branch resolves to a single concrete behavior.
