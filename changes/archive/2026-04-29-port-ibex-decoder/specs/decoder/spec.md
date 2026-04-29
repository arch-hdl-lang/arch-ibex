# Decoder Specification

## Purpose

The Ibex instruction decoder consumes a 32-bit RISC-V instruction word and
drives the ID-stage control plane: register-file selectors, immediate
extractors, ALU operator and operand-mux selectors, multiplier/divider
selectors, CSR access controls, LSU controls, and a handful of single-bit
flags for jumps, branches, traps, and CSR-illegal detection. All of its
outputs are pure combinational functions of its inputs — there is no
internal state when `RV32B = RV32BNone` (the `gen_rs3_flop` register is
elided in this configuration; `clk_i` / `rst_ni` exist only so the SVA
properties have something to sample). The decoder is the largest single
control-plane module in the Ibex core and produces ~50 outputs across
ten enumerated types.

For ID-stage timing, upstream replicates the instruction word into two
identical fan-out flops. `instr_rdata_i` drives the bulk of the
control logic (register read/write enables, LSU controls, illegal-insn
detection, mult/div operator, CSR controls, trap flags). A second
replica `instr_rdata_alu_i` drives the ALU-side outputs that sit on
the more critical path (`alu_operator_o`, `alu_op_a_mux_sel_o`,
`alu_op_b_mux_sel_o`, `imm_a_mux_sel_o`, `imm_b_mux_sel_o`,
`bt_a_mux_sel_o`, `bt_b_mux_sel_o`, `mult_sel_o`, `div_sel_o`,
`alu_multicycle_o`). The ARCH port boundary preserves both inputs so a
downstream synthesis flow can keep the same fan-out separation; in the
in-scope configuration both inputs receive identical 32-bit words.

## Port contract

In-scope parameters (per `proposal.md`): `RV32E = 0`, `RV32M =
RV32MFast`, `RV32B = RV32BNone`, `BranchTargetALU = 0`. The contract
below is written for that fixed parameter set. Parameters are listed
for completeness — the ARCH module must accept them at the boundary
even if it only honors the in-scope values.

| Direction | Name                    | Type     | Description |
|---|---|---|---|
| param | RV32E              | Bool                | RV32E mode flag — fixed `0` in scope. |
| param | RV32M              | UInt\<2\>           | M-extension config — fixed `2` (RV32MFast). |
| param | RV32B              | UInt\<2\>           | Bit-manipulation config — fixed `0` (RV32BNone). |
| param | BranchTargetALU    | Bool                | Separate branch-target ALU — fixed `0`. |
| in    | clk_i              | Clock               | Assertion-only; body is combinational. |
| in    | rst_ni             | Reset (active-low)  | Assertion-only; body is combinational. |
| in    | branch_taken_i     | Bool                | Registered branch decision (used only when `BranchTargetALU=1`; ignored in scope). |
| in    | instr_first_cycle_i| Bool                | High during the first execution cycle of a multi-cycle insn. |
| in    | instr_rdata_i      | UInt\<32\>          | Instruction word (drives non-ALU outputs and illegal detection). |
| in    | instr_rdata_alu_i  | UInt\<32\>          | Replicated instruction word (drives ALU-control outputs). |
| in    | illegal_c_insn_i   | Bool                | Compressed-decoder illegality flag — pass-through OR into `illegal_insn_o`. |
| out   | illegal_insn_o     | Bool                | Aggregate illegal-instruction signal. |
| out   | ebrk_insn_o        | Bool                | EBREAK detected. |
| out   | mret_insn_o        | Bool                | MRET detected. |
| out   | dret_insn_o        | Bool                | DRET detected. |
| out   | ecall_insn_o       | Bool                | ECALL detected. |
| out   | wfi_insn_o         | Bool                | WFI detected. |
| out   | jump_set_o         | Bool                | Pulse: ALU should compute jump target this cycle. |
| out   | icache_inval_o     | Bool                | FENCE.I invalidation pulse. |
| out   | imm_a_mux_sel_o    | UInt\<1\>           | Operand-A immediate selector — encoded per `ibex_pkg::imm_a_sel_e` (see §Enum encodings). |
| out   | imm_b_mux_sel_o    | UInt\<3\>           | Operand-B immediate selector — encoded per `ibex_pkg::imm_b_sel_e`. |
| out   | bt_a_mux_sel_o     | UInt\<2\>           | Branch-target operand-A selector — encoded per `ibex_pkg::op_a_sel_e`. |
| out   | bt_b_mux_sel_o     | UInt\<3\>           | Branch-target operand-B selector — encoded per `ibex_pkg::imm_b_sel_e`. |
| out   | imm_i_type_o       | UInt\<32\>          | Sign-extended I-type immediate. |
| out   | imm_s_type_o       | UInt\<32\>          | Sign-extended S-type immediate. |
| out   | imm_b_type_o       | UInt\<32\>          | Sign-extended B-type immediate (LSB always 0). |
| out   | imm_u_type_o       | UInt\<32\>          | U-type immediate (low 12 bits zero). |
| out   | imm_j_type_o       | UInt\<32\>          | Sign-extended J-type immediate (LSB always 0). |
| out   | zimm_rs1_type_o    | UInt\<32\>          | Zero-extended `rs1` field for CSRRxI. |
| out   | rf_wdata_sel_o     | UInt\<1\>           | Register-file write-data source — encoded per `ibex_pkg::rf_wd_sel_e`. |
| out   | rf_we_o            | Bool                | Register-file write enable (gated by illegal). |
| out   | rf_raddr_a_o       | UInt\<5\>           | Read port A address. |
| out   | rf_raddr_b_o       | UInt\<5\>           | Read port B address. |
| out   | rf_waddr_o         | UInt\<5\>           | Write address. |
| out   | rf_ren_a_o         | Bool                | Instruction reads `rs1`. |
| out   | rf_ren_b_o         | Bool                | Instruction reads `rs2`. |
| out   | alu_operator_o     | UInt\<7\>           | ALU operation — encoded per `ibex_pkg::alu_op_e`. |
| out   | alu_op_a_mux_sel_o | UInt\<2\>           | ALU operand-A source — encoded per `ibex_pkg::op_a_sel_e`. |
| out   | alu_op_b_mux_sel_o | UInt\<1\>           | ALU operand-B source — encoded per `ibex_pkg::op_b_sel_e`. |
| out   | alu_multicycle_o   | Bool                | Ternary bit-manip multicycle flag (always `0` in scope). |
| out   | mult_en_o          | Bool                | Enable multiplier (`mult_sel_o` masked by `~illegal_insn`). |
| out   | div_en_o           | Bool                | Enable divider (`div_sel_o` masked by `~illegal_insn`). |
| out   | mult_sel_o         | Bool                | Static multiplier mux selector. |
| out   | div_sel_o          | Bool                | Static divider mux selector. |
| out   | multdiv_operator_o | UInt\<2\>           | Mult/div operation — encoded per `ibex_pkg::md_op_e`. |
| out   | multdiv_signed_mode_o | UInt\<2\>        | Bit 1 = rs1 signed, bit 0 = rs2 signed. |
| out   | csr_access_o       | Bool                | CSR access in progress. |
| out   | csr_op_o           | UInt\<2\>           | CSR operation — encoded per `ibex_pkg::csr_op_e`. |
| out   | csr_addr_o         | UInt\<12\>          | CSR address (raw `instr_rdata_i[31:20]`). |
| out   | data_req_o         | Bool                | LSU transaction request. |
| out   | data_we_o          | Bool                | LSU write enable. |
| out   | data_type_o        | UInt\<2\>           | LSU access size: 0=word, 1=halfword, 2=byte. |
| out   | data_sign_extension_o | Bool             | LSU sign-extend on load. |
| out   | jump_in_dec_o      | Bool                | Jump being calculated this cycle. |
| out   | branch_in_dec_o    | Bool                | Branch being evaluated this cycle. |

### Enum encodings

Variants the decoder may emit on its ports, with the integer encoding
fixed by declaration order (or explicit literal) in `ibex_pkg.sv`.
Variants unreachable in the in-scope configuration are still listed so
the decoder cannot accidentally emit an undefined value, but the
**Reachable** column flags whether the in-scope decoder ever produces
that variant.

#### `opcode_e` — width 7

This enum classifies `instr_rdata_i[6:0]`. Only the listed encodings
are legal; any other value of bits `[6:0]` falls through the `case
(opcode)` default and produces `illegal_insn = 1`.

| Variant         | Hex  | Reachable | Notes |
|---|---|---|---|
| OPCODE_LOAD     | 0x03 | yes | I-type load |
| OPCODE_MISC_MEM | 0x0F | yes | FENCE/FENCE.I |
| OPCODE_OP_IMM   | 0x13 | yes | register-immediate ALU |
| OPCODE_AUIPC    | 0x17 | yes | AUIPC |
| OPCODE_STORE    | 0x23 | yes | S-type store |
| OPCODE_OP       | 0x33 | yes | register-register ALU + RV32M |
| OPCODE_LUI      | 0x37 | yes | LUI |
| OPCODE_BRANCH   | 0x63 | yes | conditional branch |
| OPCODE_JALR     | 0x67 | yes | JALR |
| OPCODE_JAL      | 0x6F | yes | JAL |
| OPCODE_SYSTEM   | 0x73 | yes | ECALL / EBREAK / MRET / DRET / WFI / CSR |

#### `alu_op_e` — width 7 (declaration-order encoding)

| Variant       | Int | Reachable in scope |
|---|---|---|
| ALU_ADD       | 0   | yes |
| ALU_SUB       | 1   | yes |
| ALU_XOR       | 2   | yes |
| ALU_OR        | 3   | yes |
| ALU_AND       | 4   | yes |
| ALU_XNOR      | 5   | no (RV32B-only) |
| ALU_ORN       | 6   | no (RV32B-only) |
| ALU_ANDN      | 7   | no (RV32B-only) |
| ALU_SRA       | 8   | yes |
| ALU_SRL       | 9   | yes |
| ALU_SLL       | 10  | yes |
| ALU_SRO       | 11  | no |
| ALU_SLO       | 12  | no |
| ALU_ROR       | 13  | no |
| ALU_ROL       | 14  | no |
| ALU_GREV      | 15  | no |
| ALU_GORC      | 16  | no |
| ALU_SHFL      | 17  | no |
| ALU_UNSHFL    | 18  | no |
| ALU_XPERM_N   | 19  | no |
| ALU_XPERM_B   | 20  | no |
| ALU_XPERM_H   | 21  | no |
| ALU_SH1ADD    | 22  | no |
| ALU_SH2ADD    | 23  | no |
| ALU_SH3ADD    | 24  | no |
| ALU_LT        | 25  | yes |
| ALU_LTU       | 26  | yes |
| ALU_GE        | 27  | yes |
| ALU_GEU       | 28  | yes |
| ALU_EQ        | 29  | yes |
| ALU_NE        | 30  | yes |
| ALU_MIN       | 31  | no |
| ALU_MINU      | 32  | no |
| ALU_MAX       | 33  | no |
| ALU_MAXU      | 34  | no |
| ALU_PACK      | 35  | no |
| ALU_PACKU     | 36  | no |
| ALU_PACKH     | 37  | no |
| ALU_SEXTB     | 38  | no |
| ALU_SEXTH     | 39  | no |
| ALU_CLZ       | 40  | no |
| ALU_CTZ       | 41  | no |
| ALU_CPOP      | 42  | no |
| ALU_SLT       | 43  | yes |
| ALU_SLTU      | 44  | yes (also the default) |
| ALU_CMOV      | 45  | no |
| ALU_CMIX      | 46  | no |
| ALU_FSL       | 47  | no |
| ALU_FSR       | 48  | no |
| ALU_BSET      | 49  | no |
| ALU_BCLR      | 50  | no |
| ALU_BINV      | 51  | no |
| ALU_BEXT      | 52  | no |
| ALU_BCOMPRESS | 53  | no |
| ALU_BDECOMPRESS | 54 | no |
| ALU_BFP       | 55  | no |
| ALU_CLMUL     | 56  | no |
| ALU_CLMULR    | 57  | no |
| ALU_CLMULH    | 58  | no |
| ALU_CRC32_B   | 59  | no |
| ALU_CRC32C_B  | 60  | no |
| ALU_CRC32_H   | 61  | no |
| ALU_CRC32C_H  | 62  | no |
| ALU_CRC32_W   | 63  | no |
| ALU_CRC32C_W  | 64  | no |

In-scope reachable subset: `{ADD, SUB, XOR, OR, AND, SRA, SRL, SLL, LT,
LTU, GE, GEU, EQ, NE, SLT, SLTU}`.

#### `op_a_sel_e` — width 2

| Variant      | Int |
|---|---|
| OP_A_REG_A   | 0 |
| OP_A_FWD     | 1 |
| OP_A_CURRPC  | 2 |
| OP_A_IMM     | 3 |

The decoder never emits `OP_A_FWD` in scope (forwarding is selected
elsewhere in the pipeline).

#### `op_b_sel_e` — width 1

| Variant      | Int |
|---|---|
| OP_B_REG_B   | 0 |
| OP_B_IMM     | 1 |

#### `imm_a_sel_e` — width 1

| Variant   | Int |
|---|---|
| IMM_A_Z   | 0 |
| IMM_A_ZERO| 1 |

#### `imm_b_sel_e` — width 3

| Variant       | Int |
|---|---|
| IMM_B_I       | 0 |
| IMM_B_S       | 1 |
| IMM_B_B       | 2 |
| IMM_B_U       | 3 |
| IMM_B_J       | 4 |
| IMM_B_INCR_PC | 5 |
| IMM_B_INCR_ADDR | 6 |

`IMM_B_INCR_ADDR` is unreachable from the decoder body in any
configuration.

#### `rf_wd_sel_e` — width 1

| Variant   | Int |
|---|---|
| RF_WD_EX  | 0 |
| RF_WD_CSR | 1 |

#### `csr_op_e` — width 2

| Variant      | Int |
|---|---|
| CSR_OP_READ  | 0 |
| CSR_OP_WRITE | 1 |
| CSR_OP_SET   | 2 |
| CSR_OP_CLEAR | 3 |

#### `md_op_e` — width 2

| Variant    | Int |
|---|---|
| MD_OP_MULL | 0 |
| MD_OP_MULH | 1 |
| MD_OP_DIV  | 2 |
| MD_OP_REM  | 3 |

#### `csr_num_e` — width 12

The decoder emits `csr_addr_o = instr_rdata_i[31:20]` raw — it does
not validate the 12-bit value against the enum (CSR existence and
privilege are checked downstream in `ibex_cs_registers.sv`). The full
`csr_num_e` enumeration is therefore not reproduced here; treat
`csr_addr_o` as an opaque 12-bit field passed through.

## Requirements

### Defaults when not overridden

The decoder's body is two parallel `always_comb` blocks (see
`ibex_decoder.sv:208`, `:673`). Both start by assigning every output
they own to a default value; the per-opcode arms then override only
the outputs they need to change. Outputs an opcode arm does not touch
keep their default value.

#### Scenario: defaults from main decode block (ref: ibex_decoder.sv:209-238)

- GIVEN any `instr_rdata_i`
- WHEN before any opcode-specific override fires
- THEN the following defaults hold:
  - `jump_in_dec_o = 0`, `jump_set_o = 0`, `branch_in_dec_o = 0`,
    `icache_inval_o = 0`
  - `multdiv_operator_o = MD_OP_MULL` (0), `multdiv_signed_mode_o = 2'b00`
  - `rf_wdata_sel_o = RF_WD_EX` (0), internal `rf_we = 0`,
    `rf_ren_a_o = 0`, `rf_ren_b_o = 0`
  - `csr_access_o = 0`, internal `csr_illegal = 0`,
    internal `csr_op = CSR_OP_READ` (0)
  - `data_we_o = 0`, `data_type_o = 2'b00`,
    `data_sign_extension_o = 0`, `data_req_o = 0`
  - internal `illegal_insn = 0`, `ebrk_insn_o = 0`, `mret_insn_o = 0`,
    `dret_insn_o = 0`, `ecall_insn_o = 0`, `wfi_insn_o = 0`

#### Scenario: defaults from ALU-control block (ref: ibex_decoder.sv:674-690)

- GIVEN any `instr_rdata_alu_i`
- WHEN before any opcode-specific override fires
- THEN:
  - `alu_operator_o = ALU_SLTU` (44)
  - `alu_op_a_mux_sel_o = OP_A_IMM` (3)
  - `alu_op_b_mux_sel_o = OP_B_IMM` (1)
  - `imm_a_mux_sel_o = IMM_A_ZERO` (1)
  - `imm_b_mux_sel_o = IMM_B_I` (0)
  - `bt_a_mux_sel_o = OP_A_CURRPC` (2)
  - `bt_b_mux_sel_o = IMM_B_I` (0)
  - `alu_multicycle_o = 0`, `mult_sel_o = 0`, `div_sel_o = 0`

### Requirement: Immediate extraction

The decoder SHALL produce six fully-decoded immediates as fixed
bit-string functions of `instr_rdata_i`, regardless of opcode.

#### Scenario: I-type immediate sign-extends `instr[31:20]`

- GIVEN `instr_rdata_i = 32'hFFF00093` (`ADDI x1, x0, -1`)
- WHEN decoder evaluates
- THEN `imm_i_type_o = 32'hFFFFFFFF`
- (formula: `{ {20{instr[31]}}, instr[31:20] }`, ref: ibex_decoder.sv:136)

#### Scenario: I-type immediate, positive

- GIVEN `instr_rdata_i = 32'h00500113` (`ADDI x2, x0, 5`)
- THEN `imm_i_type_o = 32'h00000005`
- (ref: ibex_decoder.sv:136)

#### Scenario: S-type immediate splits across `instr[31:25]` and `instr[11:7]`

- GIVEN `instr_rdata_i = 32'hFE112E23` (`SW x1, -4(x2)`,
  imm = -4 = `12'hFFC`, hi=`7'b1111111`, lo=`5'b11100`)
- THEN `imm_s_type_o = 32'hFFFFFFFC`
- (formula: `{ {20{instr[31]}}, instr[31:25], instr[11:7] }`,
  ref: ibex_decoder.sv:137)

#### Scenario: B-type immediate has implicit zero LSB

- GIVEN `instr_rdata_i = 32'h00208463` (`BEQ x1, x2, +8`)
  - `instr[31]=0, instr[7]=0, instr[30:25]=000000, instr[11:8]=0100`
- THEN `imm_b_type_o = 32'h00000008`
- (formula: `{ {19{instr[31]}}, instr[31], instr[7], instr[30:25],
  instr[11:8], 1'b0 }`, ref: ibex_decoder.sv:138)

#### Scenario: B-type immediate, negative

- GIVEN `instr_rdata_i = 32'hFE0008E3` (`BEQ x0, x0, -16`)
- THEN `imm_b_type_o = 32'hFFFFFFF0`
- (ref: ibex_decoder.sv:138)

#### Scenario: U-type immediate places `instr[31:12]` in upper 20 bits

- GIVEN `instr_rdata_i = 32'h12345037` (`LUI x0, 0x12345`)
- THEN `imm_u_type_o = 32'h12345000`
- (formula: `{ instr[31:12], 12'b0 }`, ref: ibex_decoder.sv:139)

#### Scenario: J-type immediate has implicit zero LSB

- GIVEN `instr_rdata_i = 32'h008000EF` (`JAL x1, +8`)
- THEN `imm_j_type_o = 32'h00000008`
- (formula: `{ {12{instr[31]}}, instr[19:12], instr[20], instr[30:21],
  1'b0 }`, ref: ibex_decoder.sv:140)

#### Scenario: J-type immediate, large negative

- GIVEN `instr_rdata_i = 32'hFFDFF0EF` (`JAL x1, -4`)
- THEN `imm_j_type_o = 32'hFFFFFFFC`
- (ref: ibex_decoder.sv:140)

#### Scenario: zimm zero-extends `rs1` field

- GIVEN `instr_rdata_i[19:15] = 5'b10101` (rs1 = 21)
- THEN `zimm_rs1_type_o = 32'h00000015`
- (formula: `{ 27'b0, instr[19:15] }`, ref: ibex_decoder.sv:145)

### Requirement: Register addressing

The decoder SHALL produce `rf_raddr_a_o`, `rf_raddr_b_o`, `rf_waddr_o`
as fixed slices of `instr_rdata_i` regardless of opcode. With
`RV32B = RV32BNone` there is no rs3 latch, so `use_rs3_q = 0` always
(ref: ibex_decoder.sv:156-166).

#### Scenario: read addresses are rs1/rs2 fields

- GIVEN `instr_rdata_i = 32'h00C58533` (`ADD x10, x11, x12`)
  - rs1 = `instr[19:15] = 11`, rs2 = `instr[24:20] = 12`
- THEN `rf_raddr_a_o = 5'd11`, `rf_raddr_b_o = 5'd12`
- (ref: ibex_decoder.sv:172-173)

#### Scenario: write address is `rd` field even when `rf_we_o = 0`

- GIVEN `instr_rdata_i = 32'h00050513` (`ADDI x10, x10, 0`)
- THEN `rf_waddr_o = 5'd10` (and `rf_we_o = 1`)
- (ref: ibex_decoder.sv:177)

#### Scenario: rs3 path is inert in scope

- GIVEN any `instr_rdata_i` and any `instr_first_cycle_i`
- WHEN `RV32B = RV32BNone`
- THEN `rf_raddr_a_o = instr[19:15]` (rs1 always wins; the
  `(use_rs3_q & ~instr_first_cycle_i)` mux selector evaluates to 0)
- (ref: ibex_decoder.sv:156-166, 172)

### Requirement: Register-file write enable

The decoder SHALL assert `rf_we_o = 1` only for instructions that
produce an architectural register write **whose data is computed inside
the EX/CSR path** (i.e., ALU result or CSR rdata), and SHALL force
`rf_we_o = 0` when `illegal_insn` is asserted. The output `rf_we_o` is
the internal `rf_we` masked by `~illegal_reg_rv32e`; with `RV32E = 0`,
`illegal_reg_rv32e = 0` so `rf_we_o = rf_we` (ref: ibex_decoder.sv:1200).

**Important — LOAD writeback is NOT through `rf_we_o`.** The LSU drives
a separate `rf_we_lsu` path on its own response cycle. The writeback
stage OR-combines the two write sources
(`rf_wdata_wb_o = ({32{rf_we_id}} & rf_wdata_id) | ({32{rf_we_lsu}} & rf_wdata_lsu)`,
ref: `ibex_wb_stage.sv:245-246`), so asserting `rf_we_o = 1` in the
decoder's LOAD arm would produce GARBAGE on every load (the loaded
data OR-ed with the address-calc ALU result). Upstream's `OPCODE_LOAD`
arm therefore leaves `rf_we = 0` and lets the LSU's separate WE path
drive the writeback. The ARCH decoder MUST replicate this — do NOT
set `rf_we_w = true` in the LOAD arm.

#### Scenario: ADD writes the register file

- GIVEN `instr_rdata_i = 32'h00C58533` (`ADD x10, x11, x12`)
- THEN `rf_we_o = 1`
- (ref: ibex_decoder.sv:454)

#### Scenario: SW does not write the register file

- GIVEN `instr_rdata_i = 32'h00C5A023` (`SW x12, 0(x11)`)
- THEN `rf_we_o = 0`
- (ref: ibex_decoder.sv:298: `rf_we` not asserted in OPCODE_STORE arm)

#### Scenario: LW does NOT set `rf_we_o` (LSU drives the writeback)

- GIVEN `instr_rdata_i = 32'h0002A303` (`LW x6, 0(x5)`)
- THEN `rf_we_o = 0`
- AND `data_req_o = 1`, `rf_ren_a_o = 1`
- NOTE The architectural register write to x6 happens via the LSU's
  separate `rf_we_lsu` writeback path on its response cycle. Setting
  `rf_we_o = 1` here would OR-combine the loaded data with the
  ALU-computed address in `ibex_wb_stage`, producing the load address
  bitwise-OR'd with the loaded value — observable end-to-end as
  silently wrong load data.
- (ref: ibex_decoder.sv:280-302 — OPCODE_LOAD arm leaves `rf_we = 0`)

#### Scenario: BEQ does not write the register file

- GIVEN `instr_rdata_i = 32'h00B58463` (`BEQ x11, x11, +8`)
- THEN `rf_we_o = 0`

#### Scenario: JAL with `BranchTargetALU=0` writes only on second cycle

- GIVEN `instr_rdata_i = 32'h008000EF` (`JAL x1, +8`),
  `instr_first_cycle_i = 1`
- WHEN `BranchTargetALU = 0`
- THEN `rf_we_o = 0` (first cycle: `rf_we = BranchTargetALU = 0`)
- (ref: ibex_decoder.sv:251)

#### Scenario: JAL second cycle writes PC+4

- GIVEN `instr_rdata_i = 32'h008000EF`, `instr_first_cycle_i = 0`
- THEN `rf_we_o = 1`
- (ref: ibex_decoder.sv:255)

#### Scenario: CSRRW writes the destination register

- GIVEN `instr_rdata_i = 32'h30559573` (`CSRRW x10, mtvec, x11`,
  funct3=001)
- THEN `rf_we_o = 1`, `rf_wdata_sel_o = RF_WD_CSR`
- (ref: ibex_decoder.sv:625-626)

#### Scenario: illegal opcode forces `rf_we_o = 0`

- GIVEN `instr_rdata_i = 32'h00000000` (opcode = 0x00, default arm)
- THEN `rf_we_o = 0`, `illegal_insn_o = 1`
- (ref: ibex_decoder.sv:643-666)

### Requirement: Register read enables (`rf_ren_a_o`, `rf_ren_b_o`)

The decoder SHALL assert each read-enable signal exactly when the
opcode arm explicitly enables it. Both default to `0`; an opcode arm
that does not touch them leaves them low.

#### Scenario: OP-IMM reads rs1 only

- GIVEN `instr_rdata_i = 32'h00500113` (`ADDI x2, x0, 5`)
- THEN `rf_ren_a_o = 1`, `rf_ren_b_o = 0`
- (ref: ibex_decoder.sv:354)

#### Scenario: OP reads both rs1 and rs2

- GIVEN `instr_rdata_i = 32'h00C58533` (`ADD x10, x11, x12`)
- THEN `rf_ren_a_o = 1`, `rf_ren_b_o = 1`
- (ref: ibex_decoder.sv:452-453)

#### Scenario: BRANCH reads both

- GIVEN `instr_rdata_i = 32'h00B58463` (`BEQ x11, x11, +8`)
- THEN `rf_ren_a_o = 1`, `rf_ren_b_o = 1`
- (ref: ibex_decoder.sv:290-291)

#### Scenario: STORE reads both

- GIVEN `instr_rdata_i = 32'h00C5A023` (`SW x12, 0(x11)`)
- THEN `rf_ren_a_o = 1`, `rf_ren_b_o = 1`
- (ref: ibex_decoder.sv:299-300)

#### Scenario: LOAD reads only rs1

- GIVEN `instr_rdata_i = 32'h0005A503` (`LW x10, 0(x11)`)
- THEN `rf_ren_a_o = 1`, `rf_ren_b_o = 0`
- (ref: ibex_decoder.sv:318)

#### Scenario: JALR reads rs1

- GIVEN `instr_rdata_i = 32'h000080E7` (`JALR x1, x1, 0`)
- THEN `rf_ren_a_o = 1`, `rf_ren_b_o = 0`
- (ref: ibex_decoder.sv:274)

#### Scenario: JAL reads neither register

- GIVEN `instr_rdata_i = 32'h008000EF` (`JAL x1, +8`)
- THEN `rf_ren_a_o = 0`, `rf_ren_b_o = 0`

#### Scenario: LUI reads neither

- GIVEN `instr_rdata_i = 32'h12345037` (`LUI x0, 0x12345`)
- THEN `rf_ren_a_o = 0`, `rf_ren_b_o = 0`
- (ref: ibex_decoder.sv:345-347)

#### Scenario: AUIPC reads neither

- GIVEN `instr_rdata_i = 32'h00001097` (`AUIPC x1, 1`)
- THEN `rf_ren_a_o = 0`, `rf_ren_b_o = 0`
- (ref: ibex_decoder.sv:349-351)

#### Scenario: CSRRW (read-modify-write) reads rs1

- GIVEN `instr_rdata_i = 32'h30559573` (CSRRW, funct3=001, instr[14]=0)
- THEN `rf_ren_a_o = 1`
- (ref: ibex_decoder.sv:628-630)

#### Scenario: CSRRWI (immediate form) does not read rs1

- GIVEN `instr_rdata_i = 32'h3055D573` (CSRRWI, funct3=101, instr[14]=1)
- THEN `rf_ren_a_o = 0`
- (ref: ibex_decoder.sv:628-630)

### Requirement: ALU operator selection (per-opcode)

The decoder SHALL set `alu_operator_o` based on `instr_rdata_alu_i`'s
opcode, funct3, and funct7 fields. Default `ALU_SLTU` (44).

#### Scenario: ADD selects `ALU_ADD`

- GIVEN `instr_rdata_alu_i = 32'h00C58533` (`ADD x10, x11, x12`,
  funct7=0x00, funct3=000)
- THEN `alu_operator_o = ALU_ADD` (0)
- (ref: ibex_decoder.sv:997)

#### Scenario: SUB selects `ALU_SUB`

- GIVEN `instr_rdata_alu_i = 32'h40C58533` (`SUB x10, x11, x12`,
  funct7=0x20)
- THEN `alu_operator_o = ALU_SUB` (1)
- (ref: ibex_decoder.sv:998)

#### Scenario: SLT/SLTU/XOR/OR/AND/SLL/SRL/SRA selectors

- GIVEN `instr_rdata_alu_i` is the canonical R-type with the listed
  funct7/funct3
- THEN `alu_operator_o` matches the table:
  - SLT (000_0000, 010) → ALU_SLT (43)
  - SLTU (000_0000, 011) → ALU_SLTU (44)
  - XOR (000_0000, 100) → ALU_XOR (2)
  - OR  (000_0000, 110) → ALU_OR (3)
  - AND (000_0000, 111) → ALU_AND (4)
  - SLL (000_0000, 001) → ALU_SLL (10)
  - SRL (000_0000, 101) → ALU_SRL (9)
  - SRA (010_0000, 101) → ALU_SRA (8)
- (ref: ibex_decoder.sv:999-1006)

#### Scenario: ADDI selects `ALU_ADD`

- GIVEN `instr_rdata_alu_i = 32'h00500113` (`ADDI x2, x0, 5`,
  funct3=000)
- THEN `alu_operator_o = ALU_ADD` (0)
- (ref: ibex_decoder.sv:826)

#### Scenario: SLTI/SLTIU/XORI/ORI/ANDI selectors

- funct3=010 → ALU_SLT (43); funct3=011 → ALU_SLTU (44);
  funct3=100 → ALU_XOR (2); funct3=110 → ALU_OR (3);
  funct3=111 → ALU_AND (4)
- (ref: ibex_decoder.sv:827-831)

#### Scenario: SLLI selects `ALU_SLL` when funct7=0x00

- GIVEN `instr_rdata_alu_i = 32'h00509093` (`SLLI x1, x1, 5`,
  funct3=001, instr[31:25]=0)
- THEN `alu_operator_o = ALU_SLL` (10)
- (ref: ibex_decoder.sv:896)

#### Scenario: SRLI selects `ALU_SRL`

- GIVEN `instr_rdata_alu_i = 32'h0050D093` (funct3=101, instr[31:27]=0)
- THEN `alu_operator_o = ALU_SRL` (9)
- (ref: ibex_decoder.sv:937)

#### Scenario: SRAI selects `ALU_SRA`

- GIVEN `instr_rdata_alu_i = 32'h4050D093` (funct3=101, instr[31:27]=0_1000)
- THEN `alu_operator_o = ALU_SRA` (8)
- (ref: ibex_decoder.sv:938-939)

#### Scenario: BRANCH funct3 picks the comparator

- BEQ (000) → ALU_EQ (29)
- BNE (001) → ALU_NE (30)
- BLT (100) → ALU_LT (25)
- BGE (101) → ALU_GE (27)
- BLTU (110) → ALU_LTU (26)
- BGEU (111) → ALU_GEU (28)
- (ref: ibex_decoder.sv:744-751)

#### Scenario: JAL operator is ADD (compute target or PC+4)

- GIVEN `instr_rdata_alu_i = 32'h008000EF` (JAL)
- THEN `alu_operator_o = ALU_ADD` (0) for either cycle
- (ref: ibex_decoder.sv:710, 716)

#### Scenario: JALR operator is ADD

- GIVEN `instr_rdata_alu_i = 32'h000080E7` (JALR)
- THEN `alu_operator_o = ALU_ADD` (0)
- (ref: ibex_decoder.sv:732, 738)

#### Scenario: LOAD/STORE address gen is ADD

- GIVEN `instr_rdata_alu_i = 32'h0005A503` (LW)
- THEN `alu_operator_o = ALU_ADD` (0)
- (ref: ibex_decoder.sv:783, 796)

#### Scenario: AUIPC operator is ADD

- THEN `alu_operator_o = ALU_ADD` (0) (ref: ibex_decoder.sv:817)

#### Scenario: LUI operator is ADD (adds zero-immediate-A to U-immediate-B)

- THEN `alu_operator_o = ALU_ADD` (0) (ref: ibex_decoder.sv:810)

#### Scenario: FENCE operator is ADD (NOP), FENCE.I operator is ADD (PC+4)

- ref: ibex_decoder.sv:1146, 1159

#### Scenario: SYSTEM/CSR keep ALU defaults except for operand-A mux

- The CSR sub-arms do not touch `alu_operator_o`, so it remains
  `ALU_SLTU` (44) — but that value is functionally unobserved because
  the result is replaced by `RF_WD_CSR` data.

### Requirement: ALU operand-A and operand-B mux selection

Per the ALU-control block (ref: ibex_decoder.sv:673-1189), the decoder
SHALL select operand-A and operand-B mux sources per opcode. Both
default to `OP_A_IMM` and `OP_B_IMM` respectively.

#### Scenario: OP/OP-IMM operand-A is REG_A; operand-B is REG_B (OP) or IMM (OP-IMM)

- GIVEN OP (`instr_rdata_alu_i[6:0] = 0x33`):
  `alu_op_a_mux_sel_o = OP_A_REG_A` (0),
  `alu_op_b_mux_sel_o = OP_B_REG_B` (0)
- (ref: ibex_decoder.sv:949-950)
- GIVEN OP-IMM (`= 0x13`):
  `alu_op_a_mux_sel_o = OP_A_REG_A` (0),
  `alu_op_b_mux_sel_o = OP_B_IMM` (1),
  `imm_b_mux_sel_o = IMM_B_I` (0)
- (ref: ibex_decoder.sv:821-823)

#### Scenario: LUI uses immediate operand-A (zero) and U-immediate operand-B

- THEN `alu_op_a_mux_sel_o = OP_A_IMM` (3),
  `alu_op_b_mux_sel_o = OP_B_IMM` (1),
  `imm_a_mux_sel_o = IMM_A_ZERO` (1),
  `imm_b_mux_sel_o = IMM_B_U` (3)
- (ref: ibex_decoder.sv:806-810)

#### Scenario: AUIPC uses CURRPC and U-immediate

- THEN `alu_op_a_mux_sel_o = OP_A_CURRPC` (2),
  `alu_op_b_mux_sel_o = OP_B_IMM` (1),
  `imm_b_mux_sel_o = IMM_B_U` (3)
- (ref: ibex_decoder.sv:814-816)

#### Scenario: JAL first cycle (BranchTargetALU=0) — CURRPC + IMM_B_J

- GIVEN `instr_first_cycle_i = 1`
- THEN `alu_op_a_mux_sel_o = OP_A_CURRPC` (2),
  `alu_op_b_mux_sel_o = OP_B_IMM` (1),
  `imm_b_mux_sel_o = IMM_B_J` (4)
- (ref: ibex_decoder.sv:707-710)

#### Scenario: JAL second cycle — CURRPC + IMM_B_INCR_PC

- GIVEN `instr_first_cycle_i = 0`
- THEN `alu_op_a_mux_sel_o = OP_A_CURRPC`,
  `alu_op_b_mux_sel_o = OP_B_IMM`,
  `imm_b_mux_sel_o = IMM_B_INCR_PC` (5)
- (ref: ibex_decoder.sv:713-716)

#### Scenario: JALR first cycle — REG_A + IMM_B_I

- GIVEN `instr_first_cycle_i = 1`
- THEN `alu_op_a_mux_sel_o = OP_A_REG_A`,
  `imm_b_mux_sel_o = IMM_B_I`
- (ref: ibex_decoder.sv:729-732)

#### Scenario: JALR second cycle — CURRPC + IMM_B_INCR_PC

- (ref: ibex_decoder.sv:735-738)

#### Scenario: BRANCH first cycle — REG_A + REG_B (compare)

- GIVEN `instr_first_cycle_i = 1`
- THEN `alu_op_a_mux_sel_o = OP_A_REG_A`,
  `alu_op_b_mux_sel_o = OP_B_REG_B`
- (ref: ibex_decoder.sv:763-765)

#### Scenario: BRANCH second cycle (BranchTargetALU=0) — CURRPC + IMM

- GIVEN `instr_first_cycle_i = 0`
- THEN `alu_op_a_mux_sel_o = OP_A_CURRPC`,
  `alu_op_b_mux_sel_o = OP_B_IMM`,
  `alu_operator_o = ALU_ADD`,
  `imm_b_mux_sel_o = branch_taken_i ? IMM_B_B (2) : IMM_B_INCR_PC (5)`
- (ref: ibex_decoder.sv:767-772)

#### Scenario: STORE — REG_A + S-immediate (or REG_B if instr_alu[14]=1, illegal)

- GIVEN `instr_rdata_alu_i = 32'h00C5A023` (`SW`, instr[14]=0)
- THEN `alu_op_a_mux_sel_o = OP_A_REG_A`,
  `alu_op_b_mux_sel_o = OP_B_IMM`,
  `imm_b_mux_sel_o = IMM_B_S` (1),
  `alu_operator_o = ALU_ADD`
- (ref: ibex_decoder.sv:781-789)

Note: when `instr_alu[14] = 1` (e.g. `instr[13:12]=11` or any illegal
store funct3) the decoder retains `alu_op_b_mux_sel_o = OP_B_REG_B`
(line 782); the instruction is also flagged illegal in the main block.
The ALU output is observable but not consumed when illegal forces
`data_req_o = 0`.

#### Scenario: LOAD — REG_A + I-immediate

- GIVEN `instr_rdata_alu_i = 32'h0005A503` (`LW`)
- THEN `alu_op_a_mux_sel_o = OP_A_REG_A`,
  `alu_op_b_mux_sel_o = OP_B_IMM`,
  `imm_b_mux_sel_o = IMM_B_I`,
  `alu_operator_o = ALU_ADD`
- (ref: ibex_decoder.sv:792-798)

#### Scenario: MISC-MEM/FENCE — REG_A + IMM (NOP)

- GIVEN `instr_rdata_alu_i[14:12] = 3'b000` (FENCE)
- THEN `alu_op_a_mux_sel_o = OP_A_REG_A`,
  `alu_op_b_mux_sel_o = OP_B_IMM`,
  `alu_operator_o = ALU_ADD`
- (ref: ibex_decoder.sv:1144-1148)

#### Scenario: MISC-MEM/FENCE.I — CURRPC + IMM_B_INCR_PC

- GIVEN `instr_rdata_alu_i[14:12] = 3'b001` (FENCE.I)
- WHEN `BranchTargetALU = 0`
- THEN `alu_op_a_mux_sel_o = OP_A_CURRPC`,
  `alu_op_b_mux_sel_o = OP_B_IMM`,
  `imm_b_mux_sel_o = IMM_B_INCR_PC`,
  `alu_operator_o = ALU_ADD`
- (ref: ibex_decoder.sv:1156-1159)

#### Scenario: SYSTEM (non-CSR, instr_alu[14:12]=000) — REG_A + IMM

- THEN `alu_op_a_mux_sel_o = OP_A_REG_A`,
  `alu_op_b_mux_sel_o = OP_B_IMM`
- (ref: ibex_decoder.sv:1167-1170)

#### Scenario: CSRRW/CSRRS/CSRRC — REG_A + IMM, with `imm_a_mux_sel_o = IMM_A_Z`

- GIVEN `instr_rdata_alu_i[14] = 0` (register-form CSR)
- THEN `alu_op_a_mux_sel_o = OP_A_REG_A`,
  `imm_a_mux_sel_o = IMM_A_Z` (0)
- (ref: ibex_decoder.sv:1173, 1180-1182)

#### Scenario: CSRRWI/CSRRSI/CSRRCI — IMM + IMM, with `imm_a_mux_sel_o = IMM_A_Z`

- GIVEN `instr_rdata_alu_i[14] = 1` (immediate-form CSR)
- THEN `alu_op_a_mux_sel_o = OP_A_IMM`,
  `imm_a_mux_sel_o = IMM_A_Z`
- (ref: ibex_decoder.sv:1173, 1178-1180)

### Requirement: Branch-target mux selection (`bt_a_mux_sel_o`, `bt_b_mux_sel_o`)

When `BranchTargetALU = 0` the BT mux selectors keep their defaults
(`OP_A_CURRPC`, `IMM_B_I`) for every opcode — the SV bodies that set
them are gated by `if (BranchTargetALU)` (ref: ibex_decoder.sv:699,
721, 754, 1152). The ARCH module SHALL replicate this: in scope,
`bt_a_mux_sel_o = OP_A_CURRPC` (2) and `bt_b_mux_sel_o = IMM_B_I` (0)
unconditionally for all opcodes.

#### Scenario: BT selectors are constants in scope

- GIVEN any `instr_rdata_alu_i`
- WHEN `BranchTargetALU = 0`
- THEN `bt_a_mux_sel_o = 2'd2`, `bt_b_mux_sel_o = 3'd0`
- (ref: ibex_decoder.sv:681-682, 699, 721, 754, 1152)

### Requirement: Mult/Div control

For `RV32M = RV32MFast` and an `OPCODE_OP` instruction with funct7
== `7'b0000001`, the decoder SHALL emit the per-instruction
`multdiv_operator_o`, `multdiv_signed_mode_o`, `mult_sel_o`,
`div_sel_o`, and (after illegal masking) `mult_en_o` / `div_en_o`. The
ALU operator for these eight RV32M ops is forced to `ALU_ADD` so the
ALU adder can pass through partial products.

The illegal-masking is global (ref: ibex_decoder.sv:1192-1193):
`mult_en_o = illegal_insn ? 0 : mult_sel_o`,
`div_en_o = illegal_insn ? 0 : div_sel_o`.

Default `multdiv_operator_o = MD_OP_MULL`,
`multdiv_signed_mode_o = 2'b00`, `mult_sel_o = 0`, `div_sel_o = 0`.

#### Scenario: MUL — funct7=0x01, funct3=000

- GIVEN `instr_rdata_i = instr_rdata_alu_i = 32'h02C58533`
  (`MUL x10, x11, x12`)
- THEN `multdiv_operator_o = MD_OP_MULL` (0),
  `multdiv_signed_mode_o = 2'b00`, `mult_sel_o = 1`, `div_sel_o = 0`,
  `mult_en_o = 1`, `div_en_o = 0`,
  `alu_operator_o = ALU_ADD`,
  `rf_we_o = 1`, `rf_ren_a_o = 1`, `rf_ren_b_o = 1`,
  `illegal_insn_o = 0`
- (ref: ibex_decoder.sv:516-520, 1100-1103)

#### Scenario: MULH — funct3=001

- GIVEN `instr_rdata_i = 32'h02C59533` (`MULH`)
- THEN `multdiv_operator_o = MD_OP_MULH` (1),
  `multdiv_signed_mode_o = 2'b11`, `mult_sel_o = 1`,
  `alu_operator_o = ALU_ADD`
- (ref: ibex_decoder.sv:521-525, 1104-1107)

#### Scenario: MULHSU — funct3=010

- GIVEN `instr_rdata_i = 32'h02C5A533` (`MULHSU`)
- THEN `multdiv_operator_o = MD_OP_MULH` (1),
  `multdiv_signed_mode_o = 2'b01`, `mult_sel_o = 1`
- (ref: ibex_decoder.sv:526-530, 1108-1111)

#### Scenario: MULHU — funct3=011

- GIVEN `instr_rdata_i = 32'h02C5B533` (`MULHU`)
- THEN `multdiv_operator_o = MD_OP_MULH` (1),
  `multdiv_signed_mode_o = 2'b00`, `mult_sel_o = 1`
- (ref: ibex_decoder.sv:531-535, 1112-1115)

#### Scenario: DIV — funct3=100

- GIVEN `instr_rdata_i = 32'h02C5C533` (`DIV`)
- THEN `multdiv_operator_o = MD_OP_DIV` (2),
  `multdiv_signed_mode_o = 2'b11`, `mult_sel_o = 0`, `div_sel_o = 1`,
  `mult_en_o = 0`, `div_en_o = 1`
- (ref: ibex_decoder.sv:536-540, 1116-1119)

#### Scenario: DIVU — funct3=101

- GIVEN `instr_rdata_i = 32'h02C5D533` (`DIVU`)
- THEN `multdiv_operator_o = MD_OP_DIV` (2),
  `multdiv_signed_mode_o = 2'b00`, `div_sel_o = 1`, `div_en_o = 1`
- (ref: ibex_decoder.sv:541-545, 1120-1123)

#### Scenario: REM — funct3=110

- GIVEN `instr_rdata_i = 32'h02C5E533` (`REM`)
- THEN `multdiv_operator_o = MD_OP_REM` (3),
  `multdiv_signed_mode_o = 2'b11`, `div_sel_o = 1`
- (ref: ibex_decoder.sv:546-550, 1124-1127)

#### Scenario: REMU — funct3=111

- GIVEN `instr_rdata_i = 32'h02C5F533` (`REMU`)
- THEN `multdiv_operator_o = MD_OP_REM` (3),
  `multdiv_signed_mode_o = 2'b00`, `div_sel_o = 1`
- (ref: ibex_decoder.sv:551-555, 1128-1131)

#### Scenario: Mult/div masked when illegal_insn rises elsewhere

- GIVEN any RV32M encoding paired with `illegal_c_insn_i = 1`
- THEN `mult_en_o = 0`, `div_en_o = 0`
- (ref: ibex_decoder.sv:1192-1193)

### Requirement: CSR control

CSR access is signalled when `instr_rdata_i[6:0] = OPCODE_SYSTEM` and
`instr_rdata_i[14:12] != 3'b000`. The decoder SHALL drive
`csr_access_o`, `csr_op_o`, `csr_addr_o`, `rf_wdata_sel_o`, and the
internal `csr_illegal` flag.

#### Scenario: CSR address is `instr[31:20]` always (even for non-CSR insns)

- GIVEN `instr_rdata_i = 32'h30559573` (`CSRRW x10, mtvec(0x305), x11`)
- THEN `csr_addr_o = 12'h305`
- (ref: ibex_decoder.sv:142)

#### Scenario: CSRRW (funct3=001) — `csr_op = CSR_OP_WRITE`

- GIVEN `instr_rdata_i = 32'h30559573` (funct3=001)
- THEN `csr_access_o = 1`, internal `csr_op = CSR_OP_WRITE` (1),
  `csr_op_o = CSR_OP_WRITE` (because rs1=11 ≠ 0; see operand-zero rule)
- (ref: ibex_decoder.sv:633)

#### Scenario: CSRRS (funct3=010) — `csr_op = CSR_OP_SET`

- GIVEN `instr_rdata_i = 32'h3055A573` (CSRRS, funct3=010, rs1=11)
- THEN internal `csr_op = CSR_OP_SET` (2), `csr_op_o = CSR_OP_SET`
- (ref: ibex_decoder.sv:634)

#### Scenario: CSRRC (funct3=011) — `csr_op = CSR_OP_CLEAR`

- GIVEN `instr_rdata_i = 32'h3055B573` (CSRRC, funct3=011, rs1=11)
- THEN internal `csr_op = CSR_OP_CLEAR` (3), `csr_op_o = CSR_OP_CLEAR`
- (ref: ibex_decoder.sv:635)

#### Scenario: CSRRWI/CSRRSI/CSRRCI — funct3 ∈ {101,110,111} maps the same as 001/010/011

- GIVEN `instr_rdata_i = 32'h3055D573` (CSRRWI, funct3=101)
- THEN internal `csr_op = CSR_OP_WRITE`, since the case is on
  `instr[13:12]` (the funct3 low bits) and ignores `instr[14]`
- (ref: ibex_decoder.sv:632)

#### Scenario: CSRRS/CSRRC with rs1=0 demote to read-only

- GIVEN `instr_rdata_i = 32'h30502573` (`CSRR x10, mtvec` =
  `CSRRS x10, mtvec, x0`, funct3=010, rs1=0)
- THEN internal `csr_op = CSR_OP_SET` but `csr_op_o = CSR_OP_READ` (0)
  (no CSR write-side-effect)
- (ref: ibex_decoder.sv:198-201)

#### Scenario: CSRRSI/CSRRCI with zimm=0 demote to read-only

- GIVEN `instr_rdata_i = 32'h30506573` (`CSRRSI x10, mtvec, 0`,
  funct3=110, rs1 field = 0 = zimm)
- THEN `csr_op_o = CSR_OP_READ` (the rs1=0 check uses the same rs1
  field bits for both rs1 and zimm)
- (ref: ibex_decoder.sv:198-201)

#### Scenario: CSRRW with rd=0 keeps `CSR_OP_WRITE` (no demote for write/clear-on-zero rule)

- GIVEN `instr_rdata_i = 32'h30559073` (`CSRW mtvec, x11` =
  `CSRRW x0, mtvec, x11`, funct3=001, rs1=11, rd=0)
- THEN `csr_op_o = CSR_OP_WRITE`, `csr_access_o = 1`, `rf_we_o = 1`
  (write to x0 is a no-op downstream but the decoder still asserts WE)
- (ref: ibex_decoder.sv:198-201; the zero-check is only for SET/CLEAR)

#### Scenario: Illegal CSR funct3=100

- GIVEN `instr_rdata_i = 32'h30504573` (funct3=100, an illegal CSR
  funct3)
- THEN internal `csr_illegal = 1`, `illegal_insn_o = 1`
- (ref: ibex_decoder.sv:636-639)

#### Scenario: rf_wdata_sel_o = RF_WD_CSR for CSR access

- GIVEN any non-illegal CSR instruction
- THEN `rf_wdata_sel_o = RF_WD_CSR` (1), `rf_we_o = 1`
- (ref: ibex_decoder.sv:625-626)

### Requirement: LSU control

The decoder SHALL drive `data_req_o`, `data_we_o`, `data_type_o`,
`data_sign_extension_o` for `OPCODE_LOAD` (0x03) and `OPCODE_STORE`
(0x23). For all other opcodes these signals stay at their defaults
(`data_req_o=0`, `data_we_o=0`, `data_type_o=2'b00`,
`data_sign_extension_o=0`). When `illegal_insn` rises, `data_req_o`
and `data_we_o` are forced to `0` (ref: ibex_decoder.sv:660-661).

`data_type_o` encoding: `2'b00 = word`, `2'b01 = halfword`,
`2'b10 = byte`, `2'b11 = reserved/illegal` (ref: ibex_decoder.sv:309-314,
326-338).

#### Scenario: SW — funct3=010, type=word

- GIVEN `instr_rdata_i = 32'h00C5A023` (`SW x12, 0(x11)`, funct3=010)
- THEN `data_req_o = 1`, `data_we_o = 1`, `data_type_o = 2'b00`,
  `data_sign_extension_o = 0`
- (ref: ibex_decoder.sv:301-312)

#### Scenario: SH — funct3=001, type=halfword

- GIVEN `instr_rdata_i = 32'h00C59023` (`SH x12, 0(x11)`)
- THEN `data_type_o = 2'b01`, `data_we_o = 1`, `data_req_o = 1`
- (ref: ibex_decoder.sv:311)

#### Scenario: SB — funct3=000, type=byte

- GIVEN `instr_rdata_i = 32'h00C58023` (`SB x12, 0(x11)`)
- THEN `data_type_o = 2'b10`, `data_we_o = 1`, `data_req_o = 1`
- (ref: ibex_decoder.sv:310)

#### Scenario: STORE with funct3 having instr[14]=1 is illegal

- GIVEN `instr_rdata_i = 32'h00C5C023` (funct3=100, illegal store)
- THEN `illegal_insn_o = 1`, `data_req_o = 0`, `data_we_o = 0`
- (ref: ibex_decoder.sv:304-306, 660-661)

#### Scenario: STORE with funct3=011 reserved → illegal

- GIVEN `instr_rdata_i = 32'h00C5B023` (funct3=011)
- THEN `illegal_insn_o = 1`
- (ref: ibex_decoder.sv:309-314 default)

#### Scenario: LW — funct3=010, type=word, sign_ext=0 (instr[14]=0)

- GIVEN `instr_rdata_i = 32'h0005A503` (`LW x10, 0(x11)`)
- THEN `data_req_o = 1`, `data_we_o = 0`, `data_type_o = 2'b00`,
  `data_sign_extension_o = 1` (since `instr[14] = 0`)

Note: `data_sign_extension_o = ~instr[14]` (ref: ibex_decoder.sv:323).
For LW, `instr[14] = 0` so `data_sign_extension_o = 1`. The LSU
ignores sign-extension on word loads, so this 1 is functionally a
don't-care but the decoder still drives it.

#### Scenario: LH — funct3=001, sign_ext=1

- GIVEN `instr_rdata_i = 32'h00059503` (`LH x10, 0(x11)`)
- THEN `data_type_o = 2'b01`, `data_sign_extension_o = 1`
- (ref: ibex_decoder.sv:323, 328)

#### Scenario: LHU — funct3=101, sign_ext=0

- GIVEN `instr_rdata_i = 32'h0005D503` (`LHU x10, 0(x11)`)
- THEN `data_type_o = 2'b01`, `data_sign_extension_o = 0`
- (ref: ibex_decoder.sv:323, 328)

#### Scenario: LB — funct3=000, sign_ext=1

- GIVEN `instr_rdata_i = 32'h00058503` (`LB x10, 0(x11)`)
- THEN `data_type_o = 2'b10`, `data_sign_extension_o = 1`
- (ref: ibex_decoder.sv:323, 327)

#### Scenario: LBU — funct3=100, sign_ext=0

- GIVEN `instr_rdata_i = 32'h0005C503` (`LBU x10, 0(x11)`)
- THEN `data_type_o = 2'b10`, `data_sign_extension_o = 0`
- (ref: ibex_decoder.sv:323, 327)

#### Scenario: LWU is illegal in RV32

- GIVEN `instr_rdata_i = 32'h0005E503` (`LWU`, funct3=110, instr[14]=1
  combined with instr[13:12]=10)
- THEN `illegal_insn_o = 1`
- (ref: ibex_decoder.sv:329-334)

#### Scenario: LOAD with funct3=011 or 111 reserved → illegal

- GIVEN `instr_rdata_i` with funct3=011 or funct3=111 in OPCODE_LOAD
- THEN `illegal_insn_o = 1`, `data_req_o = 0`
- (ref: ibex_decoder.sv:335-337)

### Requirement: Control flag outputs

The decoder SHALL emit single-bit flags driven directly off the
opcode/funct3/funct12 fields:

- `ebrk_insn_o` — opcode SYSTEM, funct3=000, instr[31:20]=0x001
- `ecall_insn_o` — opcode SYSTEM, funct3=000, instr[31:20]=0x000
- `mret_insn_o` — opcode SYSTEM, funct3=000, instr[31:20]=0x302
- `dret_insn_o` — opcode SYSTEM, funct3=000, instr[31:20]=0x7B2
- `wfi_insn_o` — opcode SYSTEM, funct3=000, instr[31:20]=0x105
- `jump_in_dec_o` — JAL or JALR or FENCE.I (`OPCODE_MISC_MEM` funct3=001)
- `jump_set_o` — JAL or JALR or FENCE.I in their first cycle
- `branch_in_dec_o` — opcode BRANCH (forced to 0 if illegal)
- `icache_inval_o` — FENCE.I in its first cycle

These flags are computed on the `instr_rdata_i` side (ref:
ibex_decoder.sv:209-212, 232-236, 246-251, 259-265, 277-278, 277,
582-585, 599-612).

When `illegal_insn = 1`, the decoder forces
`jump_in_dec_o = 0`, `jump_set_o = 0`, `branch_in_dec_o = 0`
(ref: ibex_decoder.sv:662-664). The trap flags
(`ebrk/mret/dret/ecall/wfi`) are NOT masked by `illegal_insn` — the
SYSTEM arm only sets one of them when the funct12 matches a legal
encoding, so they are inherently mutually exclusive with
`illegal_insn` from the SYSTEM arm. (Compressed-illegal pass-through
via `illegal_c_insn_i` does NOT clear the trap flags either, but in
practice an illegal compressed insn never decodes to a SYSTEM
funct12.)

#### Scenario: ECALL

- GIVEN `instr_rdata_i = 32'h00000073` (funct3=000, instr[31:20]=0x000,
  rs1=0, rd=0)
- THEN `ecall_insn_o = 1`, `illegal_insn_o = 0`,
  `ebrk/mret/dret/wfi = 0`
- (ref: ibex_decoder.sv:597-599)

#### Scenario: EBREAK

- GIVEN `instr_rdata_i = 32'h00100073` (instr[31:20]=0x001)
- THEN `ebrk_insn_o = 1`
- (ref: ibex_decoder.sv:601-603)

#### Scenario: MRET

- GIVEN `instr_rdata_i = 32'h30200073` (instr[31:20]=0x302)
- THEN `mret_insn_o = 1`
- (ref: ibex_decoder.sv:605-606)

#### Scenario: DRET

- GIVEN `instr_rdata_i = 32'h7B200073` (instr[31:20]=0x7B2)
- THEN `dret_insn_o = 1`
- (ref: ibex_decoder.sv:608-609)

#### Scenario: WFI

- GIVEN `instr_rdata_i = 32'h10500073` (instr[31:20]=0x105)
- THEN `wfi_insn_o = 1`
- (ref: ibex_decoder.sv:611-612)

#### Scenario: SYSTEM funct3=000 with rs1≠0 or rd≠0 is illegal

- GIVEN `instr_rdata_i = 32'h00100093` is OPCODE_OP_IMM (not SYSTEM);
  use instead `instr_rdata_i = 32'h00008073` (funct12=0, rs1=1, rd=0)
- THEN `illegal_insn_o = 1` even though funct12=0x000 normally signals
  ECALL — the rs1/rd zero-check fails
- (ref: ibex_decoder.sv:619-621)

#### Scenario: jump_in_dec_o for JAL

- GIVEN `instr_rdata_i = 32'h008000EF` (JAL)
- THEN `jump_in_dec_o = 1`, `jump_set_o = instr_first_cycle_i`
- (ref: ibex_decoder.sv:247, 252)

#### Scenario: jump_in_dec_o for JALR

- GIVEN `instr_rdata_i = 32'h000080E7` (JALR, funct3=000)
- THEN `jump_in_dec_o = 1`, `jump_set_o = instr_first_cycle_i`
- (ref: ibex_decoder.sv:260, 265)

#### Scenario: JALR with funct3 ≠ 000 is illegal

- GIVEN `instr_rdata_i = 32'h000090E7` (JALR funct3=001)
- THEN `illegal_insn_o = 1`, `jump_in_dec_o = 0`, `jump_set_o = 0`
- (ref: ibex_decoder.sv:270-272, 662-663)

#### Scenario: branch_in_dec_o for BEQ

- GIVEN `instr_rdata_i = 32'h00B58463` (BEQ)
- THEN `branch_in_dec_o = 1`
- (ref: ibex_decoder.sv:278)

#### Scenario: BRANCH with funct3 ∈ {010, 011} is illegal

- GIVEN `instr_rdata_i` with opcode BRANCH and funct3=010
- THEN `illegal_insn_o = 1`, `branch_in_dec_o = 0`
- (ref: ibex_decoder.sv:280-288, 664)

#### Scenario: FENCE.I sets icache_inval_o on first cycle

- GIVEN `instr_rdata_i = 32'h0000100F` (FENCE.I), `instr_first_cycle_i = 1`
- THEN `jump_in_dec_o = 1`, `jump_set_o = 1`, `icache_inval_o = 1`
- (ref: ibex_decoder.sv:578-585)

#### Scenario: FENCE.I second cycle does not set icache_inval_o

- GIVEN `instr_rdata_i = 32'h0000100F`, `instr_first_cycle_i = 0`
- THEN `jump_in_dec_o = 1`, `jump_set_o = 0`, `icache_inval_o = 0`
- (ref: ibex_decoder.sv:582-585)

#### Scenario: FENCE plain is a NOP

- GIVEN `instr_rdata_i = 32'h0000000F` (FENCE, funct3=000)
- THEN no flags set, `rf_we_o = 0`, `illegal_insn_o = 0`
- (ref: ibex_decoder.sv:569-572)

#### Scenario: MISC-MEM with funct3 ∉ {000, 001} is illegal

- GIVEN `instr_rdata_i = 32'h0000200F` (funct3=010)
- THEN `illegal_insn_o = 1`
- (ref: ibex_decoder.sv:587-589)

### Requirement: Illegal-instruction aggregation

The decoder SHALL set `illegal_insn_o = 1` if and only if at least
one of the following conditions holds:

1. The 7-bit opcode `instr_rdata_i[6:0]` does not match any
   `opcode_e` variant — the `case (opcode)` default arm fires
   (ref: ibex_decoder.sv:643-644).
2. A nested sub-decode within an opcode arm finds an unsupported
   funct3/funct7/funct12 combination:
   - `OPCODE_JALR` with funct3 ≠ 000 (ref: ibex_decoder.sv:270-272).
   - `OPCODE_BRANCH` with funct3 ∈ {010, 011} (ref: ibex_decoder.sv:280-288).
   - `OPCODE_STORE` with `instr[14] = 1` or funct3 ∉ {000, 001, 010}
     (ref: ibex_decoder.sv:304-314).
   - `OPCODE_LOAD` with funct3 ∈ {011, 110, 111} or `LWU`
     (funct3=110) (ref: ibex_decoder.sv:331-337).
   - `OPCODE_OP_IMM` with funct3=001 funct7≠0x00 except permitted
     RV32B variants (out of scope), or funct3=101 with bits not
     matching SRLI/SRAI (ref: ibex_decoder.sv:357-448). Concretely
     in scope: SLLI/SRLI/SRAI require `instr[31:25] == 7'b0000000`
     (SLLI, SRLI) or `7'b0100000` (SRAI), with `instr[26:25] == 2'b00`.
     Any other shift-amount-high bit pattern is illegal.
   - `OPCODE_OP` with `{instr[26], instr[13:12]} == {1, 01}` is RV32B
     ternary (cmix/cmov/fsl/fsr) — illegal in scope
     (ref: ibex_decoder.sv:455-456).
   - `OPCODE_OP` with `{instr[31:25], instr[14:12]}` not in the
     RV32I or RV32M list — illegal
     (ref: ibex_decoder.sv:458-559, default at 556-558).
     RV32M requires `RV32M != RV32MNone`, satisfied in scope.
   - `OPCODE_MISC_MEM` with funct3 ∉ {000, 001}
     (ref: ibex_decoder.sv:587-589).
   - `OPCODE_SYSTEM` funct3=000 with funct12 ∉ {0x000, 0x001, 0x302,
     0x7B2, 0x105} OR with rs1≠0 OR rd≠0
     (ref: ibex_decoder.sv:614-621).
   - `OPCODE_SYSTEM` funct3 ∉ {000, 001, 010, 011, 101, 110, 111}
     (i.e. funct3=100) — sets `csr_illegal = 1`
     (ref: ibex_decoder.sv:632-639).
3. The compressed-decoder upstream signals `illegal_c_insn_i = 1`
   (ref: ibex_decoder.sv:649-651).
4. (Out of scope) `illegal_reg_rv32e` — fixed at 0 because
   `RV32E = 0` (ref: ibex_decoder.sv:186-188, 1197).

When `illegal_insn` is asserted, the decoder SHALL also force
`rf_we = 0`, `data_req_o = 0`, `data_we_o = 0`, `jump_in_dec_o = 0`,
`jump_set_o = 0`, `branch_in_dec_o = 0`, `csr_access_o = 0`
(ref: ibex_decoder.sv:658-666). This masking is performed inside the
main `always_comb` after the opcode case completes.

The trap flags (`ebrk/mret/dret/ecall/wfi`) are NOT masked by
`illegal_insn`; they are only set in legal SYSTEM funct12 sub-arms.

`mult_en_o` and `div_en_o` are `mult_sel_o` / `div_sel_o` masked by
`~illegal_insn` outside the always_comb (ref: ibex_decoder.sv:1192-1193).

#### Scenario: All-zero instruction is illegal

- GIVEN `instr_rdata_i = 32'h00000000`
- THEN `illegal_insn_o = 1`, `rf_we_o = 0`, `data_req_o = 0`
- (ref: ibex_decoder.sv:643-644, 658-666)

#### Scenario: All-ones instruction is illegal

- GIVEN `instr_rdata_i = 32'hFFFFFFFF`
- THEN `illegal_insn_o = 1` (opcode = 0x7F is not a valid `opcode_e`)

#### Scenario: RV32B opcode (e.g. `bset`) is illegal

- GIVEN `instr_rdata_i = 32'h28C58533` (`BCLR x10, x11, x12`,
  OPCODE_OP funct7=0x14 funct3=0x0 — RV32B-only encoding)
- WHEN `RV32B = RV32BNone`
- THEN `illegal_insn_o = 1`
- (ref: ibex_decoder.sv:489-494)

#### Scenario: Compressed-illegal pass-through

- GIVEN `instr_rdata_i = 32'h00C58533` (legal ADD), `illegal_c_insn_i = 1`
- THEN `illegal_insn_o = 1`, all masked outputs forced to 0
- (ref: ibex_decoder.sv:649-651)

#### Scenario: Legal ADD has illegal_insn_o = 0

- GIVEN `instr_rdata_i = 32'h00C58533` (`ADD x10, x11, x12`),
  `illegal_c_insn_i = 0`
- THEN `illegal_insn_o = 0`

## Notes

- **Clock and reset.** With `RV32B = RV32BNone` the body is purely
  combinational. `clk_i` and `rst_ni` are accepted at the boundary so
  upstream SVA properties have something to sample, but no ARCH state
  element references them. The ARCH `module` SHALL nonetheless declare
  `clk_i` and `rst_ni` ports for boundary compatibility with the SoC
  shadow harness. (ref: ibex_decoder.sv:156-166 — `gen_no_rs3_flop`
  branch.)

- **`instr` vs. `instr_alu` replication.** Two replicas of the
  instruction word are required at the boundary. The bodies of the
  two `always_comb` blocks read disjoint subsets of fields:
  - `instr_rdata_i` (alias `instr`) drives:
    `imm_*_type_o`, `zimm_rs1_type_o`, `csr_addr_o`, `rf_raddr_*_o`,
    `rf_waddr_o`, `rf_we`, `rf_ren_*_o`, `rf_wdata_sel_o`,
    `csr_access_o`, `csr_illegal`, internal `csr_op` (and thus
    `csr_op_o` after the operand-zero check), `data_*_o`, `ebrk_o`,
    `mret_o`, `dret_o`, `ecall_o`, `wfi_o`, `multdiv_operator_o`,
    `multdiv_signed_mode_o`, `jump_in_dec_o`, `jump_set_o`,
    `branch_in_dec_o`, `icache_inval_o`, internal `illegal_insn`.
  - `instr_rdata_alu_i` (alias `instr_alu`) drives:
    `alu_operator_o`, `alu_op_a_mux_sel_o`, `alu_op_b_mux_sel_o`,
    `imm_a_mux_sel_o`, `imm_b_mux_sel_o`, `bt_a_mux_sel_o`,
    `bt_b_mux_sel_o`, `mult_sel_o`, `div_sel_o`, `alu_multicycle_o`,
    internal `use_rs3_d`.
  - `mult_en_o` / `div_en_o` mix both: they combine `mult_sel_o` /
    `div_sel_o` (from `instr_alu`) with `illegal_insn` (from
    `instr`) (ref: ibex_decoder.sv:1192-1193).
  - `illegal_insn_o` and `rf_we_o` come from the `instr` side
    (ref: ibex_decoder.sv:1197, 1200).

  In the in-scope SoC, both replicas are wired identically, so test
  cases drive `instr_rdata_i = instr_rdata_alu_i = <encoding>`. The
  ARCH module SHALL accept differing replicas at the boundary; if a
  test ever drives them differently, the per-output sourcing above
  applies.

- **`gen_rs3_flop` is out of scope.** With `RV32B = RV32BNone` the
  rs3 latch is elided and the address mux at line 172 reduces to
  `rf_raddr_a_o = instr_rs1`. The ARCH module SHALL implement
  `rf_raddr_a_o = instr_rdata_i[19:15]` directly with no flop and no
  conditional on `instr_first_cycle_i`. (ref: ibex_decoder.sv:156-166,
  172.)

- **`alu_multicycle_o` is constant in scope.** It is only set inside
  `if (RV32B != RV32BNone)` arms (ref: ibex_decoder.sv:856, 862, 868,
  874, 880, 886, 904, 921, 957, 966, 975, 984, 1012, 1018, 1089,
  1095). With `RV32B = RV32BNone` it stays at its default `0`.

- **Default-arm fall-through values are observable.** For most
  unknown opcodes the ALU-control block's `default: ;` arm leaves
  ALU outputs at their *block-level* defaults (not at any opcode arm
  values). The main decoder block's default sets `illegal_insn = 1`,
  which then masks `rf_we`, `data_req_o`, etc. — but it does NOT
  reset `alu_operator_o` / `alu_op_a_mux_sel_o` etc., which already
  hold their block defaults. Test scenarios for "illegal opcode" can
  observe `alu_operator_o = ALU_SLTU` (44),
  `alu_op_a_mux_sel_o = OP_A_IMM`, `alu_op_b_mux_sel_o = OP_B_IMM`,
  etc. on these inputs.

- **`branch_taken_i` is unused in scope.** It only feeds the
  BranchTargetALU=1 path of the BRANCH arm (ref: ibex_decoder.sv:757,
  771). With `BranchTargetALU = 0` and a branch that is taken, the
  second-cycle path drives `imm_b_mux_sel_o = branch_taken_i ?
  IMM_B_B : IMM_B_INCR_PC` at line 771 — so this signal IS used in
  the `BranchTargetALU=0` second cycle of a branch. The ARCH module
  MUST honor this rule.

  Concretely: when opcode = BRANCH and `instr_first_cycle_i = 0`,
  `imm_b_mux_sel_o = branch_taken_i ? IMM_B_B (2) : IMM_B_INCR_PC (5)`.

- **`unique case` semantics.** Upstream uses `unique case` which
  asserts at synthesis time that exactly one arm matches. The ARCH
  port does not need to enforce uniqueness — the `opcode_e` variants
  cover disjoint opcode encodings by construction, and the default
  arm catches anything unmatched. Functional equivalence is what the
  spec requires, not synthesis-pragma equivalence.

- **`unused_instr_alu` and `unused_clk`/`unused_rst_n`.** Upstream ties
  off bits 19:15 and 11:7 of `instr_alu`, plus `clk_i`/`rst_ni`, to
  silence lint warnings. The ARCH port has no equivalent obligation;
  these `unused_*` assignments are not part of the port contract.
