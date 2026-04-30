# Compressed Decoder Specification

## Purpose

`ibex_compressed_decoder` is the RVC/Zca/Zcb/Zcmp expander that sits in
Ibex's Instruction-Fetch (IF) stage between the prefetch buffer/icache
output and the IF→ID pipeline registers. Its single job is to translate
each 16-bit RISC-V compressed instruction into the bit-equivalent 32-bit
RV32 encoding that the main `ibex_decoder` was written to handle. The
upstream IF-stage documentation states the design intent: *"Compressed
instructions are expanded by the IF stage so the decoder can always
deal with uncompressed instructions (the ID stage still receives the
compressed instruction for placing into mtval on an illegal instruction
exception)"*
(ref: ibex/doc/03_reference/instruction_fetch.rst:22).

The module is described by the file header as *"fully combinatorial,
clock and reset are used for assertions only"*
(ref: ibex_compressed_decoder.sv:9-11). The single combinational path
inspects `instr_i[1:0]`. If those bits equal `2'b11`, the word is an
uncompressed RV32 instruction and the decoder forwards it unmodified;
otherwise the low 16 bits are treated as a compressed instruction and
expanded according to the chosen `RV32ZC` parameter.

The Zcmp extension introduces compressed instructions (`cm.push`,
`cm.pop`, `cm.popret`, `cm.popretz`, `cm.mvsa01`, `cm.mva01s`) that
expand to *multiple* 32-bit RV32 instructions. The decoder emits one
expanded instruction per fetch cycle; the IF stage holds the same
compressed encoding stable on `instr_i` while the decoder uses an
internal Zcmp FSM (the only state in the module) to step through the
expansion. The output `gets_expanded_o` advertises the sub-step state
to the IF stage so it can keep the same input asserted until the
decoder signals `INSTR_EXPANDED_LAST`
(ref: ibex_compressed_decoder.sv:179-194, 196-205).

## Port contract

### Parameters

| Name        | Type           | Default              | Meaning                                                                      |
|-------------|----------------|----------------------|------------------------------------------------------------------------------|
| `RV32ZC`    | `rv32zc_e`     | `RV32ZcaZcbZcmp` (3) | Selects which compressed-extension subset is enabled. This port is locked to `RV32ZcaZcbZcmp` for the ARCH port (per `proposal.md`). |
| `ResetAll`  | `bit`          | `1'b0`               | If 1, all internal flops have explicit asynchronous reset; if 0, only the FSM state register `cm_state_q` is reset (ref: ibex_compressed_decoder.sv:798-822). The ARCH port locks this to 0. |

### Ports

| Name              | Dir | Width | Purpose / Notes                                                                                          |
|-------------------|-----|-------|-----------------------------------------------------------------------------------------------------------|
| `clk_i`           | in  | 1     | Clock. Used **only** for the `cm_state_q`/`cm_rlist_q`/`cm_sp_offset_q` flops (Zcmp FSM) and for SVA. Comb outputs do not depend on edges. |
| `rst_ni`          | in  | 1     | Active-low async reset. Resets `cm_state_q` to `CmIdle` (ref: ibex_compressed_decoder.sv:798-804). With `ResetAll=0`, `cm_rlist_q`/`cm_sp_offset_q` are not reset. |
| `valid_i`         | in  | 1     | Producer-side strobe: `instr_i` carries a valid fetched word. Used (a) by the `gen_gets_expanded` mux to gate `gets_expanded_o` to `INSTR_NOT_EXPANDED` when low (ref: ibex_compressed_decoder.sv:200-205); (b) as a guard for FSM advance on the *first* sub-step (ref: ibex_compressed_decoder.sv:571, 583, 639, 648, 715, 741); (c) for assertions. |
| `id_in_ready_i`   | in  | 1     | Consumer-side ready: ID stage will accept `instr_o` this cycle. Used to advance the Zcmp FSM `cm_state_d` on every sub-step (ref: ibex_compressed_decoder.sv:571, 591, 606, 656, 673, 687, 693, 715, 722, 741, 748). |
| `instr_i[31:0]`   | in  | 32    | Word from the prefetch buffer. The low 16 bits hold the compressed instruction when `instr_i[1:0] != 2'b11`; the full 32 bits hold an RV32 instruction when `instr_i[1:0] == 2'b11`. |
| `instr_o[31:0]`   | out | 32    | Expanded RV32 instruction (or pass-through). Default is `instr_o = instr_i` (ref: ibex_compressed_decoder.sv:213). For Zcmp, this changes per FSM sub-step. |
| `is_compressed_o` | out | 1     | Pure combinational decode of the LSBs: `(instr_i[1:0] != 2'b11)` (ref: ibex_compressed_decoder.sv:796). Independent of `valid_i` and of `illegal_instr_o`. |
| `gets_expanded_o` | out | 2     | `instr_exp_e` enum. `INSTR_NOT_EXPANDED` for non-Zcmp (single-cycle) decodes; `INSTR_EXPANDED` for non-final Zcmp sub-steps; `INSTR_EXPANDED_LAST` for the final sub-step. Gated to `INSTR_NOT_EXPANDED` whenever `valid_i = 0` and Zcmp is enabled (ref: ibex_compressed_decoder.sv:200-205). |
| `illegal_instr_o` | out | 1     | Decoder rejected this 16-bit encoding. The expanded `instr_o` is **don't-care** when this is high — the consumer (`ibex_decoder`) re-validates and forces `illegal_insn_o` (ref: ibex_decoder.sv:649-651). |

## Enum encodings

Integer values taken from `ibex_pkg.sv` (no symbolic remapping).

### `rv32zc_e` (parameter type)

| Symbolic name        | Integer value |
|----------------------|---------------|
| `RV32Zca`            | 0             |
| `RV32ZcaZcb`         | 1             |
| `RV32ZcaZcmp`        | 2             |
| `RV32ZcaZcbZcmp`     | 3             |

(ref: ibex_pkg.sv:55-60). The ARCH port fixes this to `RV32ZcaZcbZcmp = 3`.

### `instr_exp_e` (output `gets_expanded_o`)

| Symbolic name          | Integer value (`logic [1:0]`) |
|------------------------|-------------------------------|
| `INSTR_NOT_EXPANDED`   | `2'd0`                        |
| `INSTR_EXPANDED`       | `2'd1`                        |
| `INSTR_EXPANDED_LAST`  | `2'd2`                        |

(ref: ibex_pkg.sv:310-315).

### `opcode_e` (used inside expansion formulas, `logic [6:0]`)

The compressed decoder produces these opcodes inside the expanded
`instr_o[6:0]`. Spec reproduces only what the decoder emits.

| Symbolic name     | Value      |
|-------------------|------------|
| `OPCODE_LOAD`     | `7'h03`    |
| `OPCODE_OP_IMM`   | `7'h13`    |
| `OPCODE_STORE`    | `7'h23`    |
| `OPCODE_OP`       | `7'h33`    |
| `OPCODE_LUI`      | `7'h37`    |
| `OPCODE_BRANCH`   | `7'h63`    |
| `OPCODE_JALR`     | `7'h67`    |
| `OPCODE_JAL`      | `7'h6f`    |

(ref: ibex_pkg.sv:66-78).

### Internal `cm_state_e` (Zcmp FSM, not exposed)

The Zcmp FSM is internal. Documented here only because two
Requirements reference state names:

```
CmIdle, CmPushStoreReg, CmPushDecrSp,
CmPopLoadReg, CmPopIncrSp, CmPopZeroA0, CmPopRetRa,
CmMvSecondReg
```

(ref: ibex_compressed_decoder.sv:179-191).

## Requirements

The keywords MUST, MUST NOT, SHOULD, MAY are used per RFC-2119.

Conventions for scenarios:
- Hex shown as a 16-bit `c.<x>` is the value on `instr_i[15:0]`; the
  upper bits of `instr_i` may be anything.
- The expanded 32-bit hex is the expected `instr_o`.
- Bit-formula notation: `{...}` = SV concatenation, `{N{x}}` = N-fold
  replication (sign-extension when `x` is the sign bit), `'` after a
  register name indicates the 3-bit RVC register field which expands
  to `{2'b01, instr_i[<bits>]}` (i.e. registers x8..x15).

### Requirement: 32-bit pass-through

The decoder MUST NOT modify `instr_i` when `instr_i[1:0] == 2'b11`
(uncompressed RV32). It MUST drive `is_compressed_o = 0`,
`illegal_instr_o = 0`, `gets_expanded_o = INSTR_NOT_EXPANDED`, and
`instr_o = instr_i`. The pass-through arm is the empty case at line
788 — by default `instr_o = instr_i`, `illegal_instr_o = 0`,
`gets_expanded = INSTR_NOT_EXPANDED` (ref: ibex_compressed_decoder.sv:212-215, 788).

#### Scenario: pass through addi
Given `instr_i = 32'h00100093` (RV32 `addi x1, x0, 1`)
And `valid_i = 1`
When the decoder evaluates combinational outputs
Then `instr_o == 32'h00100093`
And `is_compressed_o == 1'b0`
And `illegal_instr_o == 1'b0`
And `gets_expanded_o == INSTR_NOT_EXPANDED`

#### Scenario: pass through ebreak
Given `instr_i = 32'h00100073` (`ebreak`)
And `valid_i = 1`
When the decoder evaluates
Then `instr_o == 32'h00100073` and `is_compressed_o == 1'b0`.

---

### Requirement: Zca quadrant 0 — c.addi4spn

For `instr_i[15:0] = {3'b000, nzuimm[5:4|9:6|2|3], rd', 2'b00}` the
decoder MUST emit `addi rd', x2, nzuimm` per the RV32 I-type encoding
(ref: ibex_compressed_decoder.sv:227-232):

```
instr_o = {2'b0, instr_i[10:7], instr_i[12:11], instr_i[5],
           instr_i[6], 2'b00, 5'h02, 3'b000,
           2'b01, instr_i[4:2], OPCODE_OP_IMM};
```

The decoder MUST raise `illegal_instr_o = 1` when `instr_i[12:5] == 8'b0`
(reserved encoding — `nzuimm` must be non-zero per RVC spec)
(ref: ibex_compressed_decoder.sv:231).

#### Scenario: c.addi4spn x8, sp, 4
Given `instr_i[15:0] = 16'h0040` (`{000, 00000, 010, 00}` = `c.addi4spn x8, sp, 4`)
When evaluated
Then `instr_o == 32'h00410413` (`addi x8, x2, 4`)
And `is_compressed_o == 1'b1`
And `illegal_instr_o == 1'b0`.

#### Scenario: c.addi4spn reserved (zero immediate)
Given `instr_i[15:0] = 16'h0000` (all zeros — quadrant 0, funct3 0, all imm bits zero)
When evaluated
Then `illegal_instr_o == 1'b1`.

---

### Requirement: Zca quadrant 0 — c.lw

For `instr_i[15:13] = 3'b010` in quadrant 0, the decoder MUST emit
`lw rd', uimm(rs1')`
(ref: ibex_compressed_decoder.sv:234-238):

```
instr_o = {5'b0, instr_i[5], instr_i[12:10], instr_i[6],
           2'b00, 2'b01, instr_i[9:7], 3'b010,
           2'b01, instr_i[4:2], OPCODE_LOAD};
```

The encoding has no illegal sub-case in the upstream module: every
combination of `rs1'`, `rd'`, immediate is legal.

#### Scenario: c.lw x8, 0(x9)
Given `instr_i[15:0] = 16'h4080` (`010 000 001 00 000 00`)
Then `instr_o == 32'h0004A403` (`lw x8, 0(x9)`).

#### Scenario: c.lw x15, 124(x14) (max immediate)
Given `instr_i[15:0] = 16'h5FFC` (uimm = 124, rs1' = x14, rd' = x15)
Then `instr_o == 32'h07C72783` (`lw x15, 124(x14)`).

---

### Requirement: Zca quadrant 0 — c.sw

For `instr_i[15:13] = 3'b110` in quadrant 0, the decoder MUST emit
`sw rs2', uimm(rs1')`
(ref: ibex_compressed_decoder.sv:240-245):

```
instr_o = {5'b0, instr_i[5], instr_i[12], 2'b01, instr_i[4:2],
           2'b01, instr_i[9:7], 3'b010, instr_i[11:10],
           instr_i[6], 2'b00, OPCODE_STORE};
```

#### Scenario: c.sw x8, 0(x9)
Given `instr_i[15:0] = 16'hC080` (`110 000 001 00 000 00`)
Then `instr_o == 32'h0084A023` (`sw x8, 0(x9)`).

#### Scenario: c.sw x15, 4(x14)
Given `instr_i[15:0] = 16'hC278` (uimm = 4, rs1' = x14, rs2' = x14, rd unused)
Then `instr_o == 32'h00E72223` (`sw x14, 4(x14)`).

---

### Requirement: Zcb quadrant 0 — c.lbu / c.lh / c.lhu / c.sb / c.sh

For `instr_i[15:13] = 3'b100` in quadrant 0, the decoder dispatches
on `instr_i[12:10]` (and `instr_i[6]` for half-word loads/stores).
This sub-quadrant exists only when `RV32ZC ∈ {RV32ZcaZcb,
RV32ZcaZcbZcmp}`. With `RV32ZC = RV32ZcaZcbZcmp` (the locked value
for the ARCH port) every covered sub-encoding MUST expand as below
and unmapped values MUST raise `illegal_instr_o = 1`
(ref: ibex_compressed_decoder.sv:247-307).

| `instr_i[12:10]` | `instr_i[6]` | mnemonic   | expansion (line)                |
|------------------|--------------|------------|---------------------------------|
| `3'b000`         | `x`          | c.lbu      | `lbu rd', uimm(rs1')` (252-254) |
| `3'b001`         | `0`          | c.lhu      | `lhu rd', uimm(rs1')` (260-262) |
| `3'b001`         | `1`          | c.lh       | `lh  rd', uimm(rs1')` (264-266) |
| `3'b010`         | `x`          | c.sb       | `sb  rs2', uimm(rs1')` (276-278) |
| `3'b011`         | `0`          | c.sh       | `sh  rs2', uimm(rs1')` (286-287) |
| `3'b011`         | `1`          | (illegal)  | `illegal_instr_o = 1` (290)     |
| any other        | -            | (illegal)  | `illegal_instr_o = 1` (300)     |

The c.lbu expansion is:
```
instr_o = {10'b0, instr_i[5], instr_i[6], 2'b01, instr_i[9:7],
           3'b100, 2'b01, instr_i[4:2], OPCODE_LOAD};
```

The c.lhu / c.lh expansions zero out the second-lowest immediate bit
(`{10'b0, instr_i[5], 1'b0, ...}`) — the half-word RVC immediate is
single-bit (`uimm = {instr_i[5], 1'b0}`).

The c.sb expansion is:
```
instr_o = {7'b0, 2'b01, instr_i[4:2], 2'b01, instr_i[9:7],
           3'b000, 3'b0, instr_i[5], instr_i[6], OPCODE_STORE};
```

The c.sh expansion forces `instr_i[6] = 0` in the immediate field
even though the input bit is already required to be 0 by the spec.
The line-289 comment notes *"The instr_i[6] should always be zero
according to the reference"*; the implementation defensively raises
`illegal_instr_o = 1` whenever `instr_i[6] = 1` for the c.sh encoding
(ref: ibex_compressed_decoder.sv:289-291).

#### Scenario: c.lbu x8, 0(x9)
Given `instr_i[15:0] = 16'h8080` (`100 000 001 00 000 00`)
Then `instr_o == 32'h0004C403` (`lbu x8, 0(x9)`).

#### Scenario: c.lh x8, 2(x9)
Given `instr_i[15:0] = 16'h8460` (`100 001 001 1 1 000 00`: funct3=100, instr_i[12:10]=001, instr_i[6]=1, rs1'=x9, rd'=x8)
Then `instr_o == 32'h0024D403` — wait: the immediate uses only
`instr_i[5]` for bit 1 of the half-word offset. Given `instr_i[5]=0`,
imm=0; given `instr_i[5]=1`, imm=2. For `instr_i[15:0] = 16'h8460`
imm=2, mnemonic = `lh x8, 2(x9)` -> `instr_o == 32'h0024D403`.

#### Scenario: c.sh with reserved instr_i[6]=1
Given `instr_i[15:13] = 3'b100`, `instr_i[12:10] = 3'b011`, `instr_i[6] = 1'b1`, `instr_i[1:0] = 2'b00`
Then `illegal_instr_o == 1'b1`.

#### Scenario: Reserved q0/funct3=100, instr_i[12:10]=110
Given `instr_i[15:13] = 3'b100`, `instr_i[12:10] = 3'b110`, `instr_i[1:0] = 2'b00`
Then `illegal_instr_o == 1'b1`.

---

### Requirement: Zca quadrant 0 reserved funct3 codes

For `instr_i[15:13] ∈ {3'b001, 3'b011, 3'b101, 3'b111}` in quadrant 0,
the decoder MUST raise `illegal_instr_o = 1` (these encodings are
reserved for c.fld/c.fsd/c.lq/c.sq which Ibex does not implement)
(ref: ibex_compressed_decoder.sv:309-314).

#### Scenario: reserved funct3=001
Given `instr_i[15:13] = 3'b001`, `instr_i[1:0] = 2'b00`
Then `illegal_instr_o == 1'b1`.

#### Scenario: reserved funct3=111
Given `instr_i[15:13] = 3'b111`, `instr_i[1:0] = 2'b00`
Then `illegal_instr_o == 1'b1`.

---

### Requirement: Zca quadrant 1 — c.addi / c.nop

For `instr_i[15:13] = 3'b000` in quadrant 1, the decoder MUST emit
`addi rd, rd, sext(imm)`. When `rd = 0` and `imm = 0` this is the
canonical c.nop encoding. The implementation does not special-case
`rd = 0`: hint encodings with `rd = 0` are translated to `addi x0, x0, imm`
which the main decoder will accept as a hint
(ref: ibex_compressed_decoder.sv:329-334):

```
instr_o = {{6{instr_i[12]}}, instr_i[12], instr_i[6:2],
           instr_i[11:7], 3'b0, instr_i[11:7], OPCODE_OP_IMM};
```

Never raises `illegal_instr_o`.

#### Scenario: c.nop
Given `instr_i[15:0] = 16'h0001`
Then `instr_o == 32'h00000013` (`addi x0, x0, 0`).

#### Scenario: c.addi x1, x1, -1
Given `instr_i[15:0] = 16'h10FD` (sign-bit set, imm = -1, rd = x1)
Then `instr_o == 32'hFFF08093` (`addi x1, x1, -1`).

---

### Requirement: Zca quadrant 1 — c.jal / c.j

For `instr_i[15:13] = 3'b001` (c.jal) or `3'b101` (c.j) in
quadrant 1, the decoder MUST emit `jal rd, sext(imm)` where `rd = x1`
for c.jal and `rd = x0` for c.j. The destination register is encoded
by `~instr_i[15]` in the J-immediate
(ref: ibex_compressed_decoder.sv:336-342):

```
instr_o = {instr_i[12], instr_i[8], instr_i[10:9], instr_i[6],
           instr_i[7], instr_i[2], instr_i[11], instr_i[5:3],
           {9{instr_i[12]}}, 4'b0, ~instr_i[15], OPCODE_JAL};
```

#### Scenario: c.j +0
Given `instr_i[15:0] = 16'hA001` (`101 0_0_00_0_0_0_000_00 01` — c.j with imm=0)
Then `instr_o == 32'h0000006F` (`jal x0, 0`).

#### Scenario: c.jal +0 (RV32-only)
Given `instr_i[15:0] = 16'h2001` (`001 ... 01` — c.jal with imm=0)
Then `instr_o == 32'h000000EF` (`jal x1, 0`).

---

### Requirement: Zca quadrant 1 — c.li

For `instr_i[15:13] = 3'b010` in quadrant 1, the decoder MUST emit
`addi rd, x0, sext(imm)`. Never raises `illegal_instr_o`. Hint
encodings (`rd = 0`) pass through to the main decoder
(ref: ibex_compressed_decoder.sv:344-349):

```
instr_o = {{6{instr_i[12]}}, instr_i[12], instr_i[6:2], 5'b0,
           3'b0, instr_i[11:7], OPCODE_OP_IMM};
```

#### Scenario: c.li x1, 0
Given `instr_i[15:0] = 16'h4081`
Then `instr_o == 32'h00000093` (`addi x1, x0, 0`).

#### Scenario: c.li x2, -1
Given `instr_i[15:0] = 16'h517D` (sign bit set, imm = -1, rd = x2)
Then `instr_o == 32'hFFF00113` (`addi x2, x0, -1`).

---

### Requirement: Zca quadrant 1 — c.lui / c.addi16sp

For `instr_i[15:13] = 3'b011` in quadrant 1, the decoder MUST emit
`lui rd, sext(imm)` *unless* `rd == x2` in which case the encoding is
re-interpreted as `c.addi16sp` and expands to `addi x2, x2, sext(nzimm)`.
The dispatch is done by overwriting `instr_o` after the default
assignment (ref: ibex_compressed_decoder.sv:351-363):

```
// Default — c.lui:
instr_o = {{15{instr_i[12]}}, instr_i[6:2], instr_i[11:7], OPCODE_LUI};

// Overridden when instr_i[11:7] == 5'h02 — c.addi16sp:
instr_o = {{3{instr_i[12]}}, instr_i[4:3], instr_i[5], instr_i[2],
           instr_i[6], 4'b0, 5'h02, 3'b000, 5'h02, OPCODE_OP_IMM};
```

The decoder MUST raise `illegal_instr_o = 1` when
`{instr_i[12], instr_i[6:2]} == 6'b0` (zero immediate is reserved for
both c.lui and c.addi16sp — ref:362).

#### Scenario: c.lui x3, 1
Given `instr_i[15:0] = 16'h6185` (`011 0 00011 00001 01`)
Then `instr_o == 32'h000011B7` (`lui x3, 1`).

#### Scenario: c.addi16sp +16
Given `instr_i[15:0] = 16'h6141` (`011 0 00010 00000 01` with imm encoding for +16)
Then `instr_o == 32'h01010113` (`addi x2, x2, 16`).

#### Scenario: c.lui zero-imm reserved
Given `instr_i[15:0] = 16'h6181` (`011 0 00011 00000 01` — rd = x3, imm=0)
Then `illegal_instr_o == 1'b1`.

---

### Requirement: Zca quadrant 1 — c.srli / c.srai

For `instr_i[15:13] = 3'b100` and `instr_i[11:10] ∈ {2'b00, 2'b01}`
in quadrant 1, the decoder MUST emit `srli rsd', rsd', shamt`
(when `instr_i[10] = 0`) or `srai rsd', rsd', shamt`
(when `instr_i[10] = 1`). Hint encodings (shamt = 0, `rsd' = 0` does
not happen because `rsd'` is from the prime register set) pass through
(ref: ibex_compressed_decoder.sv:367-375):

```
instr_o = {1'b0, instr_i[10], 5'b0, instr_i[6:2], 2'b01, instr_i[9:7],
           3'b101, 2'b01, instr_i[9:7], OPCODE_OP_IMM};
```

The decoder MUST raise `illegal_instr_o = 1` when `instr_i[12] = 1`
(shamt[5] is reserved for RV64 — illegal in RV32 mode — ref:374).

#### Scenario: c.srli x8, x8, 1
Given `instr_i[15:0] = 16'h8005` (`100 0 00 000 00001 01`)
Then `instr_o == 32'h00145413` (`srli x8, x8, 1`).

#### Scenario: c.srai x9, x9, 31
Given `instr_i[15:0] = 16'h84FD` (`100 0 01 001 11111 01`)
Then `instr_o == 32'h41F4D493` (`srai x9, x9, 31`).

#### Scenario: c.srli with shamt[5]=1 reserved
Given `instr_i[15:13] = 3'b100`, `instr_i[12] = 1'b1`, `instr_i[11:10] = 2'b00`, `instr_i[1:0] = 2'b01`
Then `illegal_instr_o == 1'b1`.

---

### Requirement: Zca quadrant 1 — c.andi

For `instr_i[15:13] = 3'b100` and `instr_i[11:10] = 2'b10` in
quadrant 1, the decoder MUST emit `andi rsd', rsd', sext(imm)`
(ref: ibex_compressed_decoder.sv:377-381). Never raises
`illegal_instr_o`:

```
instr_o = {{6{instr_i[12]}}, instr_i[12], instr_i[6:2], 2'b01, instr_i[9:7],
           3'b111, 2'b01, instr_i[9:7], OPCODE_OP_IMM};
```

#### Scenario: c.andi x8, x8, -1
Given `instr_i[15:0] = 16'h987D` (`100 1 10 000 11111 01`)
Then `instr_o == 32'hFFF47413` (`andi x8, x8, -1`).

#### Scenario: c.andi x15, x15, 0
Given `instr_i[15:0] = 16'h8B81` (`100 0 10 111 00000 01`)
Then `instr_o == 32'h0007F793` (`andi x15, x15, 0`).

---

### Requirement: Zca quadrant 1 — c.sub / c.xor / c.or / c.and

For `instr_i[15:13] = 3'b100`, `instr_i[11:10] = 2'b11`, and
`instr_i[12] = 0` in quadrant 1, the decoder MUST emit one of
`sub/xor/or/and rsd', rsd', rs2'` selected by `instr_i[6:5]`
(ref: ibex_compressed_decoder.sv:384-407):

| `{instr_i[12], instr_i[6:5]}` | mnemonic   | funct3 in expansion | funct7 in expansion |
|-------------------------------|------------|---------------------|---------------------|
| `3'b000`                      | c.sub      | `3'b000`            | `7'b0100000`        |
| `3'b001`                      | c.xor      | `3'b100`            | `7'b0000000`        |
| `3'b010`                      | c.or       | `3'b110`            | `7'b0000000`        |
| `3'b011`                      | c.and      | `3'b111`            | `7'b0000000`        |

For `{instr_i[12], instr_i[6:5]} ∈ {3'b100, 3'b101}` (c.subw/c.addw,
RV64-only) the decoder MUST raise `illegal_instr_o = 1`
(ref: ibex_compressed_decoder.sv:409-413).

#### Scenario: c.sub x8, x8, x9
Given `instr_i[15:0] = 16'h8C05` (`100 0 11 000 00 001 01`)
Then `instr_o == 32'h40940433` (`sub x8, x8, x9`).

#### Scenario: c.xor x8, x8, x9
Given `instr_i[15:0] = 16'h8C25` (`100 0 11 000 01 001 01`)
Then `instr_o == 32'h00944433` (`xor x8, x8, x9`).

#### Scenario: c.or x8, x8, x9
Given `instr_i[15:0] = 16'h8C45`
Then `instr_o == 32'h00946433` (`or x8, x8, x9`).

#### Scenario: c.and x8, x8, x9
Given `instr_i[15:0] = 16'h8C65`
Then `instr_o == 32'h00947433` (`and x8, x8, x9`).

#### Scenario: c.subw reserved on RV32
Given `instr_i[15:13] = 3'b100`, `instr_i[12] = 1'b1`, `instr_i[11:10] = 2'b11`, `instr_i[6:5] = 2'b00`, `instr_i[1:0] = 2'b01`
Then `illegal_instr_o == 1'b1`.

---

### Requirement: Zcb quadrant 1 — c.mul

For `{instr_i[12], instr_i[6:5]} == 3'b110` in the q1 funct3=100/funct2=11
sub-quadrant, the decoder MUST emit `mul rsd', rsd', rs2'`
(M-extension multiply, lower 32 bits)
(ref: ibex_compressed_decoder.sv:416-425):

```
instr_o = {7'b0000001, 2'b01, instr_i[4:2], 2'b01, instr_i[9:7],
           3'b000, 2'b01, instr_i[9:7], OPCODE_OP};
```

This expansion only fires when `RV32ZC ∈ {RV32ZcaZcb, RV32ZcaZcbZcmp}`;
otherwise `illegal_instr_o = 1` (ref:421-424). The locked port value
`RV32ZcaZcbZcmp` enables this expansion.

#### Scenario: c.mul x8, x8, x9
Given `instr_i[15:0] = 16'h9C45` (`100 1 11 000 10 001 01`)
Then `instr_o == 32'h02940433` (`mul x8, x8, x9`).

---

### Requirement: Zcb quadrant 1 — zext.b / sext.b / zext.h / sext.h / not

For `{instr_i[12], instr_i[6:5]} == 3'b111` in the q1 funct3=100/funct2=11
sub-quadrant, the decoder dispatches on `instr_i[4:2]`
(ref: ibex_compressed_decoder.sv:427-473):

| `instr_i[4:2]` | mnemonic         | expansion (line) |
|----------------|------------------|------------------|
| `3'b000`       | c.zext.b         | `andi rsd', rsd', 0xff` (432-433) |
| `3'b001`       | c.sext.b         | `sext.b rsd', rsd'` (438-439)     |
| `3'b010`       | c.zext.h         | `zext.h rsd', rsd'` (444-445)     |
| `3'b011`       | c.sext.h         | `sext.h rsd', rsd'` (450-451)     |
| `3'b100`       | c.zext.w (RV64)  | `illegal_instr_o = 1` (456)       |
| `3'b101`       | c.not            | `xori rsd', rsd', -1` (461-462)   |
| `3'b110`,`3'b111` | reserved      | `illegal_instr_o = 1` (465-467)   |

The expansions:
```
// c.zext.b -> andi rsd', rsd', 0xff
instr_o = {4'b0, 8'hff, 2'b01, instr_i[9:7], 3'b111,
           2'b01, instr_i[9:7], OPCODE_OP_IMM};

// c.sext.b -> sext.b rsd', rsd' (Zbb)
instr_o = {7'b0110000, 5'b00100, 2'b01, instr_i[9:7],
           3'b001, 2'b01, instr_i[9:7], OPCODE_OP_IMM};

// c.zext.h -> zext.h rsd', rsd' (Zbb / pack)
instr_o = {7'b0000100, 5'b0, 2'b01, instr_i[9:7],
           3'b100, 2'b01, instr_i[9:7], OPCODE_OP};

// c.sext.h -> sext.h rsd', rsd' (Zbb)
instr_o = {7'b0110000, 5'b00101, 2'b01, instr_i[9:7],
           3'b001, 2'b01, instr_i[9:7], OPCODE_OP_IMM};

// c.not -> xori rsd', rsd', -1
instr_o = {12'hfff, 2'b01, instr_i[9:7], 3'b100,
           2'b01, instr_i[9:7], OPCODE_OP_IMM};
```

Note: Whether the resulting `sext.b`/`sext.h`/`zext.h` is itself a
legal RV32 instruction depends on whether the SoC enables Zbb in the
*main* decoder (via `RV32B`). The compressed decoder unconditionally
emits the expansion; downstream `ibex_decoder` will surface
`illegal_insn_o` if Zbb is not configured.

#### Scenario: c.zext.b x8
Given `instr_i[15:0] = 16'h9C61` (`100 1 11 000 11 000 01`)
Then `instr_o == 32'h0FF47413` (`andi x8, x8, 0xff`).

#### Scenario: c.not x8
Given `instr_i[15:0] = 16'h9C75` (`100 1 11 000 11 101 01`)
Then `instr_o == 32'hFFF44413` (`xori x8, x8, -1`).

#### Scenario: c.zext.w (RV64-only) reserved on RV32
Given `instr_i[15:13] = 3'b100`, `instr_i[12] = 1'b1`, `instr_i[11:10] = 2'b11`, `instr_i[6:5] = 2'b11`, `instr_i[4:2] = 3'b100`, `instr_i[1:0] = 2'b01`
Then `illegal_instr_o == 1'b1`.

---

### Requirement: Zca quadrant 1 — c.beqz / c.bnez

For `instr_i[15:13] ∈ {3'b110, 3'b111}` in quadrant 1, the decoder
MUST emit `beq rs1', x0, sext(imm)` or `bne rs1', x0, sext(imm)`
respectively. The funct3 bit comes from `instr_i[13]` directly
(ref: ibex_compressed_decoder.sv:487-493):

```
instr_o = {{4{instr_i[12]}}, instr_i[6:5], instr_i[2], 5'b0, 2'b01,
           instr_i[9:7], 2'b00, instr_i[13], instr_i[11:10],
           instr_i[4:3], instr_i[12], OPCODE_BRANCH};
```

#### Scenario: c.beqz x8, 0
Given `instr_i[15:0] = 16'hC001`
Then `instr_o == 32'h00040063` (`beq x8, x0, 0`).

#### Scenario: c.bnez x8, +4
Given `instr_i[15:0] = 16'hE111` (encodes `c.bnez x8, +4`)
Then `instr_o == 32'h00041263` (`bne x8, x0, 4`).

---

### Requirement: Zca quadrant 2 — c.slli

For `instr_i[15:13] = 3'b000` in quadrant 2, the decoder MUST emit
`slli rd, rd, shamt`
(ref: ibex_compressed_decoder.sv:508-513):

```
instr_o = {7'b0, instr_i[6:2], instr_i[11:7], 3'b001, instr_i[11:7], OPCODE_OP_IMM};
```

The decoder MUST raise `illegal_instr_o = 1` when `instr_i[12] = 1`
(shamt[5] reserved for custom extensions in RV32 — ref:512).

#### Scenario: c.slli x1, x1, 1
Given `instr_i[15:0] = 16'h0086` (`000 0 00001 00001 10`)
Then `instr_o == 32'h00109093` (`slli x1, x1, 1`).

#### Scenario: c.slli with shamt[5]=1 reserved
Given `instr_i[15:13] = 3'b000`, `instr_i[12] = 1'b1`, `instr_i[1:0] = 2'b10`
Then `illegal_instr_o == 1'b1`.

---

### Requirement: Zca quadrant 2 — c.lwsp

For `instr_i[15:13] = 3'b010` in quadrant 2, the decoder MUST emit
`lw rd, uimm(x2)`
(ref: ibex_compressed_decoder.sv:515-520):

```
instr_o = {4'b0, instr_i[3:2], instr_i[12], instr_i[6:4], 2'b00, 5'h02,
           3'b010, instr_i[11:7], OPCODE_LOAD};
```

The decoder MUST raise `illegal_instr_o = 1` when `instr_i[11:7] == 5'b0`
(`rd = x0` is reserved for c.lwsp — ref:519).

#### Scenario: c.lwsp x1, 0
Given `instr_i[15:0] = 16'h4082`
Then `instr_o == 32'h00012083` (`lw x1, 0(x2)`).

#### Scenario: c.lwsp with rd=x0 reserved
Given `instr_i[15:13] = 3'b010`, `instr_i[11:7] = 5'b0`, `instr_i[1:0] = 2'b10`
Then `illegal_instr_o == 1'b1`.

---

### Requirement: Zca quadrant 2 — c.mv / c.jr / c.add / c.jalr / c.ebreak

For `instr_i[15:13] = 3'b100` in quadrant 2, the dispatch is by
`{instr_i[12], (instr_i[6:2]==0), (instr_i[11:7]==0)}`
(ref: ibex_compressed_decoder.sv:522-548):

| `instr_i[12]` | `instr_i[6:2]` | `instr_i[11:7]` | mnemonic   | expansion (line)                |
|---------------|----------------|-----------------|------------|---------------------------------|
| `0`           | non-zero       | any             | c.mv       | `add rd, x0, rs2` (527)         |
| `0`           | `5'b0`         | non-zero        | c.jr       | `jalr x0, rs1, 0` (530)         |
| `0`           | `5'b0`         | `5'b0`          | reserved   | `illegal_instr_o = 1` (531)     |
| `1`           | non-zero       | any             | c.add      | `add rd, rd, rs2` (537)         |
| `1`           | `5'b0`         | `5'b0`          | c.ebreak   | `instr_o = 32'h0010_0073` (541) |
| `1`           | `5'b0`         | non-zero        | c.jalr     | `jalr x1, rs1, 0` (544)         |

Hint encodings of c.mv (`rd = 0`) and c.add (`rd = 0`) are translated
to `add x0, x0, rs2` / `add x0, x0, rs2`; those are accepted as hints
by the main decoder.

#### Scenario: c.mv x8, x9
Given `instr_i[15:0] = 16'h8426` (`100 0 01000 01001 10`)
Then `instr_o == 32'h00900433` (`add x8, x0, x9`).

#### Scenario: c.jr x1
Given `instr_i[15:0] = 16'h8082` (`100 0 00001 00000 10`)
Then `instr_o == 32'h00008067` (`jalr x0, x1, 0`).

#### Scenario: c.jr x0 reserved
Given `instr_i[15:0] = 16'h8002` (`100 0 00000 00000 10`)
Then `illegal_instr_o == 1'b1`.

#### Scenario: c.add x8, x8, x9
Given `instr_i[15:0] = 16'h9426` (`100 1 01000 01001 10`)
Then `instr_o == 32'h00940433` (`add x8, x8, x9`).

#### Scenario: c.ebreak
Given `instr_i[15:0] = 16'h9002` (`100 1 00000 00000 10`)
Then `instr_o == 32'h00100073` (`ebreak`).

#### Scenario: c.jalr x1
Given `instr_i[15:0] = 16'h9082` (`100 1 00001 00000 10`)
Then `instr_o == 32'h000080E7` (`jalr x1, x1, 0`).

---

### Requirement: Zca quadrant 2 — c.swsp

For `instr_i[15:13] = 3'b110` in quadrant 2, the decoder MUST emit
`sw rs2, uimm(x2)`
(ref: ibex_compressed_decoder.sv:769-773):

```
instr_o = {4'b0, instr_i[8:7], instr_i[12], instr_i[6:2], 5'h02, 3'b010,
           instr_i[11:9], 2'b00, OPCODE_STORE};
```

Never raises `illegal_instr_o`.

#### Scenario: c.swsp x1, 0
Given `instr_i[15:0] = 16'hC006`
Then `instr_o == 32'h00112023` (`sw x1, 0(x2)`).

---

### Requirement: Zca quadrant 2 reserved funct3 codes

For `instr_i[15:13] ∈ {3'b001, 3'b011, 3'b111}` in quadrant 2, the
decoder MUST raise `illegal_instr_o = 1` (these are reserved for
c.fldsp/c.fsdsp/c.lqsp/c.sqsp which Ibex does not implement)
(ref: ibex_compressed_decoder.sv:775-779).

#### Scenario: reserved q2 funct3=011
Given `instr_i[15:13] = 3'b011`, `instr_i[1:0] = 2'b10`
Then `illegal_instr_o == 1'b1`.

---

### Requirement: Zcmp — cm.push multi-cycle expansion

For `instr_i[15:13] = 3'b101` and `instr_i[12:8] = 5'b11000` in
quadrant 2, the decoder MUST treat the encoding as `cm.push {rlist},
-stack_adj` and step through a multi-cycle expansion using its
internal Zcmp FSM. The expansion emits a sequence of `sw rN, off(x2)`
for each register in `rlist` (highest first, working downward) and
finishes with one `addi x2, x2, -stack_adj`. The protocol is:

- The decoder MUST drive `gets_expanded_o = INSTR_EXPANDED` for
  every sub-step except the final `addi` which MUST drive
  `gets_expanded_o = INSTR_EXPANDED_LAST`
  (ref: ibex_compressed_decoder.sv:556, 608).
- The decoder MUST advance `cm_state_d` only when `id_in_ready_i = 1`
  (and additionally `valid_i = 1` on the very first sub-step out of
  `CmIdle`)
  (ref: ibex_compressed_decoder.sv:571, 583, 591, 606).
- The IF-stage producer MUST hold `instr_i` stable across all
  sub-steps until `gets_expanded_o == INSTR_EXPANDED_LAST` and
  `id_in_ready_i = 1`.
- `rlist` is decoded from `instr_i[7:4]` via `cm_rlist_init`:
  the four-bit value is widened to 5 bits; the special value `4'd15`
  is internally promoted to `5'd16` because rlist=15 means
  `{ra, s0..s11, s11+1=x26, x27}` (ref: ibex_compressed_decoder.sv:165-174).
- Each store is `sw rN, off(x2)` where `rN = cm_rlist_top_reg(rlist)`
  selects the top of the current rlist and `off = -sp_offset*4` (a
  negative byte offset) (ref: ibex_compressed_decoder.sv:79-95).
- `rlist` values `0..3` are reserved → `illegal_instr_o = 1`
  (ref: ibex_compressed_decoder.sv:565-568).
- The final `addi` immediate is `-cm_stack_adj(rlist, spimm)` where
  `cm_stack_adj_base(rlist) ∈ {16, 32, 48, 64}` for rlist∈{4..7,
  8..11, 12..14, 15} and `spimm = instr_i[3:2]` adds `spimm*16`
  (ref: ibex_compressed_decoder.sv:42-55, 108-125, 605).

FSM trajectory for `rlist >= 5`:
```
CmIdle (sub-step 1: store top reg at off=-4)
  -> CmPushStoreReg (sub-steps 2..N: store next regs at off=-8, -12, ...)
  -> CmPushDecrSp   (final sub-step: addi x2, x2, -stack_adj)
  -> CmIdle (gets_expanded_o asserts INSTR_EXPANDED_LAST in this cycle).
```

For `rlist == 5'd4` (only `ra` to push), CmIdle goes directly to
CmPushDecrSp (single store, single addi).

#### Scenario: cm.push {ra}, -16 first sub-step
Given `instr_i[15:0] = 16'hB842` (cm.push: `101 11000 0100 00 10`, rlist=4 → ra only, spimm=0)
And `cm_state_q = CmIdle`, `valid_i = 1`, `id_in_ready_i = 1`
When evaluated
Then `instr_o == 32'hFE112E23` (`sw x1, -4(x2)`)
And `gets_expanded_o == INSTR_EXPANDED`
And `illegal_instr_o == 1'b0`
And `cm_state_d == CmPushDecrSp`.

#### Scenario: cm.push {ra}, -16 final sub-step
Given `instr_i[15:0] = 16'hB842`, `cm_state_q = CmPushDecrSp`, `valid_i = 1`, `id_in_ready_i = 1`
When evaluated
Then `instr_o == 32'hFF010113` (`addi x2, x2, -16`)
And `gets_expanded_o == INSTR_EXPANDED_LAST`
And `cm_state_d == CmIdle`.

#### Scenario: cm.push reserved rlist=2
Given `instr_i[15:13] = 3'b101`, `instr_i[12:8] = 5'b11000`, `instr_i[7:4] = 4'b0010`, `instr_i[1:0] = 2'b10`
And `cm_state_q = CmIdle`
Then `illegal_instr_o == 1'b1`.

---

### Requirement: Zcmp — cm.pop / cm.popret / cm.popretz multi-cycle expansion

For `instr_i[15:13] = 3'b101` and `instr_i[12:8] ∈ {5'b11010 (cm.pop),
5'b11100 (cm.popretz), 5'b11110 (cm.popret)}` in quadrant 2, the
decoder MUST emit a sequence of `lw rN, off(x2)` (lowest-to-highest
register in `rlist`), then `addi x2, x2, +stack_adj`, then optionally
clear `a0` (cm.popretz only), then optionally `jalr x0, x1, 0`
(cm.popret/popretz)
(ref: ibex_compressed_decoder.sv:617-700).

FSM trajectory:
```
CmIdle (load top reg at off = stack_adj_word - 1)
  -> CmPopLoadReg (load remaining regs, decrementing offset)
  -> CmPopIncrSp  (addi x2, x2, +stack_adj)
  -> [if cm.pop]    INSTR_EXPANDED_LAST -> CmIdle
  -> [if cm.popretz] CmPopZeroA0 (addi a0, x0, 0) -> CmPopRetRa
  -> [if cm.popret]  CmPopRetRa (jalr x0, x1, 0) -> INSTR_EXPANDED_LAST -> CmIdle
```

`gets_expanded_o = INSTR_EXPANDED` for every non-final sub-step;
`INSTR_EXPANDED_LAST` is asserted on the cycle whose `id_in_ready_i`
also returns the FSM to CmIdle (ref:679-680, 695-696).

`rlist` decoding and illegal sub-cases match cm.push: rlist∈{0..3}
yields `illegal_instr_o = 1` (ref: ibex_compressed_decoder.sv:633-635).

The cm.popretz `CmPopZeroA0` step emits `addi a0, x0, 0` via
`cm_zero_a0()` (ref: ibex_compressed_decoder.sv:137-139, 686). The
`CmPopRetRa` step emits `jalr x0, x1, 0` via `cm_ret_ra()`
(ref: ibex_compressed_decoder.sv:141-149, 692).

#### Scenario: cm.pop {ra}, +16 first sub-step
Given `instr_i[15:0] = 16'hBA42` (cm.pop: `101 11010 0100 00 10`, rlist=4, spimm=0)
And `cm_state_q = CmIdle`, `valid_i = 1`, `id_in_ready_i = 1`
Then `instr_o == 32'h00C12083` (`lw x1, 12(x2)`) — sp_offset = stack_adj_word(4,0) - 1 = 4 - 1 = 3, so off = 12.
And `gets_expanded_o == INSTR_EXPANDED`
And `cm_state_d == CmPopIncrSp`.

#### Scenario: cm.popret final sub-step
Given `instr_i[15:0] = 16'hBE42` (cm.popret rlist=4)
And `cm_state_q = CmPopRetRa`, `valid_i = 1`, `id_in_ready_i = 1`
Then `instr_o == 32'h00008067` (`jalr x0, x1, 0`)
And `gets_expanded_o == INSTR_EXPANDED_LAST`
And `cm_state_d == CmIdle`.

#### Scenario: cm.popretz a0 zeroing sub-step
Given `instr_i[15:0] = 16'hBC42` (cm.popretz rlist=4)
And `cm_state_q = CmPopZeroA0`, `valid_i = 1`, `id_in_ready_i = 1`
Then `instr_o == 32'h00000513` (`addi a0, x0, 0`)
And `gets_expanded_o == INSTR_EXPANDED`
And `cm_state_d == CmPopRetRa`.

---

### Requirement: Zcmp — cm.mvsa01 / cm.mva01s

For `instr_i[15:13] = 3'b101` and `instr_i[12:10] = 3'b011` in
quadrant 2, the decoder MUST dispatch on `instr_i[6:5]`:

| `instr_i[6:5]` | mnemonic    | step 1 emits          | step 2 emits          |
|----------------|-------------|-----------------------|-----------------------|
| `2'b01`        | cm.mvsa01   | `addi r1s', a0, 0`    | `addi r2s', a1, 0`    |
| `2'b11`        | cm.mva01s   | `addi a0, r1s', 0`    | `addi a1, r2s', 0`    |
| `2'b00`,`2'b10`| reserved    | `illegal_instr_o = 1` | -                     |

(ref: ibex_compressed_decoder.sv:704-758).

`r1s'` and `r2s'` are 3-bit fields from `instr_i[9:7]` and `instr_i[4:2]`
respectively, mapped via `cm_mvsa01`/`cm_mva01s` to specific
{x8..x9, x18..x25} encodings (ref: ibex_compressed_decoder.sv:151-163):

```
dst = {(rs[2:1] > 2'd0), (rs[2:1] == 2'd0), rs[2:0]}
```

Both instructions step `CmIdle -> CmMvSecondReg -> CmIdle`.
`gets_expanded_o = INSTR_EXPANDED` on step 1, `INSTR_EXPANDED_LAST`
on step 2 (ref:709, 724, 735, 750).

#### Scenario: cm.mvsa01 step 1 (mvsa01 a0->s0)
Given `instr_i[15:0] = 16'hAC22` (`101 011 000 01 000 10`: r1s'=000→s0/x8, r2s'=000→s0/x8)
And `cm_state_q = CmIdle`, `valid_i = 1`, `id_in_ready_i = 1`
Then `instr_o == 32'h00050413` (`addi x8, x10, 0`)
And `gets_expanded_o == INSTR_EXPANDED`
And `cm_state_d == CmMvSecondReg`.

#### Scenario: cm.mva01s step 2
Given `instr_i[15:0] = 16'hAC62` (cm.mva01s, r1s'=000→x8, r2s'=000→x8)
And `cm_state_q = CmMvSecondReg`, `valid_i = 1`, `id_in_ready_i = 1`
Then `instr_o == 32'h00040593` (`addi x11, x8, 0`)
And `gets_expanded_o == INSTR_EXPANDED_LAST`
And `cm_state_d == CmIdle`.

#### Scenario: Zcmp 011 sub-quadrant reserved
Given `instr_i[15:13] = 3'b101`, `instr_i[12:10] = 3'b011`, `instr_i[6:5] = 2'b00`, `instr_i[1:0] = 2'b10`
Then `illegal_instr_o == 1'b1`.

---

### Requirement: Zcmp default reserved encodings

For `instr_i[15:13] = 3'b101` in quadrant 2 and `instr_i[12:8]` not
matching any of `5'b011??`, `5'b11000`, `5'b11010`, `5'b11100`,
`5'b11110`, the decoder MUST raise `illegal_instr_o = 1`
(ref: ibex_compressed_decoder.sv:761).

#### Scenario: Zcmp unmapped funct5
Given `instr_i[15:13] = 3'b101`, `instr_i[12:8] = 5'b00000`, `instr_i[1:0] = 2'b10`
Then `illegal_instr_o == 1'b1`.

---

### Requirement: `is_compressed_o` is a pure LSB decode

The decoder MUST drive `is_compressed_o = (instr_i[1:0] != 2'b11)`
unconditionally — independent of `valid_i`, `illegal_instr_o`, the
Zcmp FSM, or any other input
(ref: ibex_compressed_decoder.sv:796).

#### Scenario: compressed bit set
Given `instr_i[1:0] = 2'b00`
Then `is_compressed_o == 1'b1`.

#### Scenario: compressed bit clear
Given `instr_i[1:0] = 2'b11`
Then `is_compressed_o == 1'b0`.

---

### Requirement: `gets_expanded_o` gating on `valid_i`

When `RV32ZC ∈ {RV32ZcaZcmp, RV32ZcaZcbZcmp}` (Zcmp enabled), the
decoder MUST drive `gets_expanded_o = INSTR_NOT_EXPANDED` whenever
`valid_i = 0`, regardless of what the internal FSM produces. When
Zcmp is disabled, `gets_expanded_o` is tied to `INSTR_NOT_EXPANDED`
unconditionally (ref: ibex_compressed_decoder.sv:200-205).

The locked port value `RV32ZC = RV32ZcaZcbZcmp` requires the gated
behaviour. The intent (per the source comment) is *"to ensure that an
invalid instruction looking like an expandable cm.* instruction will
not be stalled/blocked in later control logic because it is waiting
for INSTR_EXPANDED_LAST"*.

#### Scenario: spurious cm.push pattern with valid_i=0
Given `instr_i[15:0] = 16'hB842` (looks like cm.push), `cm_state_q = CmPushStoreReg`, `valid_i = 1'b0`
Then `gets_expanded_o == INSTR_NOT_EXPANDED`.

#### Scenario: cm.push with valid_i=1
Given `instr_i[15:0] = 16'hB842`, `cm_state_q = CmIdle`, `valid_i = 1'b1`
Then `gets_expanded_o == INSTR_EXPANDED`.

---

### Requirement: Zcmp FSM stability when `valid_i = 0`

The decoder MUST hold `cm_state_d == cm_state_q` whenever
`valid_i = 0` (no register-level state advance unless a valid input
is being processed). This is enforced via the `IbexPushPopFSMStable`
SVA in upstream and is implicit in the FSM advance conditions which
all gate on `valid_i && id_in_ready_i` (out of CmIdle) or on
`id_in_ready_i` (during sub-steps where `valid_i` is assumed)
(ref: ibex_compressed_decoder.sv:571, 583, 639, 648, 715, 741, 845).

Note: in non-CmIdle states the upstream code does NOT explicitly gate
the `id_in_ready_i` advance on `valid_i`. It relies on the producer
contract that `valid_i` will remain 1 across an active Zcmp expansion
because the IF stage holds the same compressed encoding stable. The
ARCH port MAY mirror this assumption (gating only on `id_in_ready_i`
in non-idle states) so long as it preserves the SVA's intent that no
state update happens with `!valid_i`. See **Integration constraints
→ Producer-side**.

#### Scenario: FSM frozen with valid_i=0
Given `cm_state_q = CmPushStoreReg`, `valid_i = 1'b0`, `id_in_ready_i = 1'b1`
Then `cm_state_d == cm_state_q` (FSM does not advance).

---

### Requirement: Pure pass-through when `instr_i[1:0]` is unknown / any

For `instr_i[1:0] == 2'b11` the default arm is empty (`2'b11:;`)
which means `instr_o = instr_i`, `illegal_instr_o = 0`,
`gets_expanded = INSTR_NOT_EXPANDED` from the defaults at the top
of the always_comb block (ref: ibex_compressed_decoder.sv:212-215, 788).

The `default:` arm of the outer case (which is unreachable in 2-state
simulation since `instr_i[1:0]` is 2 bits, but covers X-propagation in
4-state) drives `illegal_instr_o = 1` (ref:790-792). The ARCH port
need not implement X-propagation behaviour; the producer guarantees
known LSBs (see Integration constraints).

---

## Integration constraints

### Consumer-side (output constraints)

**Sink: `ibex_if_stage` (lines 414-427) → IF→ID pipeline registers (lines 528-554) → `ibex_id_stage` (port `instr_rdata_i`) → `ibex_decoder` (port `instr_rdata_i` and `illegal_c_insn_i`).**

The four outputs flow into the IF stage as follows:

- **`instr_o` → `instr_decompressed`** (ref: ibex_if_stage.sv:423). When
  `DummyInstructions=1` (not in our scope at this stage; the SoC
  configures `DummyInstructions` separately) the IF stage muxes
  `instr_decompressed` against a dummy via
  `instr_out = insert_dummy_instr ? dummy_instr_data : instr_decompressed`
  (ref: ibex_if_stage.sv:452). `instr_out` is then registered into
  `instr_rdata_id_o` on `if_id_pipe_reg_we` (ref: ibex_if_stage.sv:529, 545).
  The IF stage applies **no mask, no OR-combine, no constraint** on
  the value of `instr_o` itself when not gated by `insert_dummy_instr`.
  The downstream `ibex_decoder` re-decodes the full 32 bits and is
  responsible for raising its own illegal-instruction signal if the
  expansion happens to be malformed (e.g. when `illegal_instr_o = 1`
  causes `instr_o` to be an arbitrary value)
  (ref: ibex_decoder.sv:649-651).

- **`is_compressed_o` → `instr_is_compressed`** (ref: ibex_if_stage.sv:424).
  The IF stage uses this signal locally for PC-increment selection
  (`pc_id + (instr_is_compressed ? 2 : 4)`, ref: ibex_id_stage.sv:343,
  354, 382, 756; ibex_if_stage.sv:580, 764) and for PMP-error
  selection on misaligned fetches (ref: ibex_if_stage.sv:400, 406).
  No mask or override is applied between decoder and consumer (other
  than the `insert_dummy_instr` mux when dummies are enabled, which
  forces the bit to 0 — ref: ibex_if_stage.sv:453).

- **`gets_expanded_o` → `instr_gets_expanded`** (ref: ibex_if_stage.sv:425).
  The IF stage uses this signal to suppress the IF→ID pipeline
  write-enable while the FSM is mid-expansion: the pipeline-register
  write-enable contains `!(instr_gets_expanded == INSTR_EXPANDED)`
  (ref: ibex_if_stage.sv:570, 633, 692, 708). This means the
  consumer requires `gets_expanded_o` to be a *clean* enum value —
  in particular, the producer-side comment about gating to
  `INSTR_NOT_EXPANDED` on `!valid_i` is load-bearing because
  otherwise a phantom `INSTR_EXPANDED` would lock up the IF/ID
  pipeline. ARCH port MUST honor that gating.

- **`illegal_instr_o` → `illegal_c_insn`** (ref: ibex_if_stage.sv:426).
  The IF stage muxes against dummy (ref: ibex_if_stage.sv:455:
  `illegal_c_instr_out = insert_dummy_instr ? 1'b0 : illegal_c_insn`),
  registers into `illegal_c_insn_id_o` (ref: ibex_if_stage.sv:538, 554),
  and the main decoder ORs it into `illegal_insn`:
  *"if (illegal_c_insn_i) illegal_insn = 1'b1"*
  (ref: ibex_decoder.sv:649-651). Therefore: when
  `illegal_instr_o = 1`, the value of `instr_o` is don't-care — the
  consumer's final illegal-instruction signal is taken from the OR
  of `illegal_c_insn_i` and the decoder's own legality check. **The
  ARCH port may emit any value on `instr_o` while `illegal_instr_o = 1`.**

### Producer-side (input guarantees)

**Source: `ibex_if_stage.sv:414-427` (the instantiation site).**

- **`valid_i = fetch_valid & ~fetch_err`** (ref: ibex_if_stage.sv:420).
  - `fetch_valid` is itself `fetch_valid_raw & ~nt_branch_mispredict_i`
    (ref: ibex_if_stage.sv:267) — i.e. the prefetch buffer / icache
    has produced a valid instruction word and there is no
    nt-branch-mispredict squash. With `BranchPredictor=0` (typical
    for our scope), `fetch_valid` simply tracks the prefetch
    buffer's `valid_o`.
  - `fetch_err` is `1` when the prefetch buffer reports a bus error
    on this fetch (ref: ibex_if_stage.sv:148, 295, 340, 686). When
    `fetch_err=1`, the IF stage forces `valid_i = 0` going to the
    decoder so that `instr_i` is not decoded — the IF stage will
    instead inject a synthetic illegal/error path.
  - **Guarantee for the decoder**: when `valid_i = 0`, the value of
    `instr_i` is don't-care for any of the *decoder's outputs that
    are registered downstream* (`instr_o`, `illegal_instr_o`,
    `gets_expanded_o`). However, the decoder MUST NOT update
    `cm_state_q` on `!valid_i` (matches the upstream
    `IbexPushPopFSMStable` SVA at line 845) and MUST drive
    `gets_expanded_o = INSTR_NOT_EXPANDED` on `!valid_i` (per the
    `gen_gets_expanded` mux at line 200-205).
  - `is_compressed_o` is *not* gated on `valid_i` and may take any
    value (it is a pure LSB decode); IF-stage logic that reads
    `instr_is_compressed` is itself qualified by upstream valid
    tracking, so this is acceptable.

- **`id_in_ready_i = id_in_ready_i & ~pc_set_i`** (ref: ibex_if_stage.sv:421).
  - Reflects "the ID stage will accept an instruction this cycle and
    we are not branching". When `pc_set_i=1`, `id_in_ready_i` is
    forced to 0 so the Zcmp FSM does not advance during a branch
    flush.
  - **Guarantee for the decoder**: when `id_in_ready_i = 0`, the
    decoder MUST hold `cm_state_d = cm_state_q` (no FSM advance).
    `valid_i` and `id_in_ready_i` are independent — both can be high
    or low in any combination.

- **`instr_i = if_instr_rdata`** (ref: ibex_if_stage.sv:422).
  - `if_instr_rdata` is the 32-bit fetch word from either the
    prefetch buffer or (with `BranchPredictor=1`) the skid buffer
    (ref: ibex_if_stage.sv:683, 704). It is meaningful only when
    `valid_i = 1`.
  - **LSB validity**: when `valid_i = 1`, the SVA
    `IbexInstrLSBsKnown` (ref: ibex_compressed_decoder.sv:832-833)
    asserts `instr_i[1:0]` is known (not X). The producer therefore
    *guarantees* known LSBs whenever it raises `valid_i`. The ARCH
    port may rely on this — it does not need to handle the SV
    "default" arm of the outer case.
  - **Stability across Zcmp sub-steps**: the IF-stage write-enable
    `if_id_pipe_reg_we` is held low while
    `instr_gets_expanded == INSTR_EXPANDED`
    (ref: ibex_if_stage.sv:570, 633, 692, 708). This implies the
    same `instr_i` is presented across every sub-step of a Zcmp
    expansion until the decoder asserts `INSTR_EXPANDED_LAST`. The
    ARCH port may rely on this — `instr_i[7:4]` (rlist),
    `instr_i[3:2]` (spimm), `instr_i[12:8]` (funct5),
    `instr_i[9:7]` (r1s'), and `instr_i[4:2]` (r2s') stay stable
    across the FSM trajectory.
  - **Mutual exclusion with `fetch_err`**: when the SoC reports a
    bus/PMP error on the fetched word, the producer drives
    `valid_i = 0` (ref: line 420). The decoder does not see the
    error directly; it sees only that `valid_i` is low.

- **`clk_i` / `rst_ni`**: standard module clock and async-low reset.
  Used only for the Zcmp FSM register and SVA. No producer-side
  invariants apply beyond the standard reset deassertion contract.

## Notes

- The module exports `clk_i` and `rst_ni` even when `RV32ZC = RV32Zca`,
  in which case the FSM is inactive but the registers still exist. For
  the ARCH port (locked to `RV32ZcaZcbZcmp`), the FSM is always live.

- `unused_valid` / `unused_id_in_ready` lint sinks (lines 32-40) only
  exist for the parameter combinations that don't enable Zcmp. Since
  the ARCH port locks `RV32ZC = RV32ZcaZcbZcmp`, these sinks do not
  apply.

- The SVAs at lines 829-845 are non-functional; the ARCH port may
  emit equivalent assertions or skip them (the spec keeps their
  intent in the Requirements above):
  - `IbexInstrValidKnown` — `valid_i` is never X (handled by producer).
  - `IbexInstrLSBsKnown` / `IbexC0Known1` / `IbexC1Known1..3` /
    `IbexC2Known1` — selectors are not X when `valid_i = 1`.
  - `IbexPushPopFSMStable` — already captured by the FSM stability
    Requirement above.

- Hint encodings (e.g. `c.li x0, *`, `c.lui x0, *`, `c.mv x0, *`,
  `c.add x0, *`, `c.slli x0, *`, `c.srli x0, *`) are not given
  special handling: the decoder expands them mechanically and the
  result becomes a hint at the main-decoder level. None of these
  paths set `illegal_instr_o`. The ARCH port MUST replicate this
  permissive treatment (do not coerce hints to `illegal_instr_o = 1`).

- The cm.popretz `addi a0, x0, 0` step is *intentionally* emitted
  even though the trailing `jalr` makes a0's pre-return value
  irrelevant in normal code; this is a Zcmp-spec-compliant expansion.

- The `cm_rlist_init` promotion of `4'd15 → 5'd16` is internal-only:
  `instr_i[7:4]` remains 4 bits in the encoding; `cm_rlist_top_reg`
  uses the 5-bit form to disambiguate `x26+x27` from `s11`
  (ref: ibex_compressed_decoder.sv:66-77).

- The `cm_stack_adj_word` helper computes the *word* offset for the
  topmost pop's load address. With `rlist=4` (`stack_adj_base=16`)
  and `spimm=0`, it returns `16/4 - 1 = 3`, so the first cm.pop load
  in the example scenarios is `lw x1, 12(x2)`
  (ref: ibex_compressed_decoder.sv:57-64, 628-629).
