# Proposal: Port `ibex_decoder` to ARCH

## Intent

Replace upstream `ibex_decoder.sv` (1212 LoC) — the RISC-V instruction
decoder — with an ARCH-side equivalent. This is the **fourth** leaf-module
swap (A4) and the largest by an order of magnitude over A1–A3. It is a
pure-combinational module that reads a 32-bit instruction word and drives
~50 control signals (immediate extraction, register-file selectors, ALU
operator, mult/div control, CSR control, LSU control, branch/jump
flags). It is the single biggest control-plane module in the Ibex core
and — critically for the porting effort — it consumes a large share of
the enums declared in `ibex_pkg.sv`.

A4 is the first swap that exercises:

1. **Heavy enum-typed port boundary** — `alu_op_e`, `op_a_sel_e`,
   `op_b_sel_e`, `imm_a_sel_e`, `imm_b_sel_e`, `rf_wd_sel_e`,
   `csr_op_e`, `csr_num_e`, `md_op_e`, `opcode_e`. The spec must
   enumerate every value the decoder produces.
2. **A large `case` over instruction opcodes** with nested
   `funct3`/`funct7` sub-decodes. The arch implementer will likely
   structure this as nested `if/elsif` over slices of `instr_rdata_i`,
   or use an ARCH `match` if the language supports it on enums.
3. **Two replicas of the instruction word** (`instr_rdata_i` for most
   outputs, `instr_rdata_alu_i` for ALU control) — a fan-out
   optimization in upstream that the ARCH version must preserve at the
   port boundary even if the body sometimes uses one or the other.

## Scope

**In scope** — default Ibex small configuration:

- `RV32E = 0` — full 32-register RV32. (No special-case "x16-x31 are
  illegal" path.)
- `RV32M = RV32MFast` — multiplier/divider available. The decoder
  emits `mult_en_o` / `div_en_o` / `multdiv_operator_o` /
  `multdiv_signed_mode_o` for the M-extension instructions; the actual
  sequencing lives in `ibex_multdiv_*.sv` (Phase A6).
- `RV32B = RV32BNone` — no bitmanip. Bitmanip-only opcodes return
  `illegal_insn_o = 1`. The decoder does NOT need to handle the
  RV32B-only state machine logic.
- `BranchTargetALU = 0` — branch target arithmetic shares the main
  ALU. `bt_a_mux_sel_o` / `bt_b_mux_sel_o` are still wired but will
  default to the same selectors the main ALU uses.
- All RV32I base instructions: `LUI`, `AUIPC`, jump (JAL/JALR), branch
  (BEQ/BNE/BLT/BGE/BLTU/BGEU), load (LB/LH/LW/LBU/LHU), store
  (SB/SH/SW), op-imm (ADDI/SLTI/SLTIU/XORI/ORI/ANDI/SLLI/SRLI/SRAI),
  op (ADD/SUB/SLL/SLT/SLTU/XOR/SRL/SRA/OR/AND), MISC-MEM (FENCE,
  FENCE.I), SYSTEM (CSR / ECALL / EBREAK / MRET / DRET / WFI).
- All RV32M instructions: MUL/MULH/MULHSU/MULHU/DIV/DIVU/REM/REMU.
- Compressed-instruction interaction: `illegal_c_insn_i` propagates
  to `illegal_insn_o` regardless of opcode. Compressed expansion
  itself lives in `ibex_compressed_decoder.sv` (Phase A5).

**Out of scope**:

- RV32B (bitmanip) full operator set — Phase D opentitan-config.
- `BranchTargetALU = 1` separate-ALU mode.
- `RV32E = 1` 16-register variant.
- The `gen_rs3_flop` block (rs3 latching for RV32B multi-cycle ops) —
  not exercised when RV32BNone.

## Approach

Tentative ARCH constructs (final choice deferred to the spec-only
implementation agent):

- Pure `module` with combinational outputs. The clock and reset ports
  exist on the SV boundary purely so SVA assertions can fire — the ARCH
  body uses neither.
- Field extraction via fixed slices of `instr_rdata_i` (opcode at
  `[6:0]`, funct3 at `[14:12]`, funct7 at `[31:25]`, rs1/rs2/rd at
  their fixed positions).
- A primary `comb` block doing `if/elsif` (or `match`) on opcode.
  Each opcode arm sets the relevant outputs; defaults at the top of
  the block cover the "not driven by this opcode" case.
- Enum-valued ports for the many `*_sel_e` / `*_op_e` outputs. The
  spec will enumerate each enum's variants and integer encodings;
  the implementer translates them to ARCH constants (`let NAME:
  UInt<W> = …`) following the `feedback_arch_syntax_pitfalls.md` rule
  on operator-encoding constants.
- Illegal-instruction handling: `illegal_insn` is asserted by default
  and cleared (or held set) per opcode arm. CSR illegality is computed
  separately and OR'd in.

## Verification gate

Per the TDD-first / split-gate flow:

1. **Basic suite** (blocking) — ~10–15 cocotb scenarios, one per
   spec Requirement, walking the canonical instruction of each class
   (e.g. one ADD, one BEQ, one LW, one MUL, one CSRRW, one ECALL,
   one illegal opcode, one RV32B opcode → illegal_insn).
2. **Full regression** (background) — every Scenario the spec
   captures plus a sweep over the encoding space:
   - Every RV32I base instruction.
   - Every RV32M instruction.
   - All immediate-type extraction patterns (I/S/B/U/J).
   - Boundary cases (rd=x0, rs1=x0, illegal funct7 / funct3 / RV32B
     opcodes).

Conftest auto-shadow picks up `build/ibex_decoder.sv` — no SoC
integration code change.

## Reference

Upstream: `$IBEX_ROOT/rtl/ibex_decoder.sv` (Apache-2.0, 1212 LoC).
Enum types: `$IBEX_ROOT/rtl/ibex_pkg.sv`.
Instantiated from: `ibex_id_stage.sv:436`. Our SoC inherits this
binding through the standard Ibex tree.
