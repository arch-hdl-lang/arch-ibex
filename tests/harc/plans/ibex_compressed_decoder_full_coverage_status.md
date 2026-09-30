# Compressed-decoder HARC coverage status

The native TBIR suite now measures all 85 in-scope bins and all 36 combinations
of the three required crosses. One retained X/Z bin is diagnostic-only, outside
the two-state contract permitted by spec.md. This is not a four-state coverage
claim. Source coverage is independently gated at 3/3 line records and 110/110
branch/control records after merging RV32ZC=3 and the checked RV32ZC=1 probe;
no source waivers are used.

Evidence and reproducible commands: [execution report](ibex_compressed_decoder_execution.md).
Historical archived hit counts are not used.

## Coverpoint Bin Status

| Coverpoint | Bin | Status | Evidence / next action |
| --- | --- | --- | --- |
| `cp_32_bit_pass_through` | `pass_through_addi`, `pass_through_ebreak` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_0_c_addi4spn` | `c_addi4spn_x8_sp_4`, `c_addi4spn_reserved_zero_immediate` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_0_c_lw` | `c_lw_x8_0_x9`, `c_lw_x15_124_x14_max_immediate` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_0_c_sw` | `c_sw_x8_0_x9`, `c_sw_x15_4_x14` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zcb_quadrant_0_c_lbu_c_lh_c_lhu_c_sb_c_sh` | `c_lbu_x8_0_x9`, `c_lh_x8_2_x9`, `c_sh_with_reserved_instr_i_6_1`, `reserved_q0_funct3_100_instr_i_12_10_110` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_0_reserved_funct3_codes` | `reserved_funct3_001`, `reserved_funct3_111` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_1_c_addi_c_nop` | `c_nop`, `c_addi_x1_x1_1` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_1_c_jal_c_j` | `c_j_0`, `c_jal_0_rv32_only` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_1_c_li` | `c_li_x1_0`, `c_li_x2_1` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_1_c_lui_c_addi16sp` | `c_lui_x3_1`, `c_addi16sp_16`, `c_lui_zero_imm_reserved` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_1_c_srli_c_srai` | `c_srli_x8_x8_1`, `c_srai_x9_x9_31`, `c_srli_with_shamt_5_1_reserved` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_1_c_andi` | `c_andi_x8_x8_1`, `c_andi_x15_x15_0` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_1_c_sub_c_xor_c_or_c_and` | `c_sub_x8_x8_x9`, `c_xor_x8_x8_x9`, `c_or_x8_x8_x9`, `c_and_x8_x8_x9`, `c_subw_reserved_on_rv32` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zcb_quadrant_1_c_mul` | `c_mul_x8_x8_x9` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zcb_quadrant_1_zext_b_sext_b_zext_h_sext_h_not` | `c_zext_b_x8`, `c_not_x8`, `c_zext_w_rv64_only_reserved_on_rv32` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_1_c_beqz_c_bnez` | `c_beqz_x8_0`, `c_bnez_x8_4` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_2_c_slli` | `c_slli_x1_x1_1`, `c_slli_with_shamt_5_1_reserved` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_2_c_lwsp` | `c_lwsp_x1_0`, `c_lwsp_with_rd_x0_reserved` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_2_c_mv_c_jr_c_add_c_jalr_c_ebreak` | `c_mv_x8_x9`, `c_jr_x1`, `c_jr_x0_reserved`, `c_add_x8_x8_x9`, `c_ebreak`, `c_jalr_x1` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_2_c_swsp` | `c_swsp_x1_0` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zca_quadrant_2_reserved_funct3_codes` | `reserved_q2_funct3_011` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zcmp_cm_push_multi_cycle_expansion` | `cm_push_ra_16_first_sub_step`, `cm_push_ra_16_final_sub_step`, `cm_push_reserved_rlist_2` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zcmp_cm_pop_cm_popret_cm_popretz_multi_cycle_expansion` | `cm_pop_ra_16_first_sub_step`, `cm_popret_final_sub_step`, `cm_popretz_a0_zeroing_sub_step` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zcmp_cm_mvsa01_cm_mva01s` | `cm_mvsa01_step_1_mvsa01_a0_s0`, `cm_mva01s_step_2`, `zcmp_011_sub_quadrant_reserved` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zcmp_default_reserved_encodings` | `zcmp_unmapped_funct5` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_is_compressed_o_is_a_pure_lsb_decode` | `compressed_bit_set`, `compressed_bit_clear` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_gets_expanded_o_gating_on_valid_i` | `spurious_cm_push_pattern_with_valid_i_0`, `cm_push_with_valid_i_1` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zcmp_fsm_stability_when_valid_i_0` | `fsm_frozen_with_valid_i_0` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_pure_pass_through_when_instr_i_1_0_is_unknown_any` | `specified_behavior` | `diagnostic_only` | Untested X/Z behavior excluded from native two-state scope by spec; independently reviewed by /root/review_844. Not counted as hit. |
| `cp_decode_path` | `quadrant_0`, `quadrant_1`, `quadrant_2`, `rv32_passthrough` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_valid` | `low`, `high` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_ready` | `low`, `high` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zcmp_phase` | `idle`, `intermediate`, `final` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zcmp_rlist` | `reserved_0_to_3`, `minimum_4`, `middle_5_to_14`, `maximum_15` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |
| `cp_zcmp_spimm` | `spimm_0`, `spimm_1`, `spimm_2`, `spimm_3` | `implemented_hit` | DecoderCoverage: post-comparison named bin; independent upstream RTL oracle. |

## Required Cross Status

| Cross | Status | Evidence / next action |
| --- | --- | --- |
| `cp_decode_path x cp_valid` | `implemented_hit` | DecoderCoverage: all declared combinations measured, no cross exclusions. |
| `cp_zcmp_phase x cp_valid x cp_ready` | `implemented_hit` | DecoderCoverage: all declared combinations measured, no cross exclusions. |
| `cp_zcmp_rlist x cp_zcmp_spimm` | `implemented_hit` | DecoderCoverage: all declared combinations measured, no cross exclusions. |
