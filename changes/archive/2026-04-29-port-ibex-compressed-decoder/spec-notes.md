# Compressed-decoder spec — author notes from the extraction stage

## 1. Zcmp FSM stability with `valid_i = 0` in non-idle states

Upstream's `IbexPushPopFSMStable` SVA at line 845 asserts:

```
!valid_i |-> cm_state_d == cm_state_q
```

i.e. the FSM never advances when `valid_i = 0`, in **any** state.
However, the RTL implementation only explicitly gates on
`valid_i && id_in_ready_i` in the `CmIdle` arms (lines 571, 583, 639,
648, 715, 741). The non-idle arms (`CmPushStoreReg`, `CmPushDecrSp`,
`CmPopLoadReg`, `CmPopIncrSp`, `CmPopZeroA0`, `CmPopRetRa`,
`CmMvSecondReg`) advance on `id_in_ready_i` alone — not on
`valid_i && id_in_ready_i`.

The producer-side contract makes this safe: the IF stage holds
`valid_i = 1` and `instr_i` stable across all sub-steps of an active
Zcmp expansion (because `if_id_pipe_reg_we` is suppressed while
`gets_expanded == INSTR_EXPANDED`). So in practice the SVA holds.

**Permissive choice in the spec**: the Requirement *"Zcmp FSM
stability when `valid_i = 0`"* documents the SVA's intent (FSM frozen
on `!valid_i`) and leaves the implementation flexibility note that
non-idle arms MAY gate on `id_in_ready_i` alone, relying on the
producer guarantee. The ARCH implementer can choose either:
  (a) gate FSM advance on `id_in_ready_i` only in non-idle states
      (mirrors upstream RTL exactly); or
  (b) gate FSM advance on `valid_i && id_in_ready_i` in **all** states
      (more defensive, matches the SVA literally).

Both pass the requirement as written. Orchestrator should confirm
whether the test suite needs to exercise the `!valid_i` non-idle-state
case explicitly.

## 2. `instr_o` value when `illegal_instr_o = 1` is don't-care

The Requirements describe `instr_o` *only* for legal encodings. For
illegal encodings (the various `illegal_instr_o = 1` paths) the spec
explicitly says the consumer takes `illegal_c_insn_i` and forces
`illegal_insn_o` regardless of `instr_o` content. The ARCH port may
emit any value on `instr_o` while `illegal_instr_o = 1` — including
the partially-built expansion that upstream happens to leave on the
wire (see e.g. line 232 where `instr_o` is built first and the
illegal flag is set after).

This is documented in the *Consumer-side* integration constraint and
in the per-Requirement scenarios; flagging here so the test author
does not write a value-of-`instr_o` check on illegal paths.

## 3. Hex-vs-mnemonic spot-check confidence

I bit-true validated the following expansions by hand and against the
formula in the RTL:
  - c.addi4spn x8, sp, 4 → addi x8, x2, 4 → 0x00410413
  - c.j +0 → jal x0, 0 → 0x0000006F
  - c.jal +0 → jal x1, 0 → 0x000000EF
  - c.li x1, 0 → addi x1, x0, 0 → 0x00000093
  - c.ebreak → 0x00100073
  - c.mv x8, x9 → add x8, x0, x9 → 0x00900433
  - c.add x8, x8, x9 → add x8, x8, x9 → 0x00940433
  - c.sub/c.xor/c.or/c.and x8, x8, x9 → 0x40940433/0x00944433/0x00946433/0x00947433
  - cm.push {ra} sub-step 1 → sw x1, -4(x2) → 0xFE112E23
  - cm.push {ra} sub-step 2 → addi x2, x2, -16 → 0xFF010113
  - cm.popret jalr → jalr x0, x1, 0 → 0x00008067
  - cm.popretz a0 zero → addi a0, x0, 0 → 0x00000513

The Zcb expansions (c.zext.b, c.not), the c.lh half-immediate logic,
and the cm.mvsa01/cm.mva01s register-mapping helper were derived
algebraically from the RTL functions and **not** cross-checked
against an external assembler. The implementer should re-verify these
by running the upstream RTL through a cocotb shadow or by spot-check
disassembly.

## 4. `is_compressed_o` with `valid_i = 0`

`is_compressed_o = (instr_i[1:0] != 2'b11)` is **not** gated on
`valid_i`. If the producer feeds X bits with `valid_i = 0`, then in
4-state simulation `is_compressed_o` may go X. The producer-side
contract notes that downstream IF logic that reads
`instr_is_compressed` is itself qualified by upstream valid tracking,
so this is acceptable — the ARCH port need not gate `is_compressed_o`
on `valid_i`.

## Summary

No spec ambiguity that blocks implementation. Items 1 and 4 are
permissive choices that the orchestrator should confirm match the
intended verification surface. Item 3 is a heads-up on which hex
values were hand-derived and which were transcribed from the RTL
formula without external cross-check.
