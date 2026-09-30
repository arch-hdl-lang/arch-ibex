# Compressed-decoder HARC coverage inventory

This is a requirements-derived migration plan, not measured coverage. It
restores the inventory referenced by the runner test; it is not a recovered
historical artifact. No compressed-decoder HARC VIP or unit suite is currently
checked in. The existing Python/cocotb scenarios provide stimulus references,
not evidence that HARC bins have been hit.

Sources:

- [Specification](../../../specs/compressed_decoder/spec.md)
- [Existing full cocotb suite](../../cocotb_tests/test_ibex_compressed_decoder_unit_full.py)
- [Existing unit cocotb suite](../../cocotb_tests/test_ibex_compressed_decoder_unit.py)

Scope follows the specification's fixed RV32ZcaZcbZcmp / ResetAll=0
configuration. Each specification Requirement has a coverpoint below; each
named Scenario has a bin. This inventory is a starting coverage contract,
not proof that those scenarios exhaust every encoding or temporal behavior.
Implementing the HARC suite must refine it against the DUT and reference model,
including hint encodings, exhaustive reserved selectors, register/immediate
boundaries, reset during expansion, and backpressure sequences.

A scenario bin may be credited only after its inputs, timing conditions, and
expected outputs have been checked. Illegal-instruction scenarios check the
illegal flag and defined outputs, not don't-care instr_o bits. Protocol points
sample the driven input and reference-model expansion phase, before valid_i
masks gets_expanded_o. Do not use an opcode observation alone to claim a
scenario bin. The unknown-input requirement needs a separate decision about
four-state observability; it is not silently waived on a two-state simulator.

## Coverpoints and Bins

### `cp_32_bit_pass_through`

32-bit pass-through

- `pass_through_addi` — Scenario: pass through addi
- `pass_through_ebreak` — Scenario: pass through ebreak

### `cp_zca_quadrant_0_c_addi4spn`

Zca quadrant 0 — c.addi4spn

- `c_addi4spn_x8_sp_4` — Scenario: c.addi4spn x8, sp, 4
- `c_addi4spn_reserved_zero_immediate` — Scenario: c.addi4spn reserved (zero immediate)

### `cp_zca_quadrant_0_c_lw`

Zca quadrant 0 — c.lw

- `c_lw_x8_0_x9` — Scenario: c.lw x8, 0(x9)
- `c_lw_x15_124_x14_max_immediate` — Scenario: c.lw x15, 124(x14) (max immediate)

### `cp_zca_quadrant_0_c_sw`

Zca quadrant 0 — c.sw

- `c_sw_x8_0_x9` — Scenario: c.sw x8, 0(x9)
- `c_sw_x15_4_x14` — Scenario: c.sw x15, 4(x14)

### `cp_zcb_quadrant_0_c_lbu_c_lh_c_lhu_c_sb_c_sh`

Zcb quadrant 0 — c.lbu / c.lh / c.lhu / c.sb / c.sh

- `c_lbu_x8_0_x9` — Scenario: c.lbu x8, 0(x9)
- `c_lh_x8_2_x9` — Scenario: c.lh x8, 2(x9)
- `c_sh_with_reserved_instr_i_6_1` — Scenario: c.sh with reserved instr_i[6]=1
- `reserved_q0_funct3_100_instr_i_12_10_110` — Scenario: Reserved q0/funct3=100, instr_i[12:10]=110

### `cp_zca_quadrant_0_reserved_funct3_codes`

Zca quadrant 0 reserved funct3 codes

- `reserved_funct3_001` — Scenario: reserved funct3=001
- `reserved_funct3_111` — Scenario: reserved funct3=111

### `cp_zca_quadrant_1_c_addi_c_nop`

Zca quadrant 1 — c.addi / c.nop

- `c_nop` — Scenario: c.nop
- `c_addi_x1_x1_1` — Scenario: c.addi x1, x1, -1

### `cp_zca_quadrant_1_c_jal_c_j`

Zca quadrant 1 — c.jal / c.j

- `c_j_0` — Scenario: c.j +0
- `c_jal_0_rv32_only` — Scenario: c.jal +0 (RV32-only)

### `cp_zca_quadrant_1_c_li`

Zca quadrant 1 — c.li

- `c_li_x1_0` — Scenario: c.li x1, 0
- `c_li_x2_1` — Scenario: c.li x2, -1

### `cp_zca_quadrant_1_c_lui_c_addi16sp`

Zca quadrant 1 — c.lui / c.addi16sp

- `c_lui_x3_1` — Scenario: c.lui x3, 1
- `c_addi16sp_16` — Scenario: c.addi16sp +16
- `c_lui_zero_imm_reserved` — Scenario: c.lui zero-imm reserved

### `cp_zca_quadrant_1_c_srli_c_srai`

Zca quadrant 1 — c.srli / c.srai

- `c_srli_x8_x8_1` — Scenario: c.srli x8, x8, 1
- `c_srai_x9_x9_31` — Scenario: c.srai x9, x9, 31
- `c_srli_with_shamt_5_1_reserved` — Scenario: c.srli with shamt[5]=1 reserved

### `cp_zca_quadrant_1_c_andi`

Zca quadrant 1 — c.andi

- `c_andi_x8_x8_1` — Scenario: c.andi x8, x8, -1
- `c_andi_x15_x15_0` — Scenario: c.andi x15, x15, 0

### `cp_zca_quadrant_1_c_sub_c_xor_c_or_c_and`

Zca quadrant 1 — c.sub / c.xor / c.or / c.and

- `c_sub_x8_x8_x9` — Scenario: c.sub x8, x8, x9
- `c_xor_x8_x8_x9` — Scenario: c.xor x8, x8, x9
- `c_or_x8_x8_x9` — Scenario: c.or x8, x8, x9
- `c_and_x8_x8_x9` — Scenario: c.and x8, x8, x9
- `c_subw_reserved_on_rv32` — Scenario: c.subw reserved on RV32

### `cp_zcb_quadrant_1_c_mul`

Zcb quadrant 1 — c.mul

- `c_mul_x8_x8_x9` — Scenario: c.mul x8, x8, x9

### `cp_zcb_quadrant_1_zext_b_sext_b_zext_h_sext_h_not`

Zcb quadrant 1 — zext.b / sext.b / zext.h / sext.h / not

- `c_zext_b_x8` — Scenario: c.zext.b x8
- `c_not_x8` — Scenario: c.not x8
- `c_zext_w_rv64_only_reserved_on_rv32` — Scenario: c.zext.w (RV64-only) reserved on RV32

### `cp_zca_quadrant_1_c_beqz_c_bnez`

Zca quadrant 1 — c.beqz / c.bnez

- `c_beqz_x8_0` — Scenario: c.beqz x8, 0
- `c_bnez_x8_4` — Scenario: c.bnez x8, +4

### `cp_zca_quadrant_2_c_slli`

Zca quadrant 2 — c.slli

- `c_slli_x1_x1_1` — Scenario: c.slli x1, x1, 1
- `c_slli_with_shamt_5_1_reserved` — Scenario: c.slli with shamt[5]=1 reserved

### `cp_zca_quadrant_2_c_lwsp`

Zca quadrant 2 — c.lwsp

- `c_lwsp_x1_0` — Scenario: c.lwsp x1, 0
- `c_lwsp_with_rd_x0_reserved` — Scenario: c.lwsp with rd=x0 reserved

### `cp_zca_quadrant_2_c_mv_c_jr_c_add_c_jalr_c_ebreak`

Zca quadrant 2 — c.mv / c.jr / c.add / c.jalr / c.ebreak

- `c_mv_x8_x9` — Scenario: c.mv x8, x9
- `c_jr_x1` — Scenario: c.jr x1
- `c_jr_x0_reserved` — Scenario: c.jr x0 reserved
- `c_add_x8_x8_x9` — Scenario: c.add x8, x8, x9
- `c_ebreak` — Scenario: c.ebreak
- `c_jalr_x1` — Scenario: c.jalr x1

### `cp_zca_quadrant_2_c_swsp`

Zca quadrant 2 — c.swsp

- `c_swsp_x1_0` — Scenario: c.swsp x1, 0

### `cp_zca_quadrant_2_reserved_funct3_codes`

Zca quadrant 2 reserved funct3 codes

- `reserved_q2_funct3_011` — Scenario: reserved q2 funct3=011

### `cp_zcmp_cm_push_multi_cycle_expansion`

Zcmp — cm.push multi-cycle expansion

- `cm_push_ra_16_first_sub_step` — Scenario: cm.push {ra}, -16 first sub-step
- `cm_push_ra_16_final_sub_step` — Scenario: cm.push {ra}, -16 final sub-step
- `cm_push_reserved_rlist_2` — Scenario: cm.push reserved rlist=2

### `cp_zcmp_cm_pop_cm_popret_cm_popretz_multi_cycle_expansion`

Zcmp — cm.pop / cm.popret / cm.popretz multi-cycle expansion

- `cm_pop_ra_16_first_sub_step` — Scenario: cm.pop {ra}, +16 first sub-step
- `cm_popret_final_sub_step` — Scenario: cm.popret final sub-step
- `cm_popretz_a0_zeroing_sub_step` — Scenario: cm.popretz a0 zeroing sub-step

### `cp_zcmp_cm_mvsa01_cm_mva01s`

Zcmp — cm.mvsa01 / cm.mva01s

- `cm_mvsa01_step_1_mvsa01_a0_s0` — Scenario: cm.mvsa01 step 1 (mvsa01 a0->s0)
- `cm_mva01s_step_2` — Scenario: cm.mva01s step 2
- `zcmp_011_sub_quadrant_reserved` — Scenario: Zcmp 011 sub-quadrant reserved

### `cp_zcmp_default_reserved_encodings`

Zcmp default reserved encodings

- `zcmp_unmapped_funct5` — Scenario: Zcmp unmapped funct5

### `cp_is_compressed_o_is_a_pure_lsb_decode`

`is_compressed_o` is a pure LSB decode

- `compressed_bit_set` — Scenario: compressed bit set
- `compressed_bit_clear` — Scenario: compressed bit clear

### `cp_gets_expanded_o_gating_on_valid_i`

`gets_expanded_o` gating on `valid_i`

- `spurious_cm_push_pattern_with_valid_i_0` — Scenario: spurious cm.push pattern with valid_i=0
- `cm_push_with_valid_i_1` — Scenario: cm.push with valid_i=1

### `cp_zcmp_fsm_stability_when_valid_i_0`

Zcmp FSM stability when `valid_i = 0`

- `fsm_frozen_with_valid_i_0` — Scenario: FSM frozen with valid_i=0

### `cp_pure_pass_through_when_instr_i_1_0_is_unknown_any`

Pure pass-through when `instr_i[1:0]` is unknown / any

- `specified_behavior` — Requirement: Pure pass-through when instr_i[1:0] is unknown / any

### `cp_decode_path`

Input instruction classification

- `quadrant_0` — quadrant_0
- `quadrant_1` — quadrant_1
- `quadrant_2` — quadrant_2
- `rv32_passthrough` — rv32_passthrough

### `cp_valid`

valid_i sampled with the input

- `low` — valid_i = 0
- `high` — valid_i = 1

### `cp_ready`

id_in_ready_i sampled with the input

- `low` — id_in_ready_i = 0
- `high` — id_in_ready_i = 1

### `cp_zcmp_phase`

Position in a checked Zcmp expansion sequence

- `idle` — No active multi-instruction expansion
- `intermediate` — Non-final expansion step
- `final` — Final expansion step

### `cp_zcmp_rlist`

Encoded instr_i[7:4] for push/pop families

- `reserved_0_to_3` — rlist 0..3
- `minimum_4` — rlist 4
- `middle_5_to_14` — rlist 5..14; enumerate all values in stimulus
- `maximum_15` — rlist 15, including internal promotion to 16

### `cp_zcmp_spimm`

Encoded stack adjustment selector

- `spimm_0` — spimm 0
- `spimm_1` — spimm 1
- `spimm_2` — spimm 2
- `spimm_3` — spimm 3

## Required Crosses

Products are required over feasible combinations. The HARC implementation must
review unreachable combinations explicitly before exclusions; no exclusions
are approved by this plan. Sample rlist/spimm only for push/pop-family inputs.

- `cp_decode_path x cp_valid`
- `cp_zcmp_phase x cp_valid x cp_ready`
- `cp_zcmp_rlist x cp_zcmp_spimm`
