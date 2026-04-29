# Proposal: Port `ibex_register_file_ff` to ARCH

## Intent

Replace upstream `ibex_register_file_ff.sv` (108 LoC) — the flop-based RV32
GPR file — with an ARCH-side equivalent that emits an SV module of the
same name. This is the second leaf-module swap (A2) and the first one
that exercises:

1. Clocked state in ARCH (`reg`/`seq` with async-active-low reset).
2. Per-element `generate for` to instantiate one flop block per
   architectural register, mirroring upstream's `g_rf_flops` loop.
3. The new `unpacked` Vec port modifier on an *internal* array shape
   (the read-multiplexed `rf_reg [NUM_WORDS]`), validating the same
   feature path the ALU's `imd_val_q_i [2]` exercised.

## Scope

**In scope** — the default Ibex small configuration:

- `RV32E = 0` → 32 registers (x0–x31), 5-bit address.
- `DataWidth = 32`.
- `DummyInstructions = 0` → x0 hardwired to `WordZeroVal` (no flop).
- `WordZeroVal = '0` (the reset / x0 read value).
- Two combinational read ports (`rdata_a_o` / `rdata_b_o`) and one
  write port (`waddr_a_i` + `wdata_a_i` + `we_a_i`).
- Async active-low reset (`rst_ni`) loads every flop with
  `WordZeroVal` on assertion.
- Concurrent read-while-write to the same address returns the **old**
  value (FF behavior, not RAM forwarding).

**Carried at boundary, not exercised behaviourally** — the SV port
signature must match upstream so `ibex_top.sv` instantiates without
ripple. The ports below remain declared but produce no observable
behaviour under the in-scope parameter values:

- `test_en_i` — unused in the FF flavour (upstream wires it to a dead
  `unused_test_en` signal).
- `dummy_instr_id_i`, `dummy_instr_wb_i` — only meaningful when
  `DummyInstructions = 1`. With `DummyInstructions = 0`, upstream
  XORs them into `unused_dummy_instr`.

**Out of scope** — guarded by parameters, deferred to later phases:

- `RV32E = 1` (16-register variant — would require parameterising
  `NUM_WORDS = 16` through the generate). Phase D opentitan-config.
- `DummyInstructions = 1` (security hardening — adds an explicit x0
  flop and the `dummy_instr_*` mux on read). Phase D.

## Approach

The module is fundamentally a register array with a write decoder, two
read muxes, and a per-register flop block. Tentative ARCH constructs
(final choice deferred to the spec-only implementation agent — listed
here so the proposal can be reviewed without reading the implementation):

- `module` with combinational outputs for the read ports and a
  separate `seq` block per generated flop element for the writes.
- `generate for i in 1..NUM_WORDS` to emit one flop per register
  (matches upstream's `g_rf_flops`).
- Internal `Vec<UInt<32>, NUM_WORDS>` to hold the register state, then
  combinational read mux: `rdata_a_o = rf_reg[raddr_a_i]`.
- x0 (`rf_reg[0]`) is a tied constant — no flop, no `generate` slot.

The implementation agent works from `specs/register_file_ff/spec.md`
alone and chooses constructs to satisfy that contract. If a clean ARCH
encoding requires a compiler feature that doesn't yet exist (e.g.
generate-for over array indices), the agent flags it and the
orchestrator escalates.

## Verification gate

1. `arch build src/IbexRegisterFileFf.arch` lands clean.
2. `make build` produces `build/ibex_register_file_ff.sv`; conftest
   auto-discovers it and shadows the upstream copy in the SoC filelist.
3. `verilator --lint-only` on the SoC stays clean.
4. Existing 4 cocotb ISR programs (timer / sw / ext / multictx) still
   pass end-to-end. These programs exercise the register file on every
   instruction (load / store / arithmetic / compare); any read-after-write
   bug would surface in the trap handler's stack restore at minimum.
5. Stretch: a focused unit test (`test_ibex_register_file_ff_unit.py`)
   batched at the end of Phase A — see HANDOFF.md decision #2.

## Reference

Upstream: `$IBEX_ROOT/rtl/ibex_register_file_ff.sv` (Apache-2.0, 108 LoC).
Instantiated from: `ibex_top.sv:463` (and shadowed in `ibex_lockstep.sv`,
not exercised by the mini SoC).
