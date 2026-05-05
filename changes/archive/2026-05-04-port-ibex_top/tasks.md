# Tasks: Port `ibex_top` to ARCH (C2)

Spec: `specs/ibex_top/spec.md` — **15 Requirements**, 10 caller-side rules,
11 producer-side rules, 36 spec notes. Two-stage review (WORKFLOW step 6a)
is **MANDATORY** (>3 Requirements + closes Phase C).

## Implementation checklist

- [x] **Proposal done** (`proposal.md`, 807 lines).
- [x] **Spec done** (`specs/ibex_top/spec.md`, 1325 lines).
- [x] **Tests written** (basic + full cocotb suites + collectors + `tests-inventory.md`).
- [ ] **Implementer agent dispatched** → produces `src/IbexTop.arch` and
      hand-written `src/prim_clock_gating.archi` + `src/prim_buf.archi`
      stubs.
- [ ] **Two-stage review (mandatory)**: spec-compliance pass + ARCH idiom
      pass before the build gate.
- [ ] **Basic gate** (blocking): `rm -rf build/ && make build &&
      pytest tests/test_ibex_top_unit.py tests/test_soc_lint.py
      tests/test_cpu_programs.py`.
- [ ] **Full gate**: `make test`. Expected after C2 lands: 44 (post-C1) +
      ~25 (C2 new) = ~69 cocotb sub-tests across the unit-suite collectors,
      plus the 4 ISR programs and B-phase tests must remain green.
- [ ] **Archive** to `changes/archive/2026-05-DD-port-ibex_top/`.
- [ ] **PR** opened against `main` of `arch-hdl-lang/arch-ibex`.

## Construct decisions (from proposal + spec)

- **Outer**: `module ibex_top` (snake_case top, CamelCase `.arch` source
  `IbexTop.arch`). Plain `module`, NOT a `pipeline` — the pipeline is
  inside IbexCore. C2 is just glue.
- **`inst` blocks** (4 total):
  - `inst u_ibex_core: ibex_core` — ARCH-side, full pipeline (just merged
    as PR #9, lives at `src/IbexCore.arch`).
  - `inst register_file_i: ibex_register_file_ff` — A2 ARCH leaf.
  - `inst core_clock_gate_i: prim_clock_gating` — upstream-SV cell, needs
    hand-written `.archi` stub at `src/prim_clock_gating.archi`.
  - `inst u_fetch_enable_buf: prim_buf` — upstream-SV cell, needs hand-
    written `.archi` stub at `src/prim_buf.archi`.
- **Latched flop**: just `core_busy_q: UInt<4>` (the 4-bit MuBi). Per
  spec note "core_busy_q on ungated `clk_i`" — `seq on clk_i rising`
  (NOT the gated `core_clock_gate_i.clk_o`). Async-low reset to
  `IbexMuBiOff` (= 4'b1010 = 10).
- **Module-scope `comb` blocks** for module glue:
  - mubi assembly (`core_busy_d` from `core_busy_o[0]`)
  - `clock_en` derivation (= `core_busy_q != IbexMuBiOff`)
  - `core_sleep_o` derivation (= `core_busy_q == IbexMuBiOff`)
  - mem-data ECC merge (collapses to no-op under `MemECC=0`)
  - alert OR-trees (tied 0 under `SecureIbex=0` / `Lockstep=0`)
  - ICache RAM tieoffs (under `ICache=0`)
  - lockstep alert tieoffs (under `Lockstep=0`)
  - dummy-instr seed flop chain tieoffs (under `DummyInstructions=0`)
- **No new `fsm` / `thread` / `pipeline`**. Plain `module` body.

## Pre-build smoke checks (verify before full IbexTop body)

C2 risks are smaller than C1 (since the heavy `pipeline` work is already
done), but two open questions from the spec/proposal need verification:

1. **Upstream-SV `prim_*` `.archi` stub shape**: are 4-port
   `prim_clock_gating` (`clk_i, en_i, test_en_i, clk_o`) and 2-port
   `prim_buf #(.Width(W)) (data_i, data_o)` cells correctly
   instantiable from arch-com via hand-written stubs? Mirror the C1
   `cs_registers.archi` methodology — concrete numeric widths, no param
   refs that arch-com can't resolve. Run a 1-stage smoke that instantiates
   `prim_buf` + `prim_clock_gating` from a tiny ARCH `module` and lints
   clean.

2. **Spec note N-7 — `ic_*_rdata` packed-vs-unpacked port shape between
   IbexCore and IbexTop**: read `build/ibex_core.sv` to see how the auto-
   emitted port for `ic_tag_rdata_i` / `ic_data_rdata_i` looks. If
   packed `[N*W-1:0]`, IbexTop's tieoff side must be packed Vec; if
   unpacked `[W-1:0] [N]`, must be `unpacked Vec`. The implementer's
   IbexTop should match whatever IbexCore actually emits.

If either smoke fails, STOP and report.

## Spec extractor flags forwarded to implementer

(From `specs/ibex_top/spec.md` — load-bearing items copied here.)

- **N-7 (`ic_*_rdata` packed/unpacked)**: see smoke #2 above. IbexTop
  must match IbexCore's emitted port shape, not pre-commit to either
  choice.
- **N-21 (`unused_scramble_inputs`)**: tied off via assign-on-decl in
  upstream. ARCH equivalent is `let unused = ...` at module scope.
- **N-29 (`prim_buf` semantics)**: must remain as upstream-SV `inst`,
  not collapsed to a wire alias — Verilator's optimizer might erase a
  bare wire alias, but a `prim_buf` instance is treated as a synth
  optimization barrier.
- **N-22 (`prim_flop` collapse under SecureIbex=0)**: the upstream
  uses `prim_flop` for `core_busy_q`, but its specialised hardening
  is dead under SecureIbex=0. Spec says implementer MAY use a plain
  `reg core_busy_q` with `seq` block.
- **WordZeroVal pass-through**: a complex SV expression
  `RegFileDataWidth'(prim_secded_pkg::SecdedInv3932ZeroWord)`. Under
  `RegFileECC=0` (default), this is observably equivalent to 0; pass
  `0` at the inst boundary.

## ARCH syntax pitfalls (read once, internalize)

Per `~/.claude/projects/-Users-<user>-github-arch-ibex/memory/feedback_arch_syntax_pitfalls.md`,
14 traps. Key ones for C2:

- **Rule #5 — `unpacked` Vec ports**: only when interop'ing with
  upstream-SV unpacked-array signals. C2's RAM-config ports (struct
  arrays, `[NUM_WAYS]`) are unpacked. Match upstream.
- **Rule #6 — operator-encoding constants**: declare as `let NAME:
  UInt<W> = W'd...;` (e.g. `let IbexMuBiOff: UInt<4> = 4'd10;`) not
  `local param`.
- **Rule #14 — `use Pkg;` placement**: at file scope BEFORE the
  module declaration. C2 will likely `use IbexCoreSharedPkg;` if it
  references the shared types; otherwise omit.
- **Rule #12 — Param-as-ternary-condition triggers WIDTHTRUNC**: for
  the bit-typed params (`PMPEnable`, `SecureIbex`, etc.), declare with
  explicit `[0:0]: const = 1'd0` or use the form
  `param NAME[0:0]: const = 1'd0;`.

## arch-com extensions used (all merged)

- PR #282: wait-FSM ref-prefix fix.
- PR #283: pipeline auto-dep walker + cross-stage inst-output type res.
- PR #286: cross-package qualified enum types (`ibex_pkg::rv32m_e`).
- PR #288: post-name unpacked-array dim + `UInt<W>` clean syntax for
  typed-value params (`pmp_cfg_t [16]`, `UInt<34> [16]`,
  `pmp_mseccfg_t`).

C2 may use any of these. Specifically, the `WordZeroVal` and
`RegFile`-related typed params can use the qualified-enum form when
appropriate, or pass concrete values.

## B-phase + C1 lessons forwarded

- Per `feedback_full_gate_before_ready`: before READY.md, always
  `rm -rf build/ && make build && make test`. Narrow swap-local gate
  misses cross-cutting regressions.
- Per `feedback_avoid_verilator_in_comments`: no literal word
  `Verilator` in `///` doc comments.
- Per `feedback_thread_single_state_idiom`: don't reach for `thread`.
  C2 expects no `thread` blocks at all.
- Per the C1 spec-notes lesson: any port-shape mismatch surfaces at
  Verilator lint time, not at build time. Run lint early and often.

## Verification gate

**Basic gate (blocking)**:
```sh
rm -rf build/
make build
pytest tests/test_ibex_top_unit.py
pytest tests/test_soc_lint.py
pytest tests/test_cpu_programs.py
```

**Full SoC gate**:
```sh
make test
```

Expected after C2 lands: ~69 cocotb sub-tests across the C1 + C2 unit
suites, plus the 4 ISR programs and all B-phase composite tests.

**Phase C end-gate**: deferred to a follow-up task. Adds riscv-arch-tests
RV32IMC compliance per the project plan. C2 closes the structural Phase C
work; the compliance suite is a separate task that lights up once C2 has
shipped.
