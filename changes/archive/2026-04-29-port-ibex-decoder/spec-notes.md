# Decoder spec — author notes from the test stage

Two minor spec-text-vs-hex inconsistencies surfaced while authoring
tests. Both are cosmetic — the *hex* the spec provides drives the
correct test outcome; only the human-readable annotation is off. The
arch implementer can safely treat the spec's behavioral rules as
authoritative.

## 1. RV32B "BSET" scenario hex actually decodes to BCLR

Spec §"Illegal-instruction aggregation", scenario "RV32B opcode (e.g.
`bset`) is illegal":

> GIVEN `instr_rdata_i = 32'h28C58533` (`BSET x10, x11, x12`,
> OPCODE_OP funct7=0x29 → matches `{7'b001_0100, 3'b001}` in line 490)

Decoding `0x28C58533`:
- opcode = 0x33 (OPCODE_OP) — correct
- funct3 = 0b000 (NOT 0b001 as annotated)
- funct7 = 0x14 (NOT 0x29 as annotated)

`{funct7=7'b0010100, funct3=3'b000}` is the upstream encoding for
**BCLR**, not BSET. Both are RV32B-only, so under `RV32B = RV32BNone`
the decoder still emits `illegal_insn_o = 1`, which is what the test
asserts. The behavioral assertion is correct; only the mnemonic and
the cited line annotation are misleading. Recommend the spec author
update the scenario text to either:
- (a) cite the correct mnemonic (BCLR) and funct7 (0x14), or
- (b) replace the hex with one that actually encodes BSET, e.g.
  `0x28C59533` (funct7=0x14, funct3=001 — BSET in the upstream RV32B
  table at line 490).

## 2. CSRRW with rd=0 scenario hex actually has rd=1

Spec §"CSR control", scenario "CSRRW with rd=0 keeps CSR_OP_WRITE":

> GIVEN `instr_rdata_i = 32'h305590F3` (`CSRW mtvec, x11` =
> `CSRRW x0, mtvec, x11`, funct3=001, rs1=11)

Decoding `0x305590F3`:
- opcode = 0x73 — correct
- funct3 = 0b001 — correct
- rs1 = 11 — correct
- **rd = 1, not 0** (instr[11:7] = 0b00001)
- csr = 0x305 — correct

The behavioral assertion the spec is testing — that the rs1=0 demote
rule does NOT trigger on a CSR instruction with rd=0 (the demote rule
checks rs1, not rd) — still holds for this hex because rs1=11 is
non-zero, so `csr_op_o` reads `CSR_OP_WRITE` regardless of rd's
value. The test passes either way. To make the scenario actually
exercise rd=0 the hex should be `0x30559073` (clears `instr[11:7]`).

## Summary

Neither inconsistency required a test redesign — both behavioral
assertions are well-defined under the hex the spec provides. Flagging
them so the spec author can tighten the human-readable annotations
before archive.
