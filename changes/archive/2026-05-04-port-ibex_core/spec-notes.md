# C1 IbexCore — spec notes / open questions surfaced during triage

## LSU producer-side bug discovered during C1 unit-test triage

The B0 `IbexLoadStoreUnit` (archived) had `data_req_o = lsu_req_i or
handle_misaligned_q`. That assertion holds only while the upstream
consumer drives `lsu_req_i = 1`. Under the C1 / B5 ID-stage contract
`lsu_req_o = instr_executing & instr_first_cycle & lsu_req_dec`, ID
drops `lsu_req_o` after one cycle — at which point `data_req_o` would
also drop. That violates `specs/load_store_unit/spec.md`
§"Delayed grant — aligned access" (line 79):

> `data_req_o` remains asserted and all address-phase outputs remain
> stable until `data_gnt_i` is received.

The B0 LSU spec assumed an upstream driver that holds `lsu_req_i`,
but the C1/B5 chain doesn't. The B0 unit tests granted on the same
cycle as the request, so this path was never exercised at the LSU
swap level.

**Fix applied during C1 triage** (in `src/IbexLoadStoreUnit.arch`):
added a `data_req_pending_q` register that latches "first request
issued, awaiting first grant" (≈ upstream `ls_fsm_cs == WAIT_GNT`),
included it in the `data_req_o` and `lsu_req_done_o` expressions, and
in the FSM transition that exits WAIT_GNT on first grant. The fix is
local, minimal, and preserves the LSU's per-state semantics
documented in the file.

This is essentially a producer-side bug in B0 that was masked by the
B0 unit-test setup. It was caught only at the IbexCore-swap scope.

## Pre-existing issue: `tests/test_ibex_core_unit_full.py` SV file order

The full-regression test file lists Verilator sources as
`ARCH_SV_FILES + UPSTREAM_SV_FILES`, which puts `ibex_pkg.sv` (which
defines the SV-level `rv32m_e` enum referenced by `IbexCore.arch`'s
typed parameter) AFTER the consumer modules. Verilator rejects the
build with "expecting IDENTIFIER" syntax errors on every port line
of `ibex_core` because the typed-enum parameter forward-declaration
isn't resolved.

The basic suite (`tests/test_ibex_core_unit.py`) has the correct
order (`UPSTREAM_SV_FILES + ARCH_SV_FILES`). The fix is a one-line
swap; this issue predates C1 and is not blocking the C1 swap itself
(the full suite is the optional extended-coverage harness and was
already skipped/erroring before C1 changes). Left for a follow-up.
