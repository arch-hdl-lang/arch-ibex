# Proposal: Port `ibex_counter` to ARCH

## Intent

Replace upstream `ibex_counter.sv` (111 LoC) with an ARCH-side
equivalent. `ibex_counter` is a parameterizable up-counter used by the
Ibex CSR block: it backs `mcycle` (parameterized to 64-bit), `minstret`,
and the per-counter HPM (hardware performance monitor) instances. The
upstream module is instantiated three times in `ibex_cs_registers.sv`
with different `CounterWidth` / `ProvideValUpd` choices.

This is the third leaf-module swap (A3). It's the first swap authored
under the **TDD-first / split-gate** flow adopted on 2026-04-29 (see
`WORKFLOW.md`): unit tests for every spec Requirement land before
`src/IbexCounter.arch` is written, the basic suite gates the arch
generation, and a background regression agent validates the full
scenario sweep without serializing the orchestrator.

## Scope

**In scope** — every parameter combination upstream uses in
`ibex_cs_registers.sv`:

- `CounterWidth ∈ {1, 32, 64}`. The 1-bit form is for HPM event
  counters that count only zero/one; 32-bit is the HPM count
  default; 64-bit is `mcycle` / `minstret`.
- `ProvideValUpd ∈ {0, 1}`. With `ProvideValUpd = 0`,
  `counter_val_upd_o` is hard-wired to `64'h0` so the synthesis tool
  is free to infer Xilinx DSPs for the increment path. With
  `ProvideValUpd = 1`, the incremented value is exposed for the
  caller to forward into a same-cycle CSR read.
- 64-bit `counter_val_o` regardless of `CounterWidth` — the upper
  `64 - CounterWidth` bits are tied to zero. Behaviour required by
  the CSR block which always fetches a 64-bit pair.
- High/low CSR write ports (`counter_we_i` for the low 32 bits,
  `counterh_we_i` for the high 32 bits, both with `counter_val_i` as
  the data). RISC-V `mcyclel`/`mcycleh` write semantics.
- Increment gate `counter_inc_i` — caller asserts to advance the
  counter on the next rising edge.
- Async active-low reset (`rst_ni`) clears the counter to `64'h0`.

**Out of scope** — this is a parametric leaf module, no out-of-scope
features beyond that. RISC-V CSR-side semantics (read masking,
mcountinhibit gating, etc.) live in `ibex_cs_registers.sv` /
`ibex_cs_registers_hybrid.sv` and are unaffected.

## Approach

Tentative ARCH constructs (final choice deferred to the spec-only
implementation agent):

- `module` with one or two `param`s (`CounterWidth`, `ProvideValUpd`).
- A 64-bit `reg counter` with async-low reset to zero. The counter is
  effectively a `Vec<UInt<1>, 64>` flat — single flop bank.
- `seq` block that, on each rising edge, applies in priority order:
  1. `counterh_we_i` writes the high 32 bits.
  2. `counter_we_i` writes the low 32 bits.
  3. otherwise, if `counter_inc_i` is high, increment the low
     `CounterWidth` bits (with carry into `[63:CounterWidth]` clamped
     to zero — these bits stay tied off).
- Combinational `counter_val_o = counter` (full 64 bits) and
  `counter_val_upd_o = ProvideValUpd ? incremented_low : 64'h0`.
- A `generate_if (ProvideValUpd)` may or may not be needed depending
  on how the implementer chooses to gate the upd output — the spec
  will specify the contract; the agent picks the construct.

## Verification gate

Per the new flow:

1. **Basic suite** (blocking) — `tests/test_ibex_counter_unit.py` walks
   one representative scenario per spec Requirement (~6–8 tests).
   Combined with the existing 5 SoC tests this brings the basic gate
   to ≤ 30 s wall-clock.
2. **Full regression** (background) —
   `tests/test_ibex_counter_unit_full.py` walks every spec Scenario
   plus parameter sweeps over `CounterWidth ∈ {1, 32, 64}` and
   `ProvideValUpd ∈ {0, 1}` — six full param combinations.

The conftest's auto-shadow logic picks up `build/ibex_counter.sv` and
filters out the upstream copy from the fusesoc filelist; no SoC
integration code change.

## Reference

Upstream: `$IBEX_ROOT/rtl/ibex_counter.sv` (Apache-2.0, 111 LoC).
Instantiated from `ibex_cs_registers.sv:1328, 1343, 1379` (the latter
inside a `for (genvar i = 0; i < ...; i++)` loop for HPM instances).
Our forked `soc/ibex_cs_registers_hybrid.sv` keeps the same instance
binding, so the swapped module slots in transparently.
