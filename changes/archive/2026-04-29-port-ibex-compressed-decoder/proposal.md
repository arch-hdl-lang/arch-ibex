# Proposal: Port `ibex_compressed_decoder` to ARCH

## Intent

Replace upstream `ibex_compressed_decoder.sv` (847 LoC) — the
RV32C/Zca/Zcb/Zcmp compressed-instruction expander — with an ARCH
equivalent. Sits in the IF stage between prefetch and the main
decoder; takes a 32-bit aligned fetch word and produces an expanded
32-bit instruction (when the low 16 bits are a compressed instruction)
or passes through (when the full 32 bits are an uncompressed RV32
instruction).

Fifth leaf-module swap (A5). First swap fully under the **methodology
elaborated after A4** — spec extractor reads neighbor blocks in BOTH
directions (`ibex_if_stage.sv` producer + `ibex_id_stage.sv`/main
decoder consumer) per
`feedback_unit_tests_dont_catch_integration.md`.

## Scope

**In scope** — match the SoC's parameter binding
(`soc/ibex_mini_soc.sv:51-52` defines `RV32ZC = ibex_pkg::RV32ZcaZcbZcmp`):

- `RV32ZC = RV32ZcaZcbZcmp` (= 3) — full Zc support.
  - **Zca**: standard RVC base — `c.addi`, `c.li`, `c.lw`, `c.sw`,
    `c.j`, `c.jal` (rv32-only), `c.beqz`, `c.bnez`, `c.lui`, `c.add`,
    `c.mv`, `c.jr`, `c.jalr`, `c.ebreak`, `c.slli`, `c.srli`, `c.srai`,
    `c.andi`, `c.and`, `c.or`, `c.xor`, `c.sub`, `c.addi16sp`,
    `c.addi4spn`, `c.swsp`, `c.lwsp`, `c.nop`.
  - **Zcb**: extra compressed — `c.lbu`, `c.lh`, `c.lhu`, `c.sb`,
    `c.sh`, `c.zext.b`, `c.sext.b`, `c.zext.h`, `c.sext.h`,
    `c.zext.w` (RV32 only), `c.not`, `c.mul`.
  - **Zcmp**: code-size optimization — `cm.push`, `cm.pop`,
    `cm.popret`, `cm.popretz`, `cm.mvsa01`, `cm.mva01s`. These are
    multi-cycle and produce a sequence of expanded 32-bit
    instructions; the decoder emits one per fetch cycle while
    `gets_expanded_o` indicates the sub-step.
- `ResetAll = 0` — default; the spec needn't cover the all-flop-reset
  variant.
- 32-bit pass-through: when `instr_i[1:0] == 2'b11`, the input is
  already a 32-bit RV32 instruction — `instr_o = instr_i`,
  `is_compressed_o = 0`.
- Illegal compressed encodings → `illegal_instr_o = 1`. The expanded
  `instr_o` may be anything in this case (downstream `ibex_decoder`
  re-validates and propagates `illegal_c_insn_i`).

**Out of scope**:

- `RV32ZC ∈ {RV32Zca, RV32ZcaZcb, RV32ZcaZcmp}` — narrower variants.
  We pick the full variant to match the SoC.
- `ResetAll = 1`.
- The SVA assertions on `valid_i` / `id_in_ready_i` (clock/reset are
  for SVA only).

## Approach

Tentative ARCH constructs (the implementer agent picks the final form):

- Pure `module` with comb outputs. SV `clk_i`/`rst_ni` ports are SVA-
  only; the body never reads them (same pattern as `ibex_alu` /
  `ibex_decoder`).
- A primary `comb` block doing `if/elsif` (or nested `match`) on
  `instr_i[1:0]` (compressed quadrant) and `instr_i[15:13]` (funct3
  for compressed). Each arm builds the 32-bit `instr_o` via concat /
  immediate sign-extension.
- For Zcmp's multi-cycle expansion: the decoder is purely combinational
  but emits a *sequence* of expansions across fetches. The caller
  drives the same compressed instruction repeatedly with different
  `gets_expanded_o` cycles; the decoder must track which sub-step it
  is on. Looking at upstream, this is implemented as combinational
  logic over `gets_expanded_o` (an enum input from the IF stage)
  plus the original compressed encoding — so it stays combinational
  here too. **Note**: revisit during spec extraction; the agent will
  capture the exact protocol.

## Verification gate

Per the TDD-first / split-gate flow:

1. **Basic suite** (blocking) — one cocotb test per spec Requirement
   (~10–15 tests covering: pass-through 32-bit, each Zca instruction
   class, each Zcb instruction class, each Zcmp sub-step, illegal
   encoding).
2. **Full regression** (background) — every Zca + Zcb + Zcmp encoding
   the spec captures, plus immediate-extension boundary cases and
   illegal-encoding sweeps.

The conftest auto-shadow picks up `build/ibex_compressed_decoder.sv`.

The existing 4 ISR programs are compiled with `-march=rv32im_zicsr`
(no `c` extension) so they only exercise the pass-through case. The
unit-test suite is the primary verification surface for compressed
expansion correctness.

## Reference

Upstream: `$IBEX_ROOT/rtl/ibex_compressed_decoder.sv` (Apache-2.0,
847 LoC).
Producer (input neighbor): `ibex_if_stage.sv:414` (drives `instr_i`,
`valid_i`, `id_in_ready_i`).
Consumer (output neighbor): `ibex_id_stage.sv` via the main `ibex_decoder`'s
`instr_rdata_i` port (consumes `instr_o`, also passes
`illegal_c_insn_i = illegal_instr_o`).
Reference doc: `~/github/ibex/doc/03_reference/instruction_fetch.rst`.
