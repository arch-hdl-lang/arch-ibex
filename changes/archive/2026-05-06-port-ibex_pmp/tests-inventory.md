# tests-inventory: ibex_pmp basic suite

This inventory lists each `@cocotb.test()` in
`tests/cocotb_tests/test_ibex_pmp_unit.py`, one per spec Requirement
(22 total). The implementer reads ONLY this file; assertions and
stimulus details live in the test bodies.

Tests bind to MUST clauses (RFC-2119). The spec-ambiguity resolutions
follow the **proposal's** §"Spec ambiguity resolutions" table (A1..A5),
not the spec's flagged punt list.

Pinned parameters: `DmBaseAddr=0`, `DmAddrMask=3`, `PMPGranularity=0`,
`PMPNumChan=3`, `PMPNumRegions=4`.

## R-MODE: region match modes

- `test_r_mode_1_off_never_matches` — A region with `mode == OFF` never
  matches; with all OFF and U-mode, REQ-MMWP-4 default-deny applies.
- `test_r_mode_2_na4_exact_match` — NA4 matches iff the request word
  address equals `csr_pmp_addr_i[r][33:2]` exactly.
- `test_r_mode_3_napot_mask` — NAPOT match uses the trailing-ones rule
  to derive the address mask (spec §S3 16-byte region exemplar).
- `test_r_mode_4_tor_inclusive_lower_exclusive_upper` — TOR region r>0:
  `addr[r-1] <= request < addr[r]`.
- `test_r_mode_5_tor_region0_lower_is_zero` — TOR region 0 uses 0 as
  the lower bound.

## R-PERM: basic permission rules

- `test_r_perm_1_basic_perm_check_encoding` — `basic_perm_check` selects
  `cfg.exec` / `cfg.write` / `cfg.read` per request type.
- `test_r_perm_2_mml0_mmode_lock_gates_basic` — MML=0, M-mode:
  unlocked grants regardless; locked needs basic R/W/X.
- `test_r_perm_3_mml0_nonmmode_basic_only` — MML=0, non-M-mode: lock
  irrelevant; only basic bit matters.

## R-MML: Machine Mode Lockdown

- `test_r_mml_1_shared_region_table` — MML=1 with `{R=0, W=1}`: the
  four-row `{L,X}` shared-region table.
- `test_r_mml_2_shared_read_only` — MML=1 with `L=W=R=X=1`: read-only
  any-priv.
- `test_r_mml_3_lock_bit_polarity_flips` — Default MML rule (outside
  the special tables): M-mode requires L=1, non-M-mode requires L=0.

## R-MMWP: Machine Mode Whitelist Policy

- `test_r_mmwp_1_unmatched_always_deny` — MMWP=1 + no match → deny any
  privilege.
- `test_r_mmwp_2_mmode_default_allow` — MMWP=0 + no match + M-mode →
  allow (modulo MML M-EXEC clause).
- `test_r_mmwp_3_mml_mmode_exec_requires_match` — MML=1 + M-mode EXEC
  + no match → deny even with MMWP=0.
- `test_r_mmwp_4_nonmmode_default_deny` — Non-M-mode + no match → deny
  regardless of mseccfg.

## R-DBG: Debug-mode bypass

- `test_r_dbg_1_dm_address_bypass` — Debug + addr in DM window
  (`(addr & ~mask) == base`) → allow regardless.
- `test_r_dbg_2_bypass_scope` — Debug + addr OUTSIDE DM window → normal
  PMP check applies.
- `test_r_dbg_3_bypass_uses_low32_only` — Bypass test uses only
  `addr[31:0]` of the byte PA; bits [33:32] of the 34-bit port are
  ignored.

## R-PRIO: Region priority

- `test_r_prio_1_lowest_index_wins` — Multiple matches → lowest-index
  region's verdict wins (spec §S5 swap test).

## R-CHAN: Per-channel independence

- `test_r_chan_1_channels_independent` — Distinct per-channel inputs
  yield independent verdicts.
- `test_r_chan_2_shared_region_table` — All channels see the same
  region table; identical inputs → identical outputs.
- `test_r_chan_3_output_formula` — `pmp_req_err_o[c] =
  ~debug_mode_allowed_access[c] & access_fault_check_res[c]` verified
  by toggling debug bypass over a denying setup.

## Test count summary

22 spec Requirements, 22 basic tests, 0 marked `@cocotb.test(skip=True)`.

PMP is fully combinational with no internal state, so every Requirement
is structurally testable at the leaf-unit level via the provided port
interface.
