# Proposal: Port `ibex_alu` to ARCH

## Intent

Replace upstream `ibex_alu.sv` (1400 LoC) with an ARCH-side equivalent
that emits an SV module of the same name. First leaf-module swap in the
Ibex port; primary purpose is to stress-test the full build → swap →
lint → cocotb-gate loop on the smallest meaningful design before bigger
modules consume effort.

## Scope

**In scope** — RV32B=`RV32BNone` operator set:

- Arithmetic: `ALU_ADD`, `ALU_SUB`
- Logic: `ALU_XOR`, `ALU_OR`, `ALU_AND`
- Shift: `ALU_SRA`, `ALU_SRL`, `ALU_SLL`
- Compare: `ALU_LT`, `ALU_LTU`, `ALU_GE`, `ALU_GEU`, `ALU_EQ`, `ALU_NE`,
  `ALU_SLT`, `ALU_SLTU`
- Adder result outputs (`adder_result_o`, `adder_result_ext_o`) used by
  LSU for address generation and by branch unit for target calc
- Comparator outputs (`comparison_result_o`, `is_equal_result_o`) used by
  controller for branch resolution
- `multdiv_sel_i` mux of operands into the shared adder (the multdiv unit
  reuses the ALU adder for 33-bit accumulate)

**Out of scope** — guarded by RV32B parameter, Phase D extension:

- All RV32B (bitmanip) operators: XNOR/ORN/ANDN, SRO/SLO/ROR/ROL,
  GREV/GORC, SHFL/UNSHFL, XPERM_*, SH{1,2,3}ADD, MIN/MAX(U),
  PACK/PACKU/PACKH, SEXTB/SEXTH, CLZ/CTZ/CPOP, CMOV/CMIX, FSL/FSR,
  BSET/BCLR/BINV/BEXT, BCOMPRESS/BDECOMPRESS, BFP, CLMUL{,R,H},
  CRC32{,C}_{B,H,W}
- For these operators, `result_o` returns 0 (matching `default:` arm
  in upstream's RV32B-disabled compile)
- `imd_val_q_i`/`imd_val_d_o`/`imd_val_we_o` ports stay declared at the
  module boundary but are tied to 0 / unused (they only carry RV32B
  multi-cycle state; bitmanip-disabled config never asserts `imd_val_we`)

## Approach

Pure combinational `module` — no `fsm`, no `pipeline`, no clocked logic.
The ARCH constructs exercised are:
- `module` with combinational `let` + `wire` signals for the data path
- Generic `UInt<32>` / `SInt<32>` arithmetic with explicit `signed()` /
  `unsigned()` reinterpret for SLT/SLTU and SRA distinction
- Width casts (`.zext<33>()`, `.trunc<32>()`) on the 33-bit shared adder

The single `RV32B` parameter is forwarded as a width-zero const param
to keep the SV module signature byte-compatible with upstream; the
disabled-only build collapses all RV32B-arm muxes to the default arm
during ARCH `arch check`-time constant folding.

## Verification gate

1. `arch build src/IbexAlu.arch` lands clean
2. `make filelist` includes `build/IbexAlu.sv`, excludes `ibex_alu` from
   the upstream list
3. `verilator --lint-only` on the SoC stays clean
4. Existing 4 cocotb ISR programs (timer/sw/ext/multictx) still pass
   end-to-end — these exercise ALU on every instruction the ISR programs
   execute (load/store address calc, arithmetic in trap handlers,
   comparisons in `bne` loops)
5. New focused cocotb test (`test_ibex_alu_unit.py`) drives the standalone
   `ibex_alu` instance via VPI, walks the per-operator scenarios from
   `specs/alu/spec.md`, asserts result + comparator outputs

## Reference

Upstream: `$IBEX_ROOT/rtl/ibex_alu.sv` (Apache-2.0).
Operator enum: `ibex_pkg.sv:85-189`.
