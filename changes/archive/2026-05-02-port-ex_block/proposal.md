# Proposal: Port `ibex_ex_block` to ARCH

## Intent

This swap replaces `ibex_ex_block.sv` (217 LoC) with `src/IbexExBlock.arch`.
`ibex_ex_block` is the EX (execute) stage container that:

1. Instantiates the ALU (`ibex_alu`, already ported as A1 `IbexAlu`) and
   the fast multiplier/divider (`ibex_multdiv_fast`, already ported as A6
   `IbexMultdivFast`).
2. Wires the combinational cross-module loop: multdiv drives 33-bit ALU
   operands, ALU returns 34-bit extended sum + equality flag, same cycle.
3. Muxes intermediate-value register data and write-enables between the two
   sub-modules based on `multdiv_sel = mult_sel_i | div_sel_i`.
4. Routes the final result (`result_ex_o`, `alu_adder_result_ex_o`,
   `branch_target_o`, `branch_decision_o`, `ex_valid_o`) to the writeback /
   IF / ID stages.

This is the first Phase B composite swap. It follows all nine Phase A leaf
swaps (A1–A9) which are already merged on `main` at `5402983`.

## Scope

**In scope:**

- `RV32M = RV32MFast` (= 2) — the SoC's configuration. The fast multdiv
  variant is instantiated.
- `RV32B = RV32BNone` (= 0) — the only configuration covered by the ALU spec.
- `BranchTargetALU = 0` — no dedicated branch-target adder; `branch_target_o`
  is wired directly from `alu_adder_result_ex_o`.
- All comb mux logic: `multdiv_sel`, `result_ex_o`, `imd_val_d_o`,
  `imd_val_we_o`, `ex_valid_o`.
- Sub-module instantiation via ARCH `inst` of `IbexAlu` and
  `IbexMultdivFast`.

**Out of scope:**

- `RV32M = RV32MSlow` (slow multdiv variant).
- `RV32M = RV32MSingleCycle` (single-cycle multdiv variant).
- `BranchTargetALU = 1` (dedicated branch-target adder path — adds a second
  adder and carry discard; not used in the SoC).
- `RV32B != RV32BNone` (bitmanip extension).
- SVA assertions (`INC_ASSERT` block) — simulation-only and not part of the
  synthesizable spec.

## Construct enumeration

| Construct      | Status | Reason |
|----------------|--------|--------|
| `module`       | **picked** | Outer container wiring two sub-modules + comb mux. Direct structural description; no specialised construct helps here. |
| `fsm`          | **rejected** | No multi-state sequencing in the container itself; the multdiv's internal FSM is inside `IbexMultdivFast`. |
| `thread`       | **rejected** | No mid-walk yield or multi-cycle wait in the container; sub-modules handle their own timing. |
| `fifo`         | **rejected** | No push/pop FIFO semantics — the container is a pure comb mux over sub-module outputs. |
| `ram`          | **N/A** | No address-indexed storage. |
| `cam`          | **N/A** | No content-addressed lookup. |
| `linklist`     | **N/A** | No pointer-chained storage. |
| `regfile`      | **N/A** | The intermediate-value register file (`imd_val_q_i` / `imd_val_d_o`) is modelled as a 2-element unpacked Vec port driven by the caller (ID stage) — not a multi-port regfile construct owned by EX. |
| `arbiter`      | **N/A** | No request-grant arbitration; `multdiv_sel` is a static decoder output, not a priority arbiter. |
| `counter`      | **N/A** | Not a freestanding count primitive. |
| `pipeline`     | **rejected** | Bespoke cross-module comb loop (multdiv ↔ ALU) and non-uniform latency make a generic stage chain inappropriate. |
| `synchronizer` | **N/A** | Single clock domain. |
| `clkgate`      | **N/A** | No clock gating at this level. |

## Approach

**Outer structure:** `module ibex_ex_block` with:
- `param RV32M: const = 2;` (RV32MFast)
- `param RV32B: const = 0;` (RV32BNone)
- `param BranchTargetALU[0:0]: const = 1'b0;` (fixed 1-bit param; avoids
  WIDTHTRUNC on ternary condition per pitfall #12)

**Port declarations:**
- Clock (`clk_i: in Clock<SysDomain>`) and async-low reset (`rst_ni: in Reset<Async, Low>`)
- ALU inputs: `alu_operator_i: in UInt<7>`, `alu_operand_a_i: in UInt<32>`, etc.
- BranchTargetALU inputs: `bt_a_operand_i: in UInt<32>`, `bt_b_operand_i: in UInt<32>`
- Multdiv inputs: `multdiv_operator_i: in UInt<2>`, `mult_en_i: in Bool`, etc.
- `imd_val_we_o: out UInt<2>`, `imd_val_d_o: out unpacked Vec<UInt<34>, 2>`,
  `imd_val_q_i: in unpacked Vec<UInt<34>, 2>` — unpacked arrays (pitfall #5)
- Standard outputs: `alu_adder_result_ex_o: out UInt<32>`, `result_ex_o: out UInt<32>`, etc.

**Internal wires:**
- `wire alu_result: UInt<32>` — ALU `result_o`
- `wire multdiv_result: UInt<32>` — MultdivFast `multdiv_result_o`
- `wire multdiv_alu_operand_a: UInt<33>` — from multdiv to ALU
- `wire multdiv_alu_operand_b: UInt<33>` — from multdiv to ALU
- `wire alu_adder_result_ext: UInt<34>` — ALU extended adder result
- `wire alu_cmp_result: Bool` — ALU comparison result
- `wire alu_is_equal_result: Bool` — ALU equality flag
- `wire multdiv_valid: Bool` — MultdivFast `valid_o`
- `wire multdiv_sel: Bool` — `mult_sel_i | div_sel_i`
- `wire alu_imd_val_q: unpacked Vec<UInt<32>, 2>` — `imd_val_q_i[i][31:0]` slices
- `wire alu_imd_val_d: unpacked Vec<UInt<32>, 2>` — from ALU `imd_val_d_o`
- `wire alu_imd_val_we: UInt<2>` — from ALU `imd_val_we_o`
- `wire multdiv_imd_val_d: unpacked Vec<UInt<34>, 2>` — from multdiv `imd_val_d_o`
- `wire multdiv_imd_val_we: UInt<2>` — from multdiv `imd_val_we_o`

**Sub-module instantiation:**
- `inst alu_i: IbexAlu` — connected to the ALU port contract
- `inst multdiv_i: IbexMultdivFast` — connected to the multdiv port contract

**Comb block(s):** One `comb` block handling:
- `multdiv_sel = mult_sel_i | div_sel_i`
- `alu_imd_val_q[0] = imd_val_q_i[0][31:0]`; `alu_imd_val_q[1] = imd_val_q_i[1][31:0]`
- `imd_val_d_o[0] = multdiv_sel ? multdiv_imd_val_d[0] : {2'b0, alu_imd_val_d[0]}`
- `imd_val_d_o[1] = multdiv_sel ? multdiv_imd_val_d[1] : {2'b0, alu_imd_val_d[1]}`
- `imd_val_we_o = multdiv_sel ? multdiv_imd_val_we : alu_imd_val_we`
- `result_ex_o = multdiv_sel ? multdiv_result : alu_result`
- `branch_decision_o = alu_cmp_result`
- `branch_target_o = alu_adder_result_ex_o` (BranchTargetALU=0 path)
- `ex_valid_o = multdiv_sel ? multdiv_valid : ~(|alu_imd_val_we)`

**bt_a_operand_i and bt_b_operand_i:** With BranchTargetALU=0, these are
unused. Assign them to a dummy let to silence Verilator UNUSED warnings,
matching upstream's `unused_bt_a_operand` / `unused_bt_b_operand` pattern.

## Verification gate

**Basic gate (blocking):**
```
make build
pytest tests/test_ex_block_unit.py tests/test_soc_lint.py tests/test_cpu_programs.py
```

**Full regression (background):**
```
pytest tests/test_ex_block_unit_full.py
```

The basic suite covers: multdiv_sel mux, ALU pass-through, multdiv pass-through,
ex_valid_o for ALU-only and multdiv cases, imd_val routing, branch_decision
and branch_target wiring. The SoC lint and 4 ISR programs validate that the
ex_block stitches cleanly into the larger pipeline.

## Verification gate caveats

1. **Sub-module cross-coupling**: the multdiv drives ALU operands (`alu_operand_*_o`
   which become `multdiv_operand_*_i` on the ALU) and reads back the ALU's
   adder result the same cycle. The unit test must supply the testbench with the
   combined `ex_block` so that this combinational loop resolves correctly.
   The unit test should drive the ex_block, not the sub-modules directly.

2. **unpacked Vec port**: `imd_val_q_i` and `imd_val_d_o` are 34-bit unpacked
   arrays in upstream SV (`logic [33:0] imd_val_q_i [2]`). Declare as
   `in unpacked Vec<UInt<34>, 2>` to match upstream's boundary. The ALU
   sub-module uses 32-bit slices (`[31:0]`), so the ex_block slices them
   in its comb block.

3. **ex_valid_o test sensitivity**: when multdiv_sel=0, `ex_valid_o = ~(|alu_imd_val_we)`.
   Under RV32BNone the ALU drives `alu_imd_val_we = 2'b00` always, so
   `ex_valid_o = 1` for all ALU-only operations. Tests should verify this.

4. **BranchTargetALU=0**: `branch_target_o` is wired from `alu_adder_result_ex_o`.
   Testbench can drive a simple ADD to verify the adder pass-through.

## Reference

- Upstream: `~/github/ibex/rtl/ibex_ex_block.sv` (217 LoC)
- Producer neighbor: `~/github/ibex/rtl/ibex_id_stage.sv` (drives alu_operator_i, alu_operand_*_i, mult/div_en_i, etc.)
- Consumer neighbor: `~/github/ibex/rtl/ibex_wb_stage.sv` (samples result_ex_o, ex_valid_o)
- ALU spec: `specs/alu/spec.md`
- Multdiv spec: `specs/multdiv/spec.md`
- Pipeline reference: `~/github/ibex/doc/03_reference/pipeline_details.rst`
