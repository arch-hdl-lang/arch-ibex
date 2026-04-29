# Tasks: Port `ibex_alu` to ARCH

## 1. ARCH source

- [x] 1.1 Refreshed on `module` / `types` / `expressions` / `doc_comments` syntax.
- [x] 1.2 Wrote `src/IbexAlu.arch` covering the in-scope operator set from the spec.
- [x] 1.3 `//!` front-matter + `///` doc comment with cross-refs to upstream `ibex_alu.sv` line ranges.

## 2. Build & lint

- [x] 2.1 `arch check` + `arch build` clean. Standalone Verilator `--lint-only` clean.
- [x] 2.2 Added `"ibex_alu"` to `scripts/gen_filelist.py` SWAPPED set.
- [x] 2.3 SoC-level lint clean (`pytest tests/test_soc_lint.py`).

## 3. Verification

- [ ] 3.1 (deferred to Phase A unit-test sweep) — `tests/cocotb_tests/test_ibex_alu_unit.py` walking spec scenarios. ISR-program coverage in 3.3 is sufficient for the A1 gate; per-leaf unit tests will be batched after the rest of Phase A lands.
- [x] 3.3 `pytest tests/test_cpu_programs.py` — 4/4 ISR programs (timer / sw / ext / multictx) pass with ARCH-side `ibex_alu`.
- [x] 3.4 `pytest tests/test_soc_lint.py` — full SoC lint clean.

## 4. Archive

- [x] 4.1 Moved `changes/port-ibex-alu/` → `changes/archive/2026-04-29-port-ibex-alu/`.
- [x] 4.2 Materialized `specs/alu/spec.md` from the archived spec.
- [x] 4.3 README status updated.
- [x] 4.4 Single commit lands proposal/spec/tasks/source/build-glue/conftest changes.

## Compiler change required (out-of-tree dependency)

A1 required adding the `unpacked` Vec port modifier to ARCH so
`imd_val_q_i [2]` / `imd_val_d_o [2]` connect cleanly to upstream
`ibex_ex_block.sv`'s unpacked-array nets. Implemented on
`feat/unpacked-array-ports` branch in `arch-com` (worktree at
`../arch-com-unpacked-ports`); 224 ARCH-com tests + 5 arch-ibex tests
green. Branch held local pending push/PR decision.
