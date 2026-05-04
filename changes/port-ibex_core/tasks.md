# Tasks: Port `ibex_core` to ARCH (C1)

Spec: `specs/ibex_core/spec.md` — **21 Requirements**, 10 caller-side rules,
13 producer-side rules, 36 spec notes. Two-stage review (WORKFLOW step 6a)
is **MANDATORY** (any swap with >3 Requirements, plus this is the linchpin).

## Implementation checklist

- [x] **Proposal done** (`proposal.md`).
- [x] **Spec done** (`specs/ibex_core/spec.md`, 1371 lines).
- [x] **Tests written** (`tests/cocotb_tests/test_ibex_core_unit{,_full}.py`,
      pytest collectors, `tests-inventory.md`).
- [x] **Pipeline-fit spike** (`~/github/arch-ibex-c1-spike/spike/c1-pipeline/`)
      validated `pipeline` + stateful `inst` + cross-stage backward read +
      upstream-SV `inst`. Required arch-com fixes landed in PR #282
      (wait-FSM ref prefix) and PR #283 (dep walker + inst-output wire
      type resolution).
- [ ] **Implementer agent dispatched** → produces `src/IbexCore.arch`
      and updates `scripts/build.sh` to (a) leaf-first ordering with
      `IbexCore` last, (b) ensure the upstream-SV `ibex_cs_registers.sv`
      and its dep chain land in the build correctly.
- [ ] **Two-stage review (mandatory)**: spec-compliance pass + ARCH
      idiom pass before the build gate.
- [ ] **Basic gate** (blocking): `rm -rf build/ && make build &&
      pytest tests/test_ibex_core_unit.py tests/test_soc_lint.py
      tests/test_cpu_programs.py` (per `feedback_full_gate_before_ready`).
- [ ] **Full gate**: `make test` — all 38+ existing tests must stay
      green plus the 21 new IbexCore Requirements.
- [ ] **Archive** to `changes/archive/2026-05-DD-port-ibex_core/`.
- [ ] **PR** opened against `main` of `arch-hdl-lang/arch-ibex`.

## Construct decisions (from proposal + spike)

- **Outer**: `pipeline IbexCore` — first real-CPU use of the ARCH
  `pipeline` construct. Snake_case file output `build/ibex_core.sv`
  (already handled by `scripts/build.sh`); CamelCase `.arch` source.
- **Stages** (per proposal §Stage decomposition):
  - `stage IF` — hosts `inst if_stage_i: IbexIfStage`.
  - `stage ID` — hosts `inst id_stage_i: IbexIdStage` AND
    `inst cs_registers_i: ibex_cs_registers` (upstream-SV; .archi will
    need to be hand-written or sourced from upstream — see "cs_registers
    integration" below).
  - `stage EX` — hosts `inst ex_block_i: IbexExBlock`.
  - `stage WB` — hosts `inst wb_stage_i: IbexWbStage` AND
    `inst load_store_unit_i: IbexLoadStoreUnit`. Per proposal, LSU's
    response is the key variable-latency surface — drive a `wait until
    lsu_resp_valid` here if needed, or pass through the LSU's existing
    stall handshake (pick the lighter-touch one — try the latter first).
- **Flush is NOT framework-driven** in this design. Per proposal's stage
  decomposition: the existing `controller_i` (inside `id_stage_i`)
  already issues `pc_set` + `instr_valid_clear` to the IF stage on
  branches / exceptions / IRQs / debug-entry / WFI-exit. The pipeline
  framework's `flush Stage when ...` is **NOT used** for C1; sub-modules
  handle flush via their existing port semantics. This diverges from the
  spike's shape but is correct for IbexCore — don't add `flush` clauses.
- **Backward feedback path**: EX→ID multdiv intermediate state via
  `imd_val_d_ex` / `imd_val_q_ex` (Vec<UInt<34>, 2>). The spike
  validated cross-stage backward register reads work
  (`stage A { seq { reg_q <= B.feedback_q; } }`). Express this as
  `stage ID { ... id_stage_i.imd_val_d_ex_i <- EX.ex_block_i.imd_val_d_o; }`
  per the existing port shape — the flop lives inside `id_stage_i`
  (per spec note N-4); EX is purely combinational on this path.
- **No new `fsm` / `thread` / `fifo` etc.** — every state machine is
  already inside a sub-module. C1 is composition, not new state.

## Pre-build smoke checks (DO BEFORE the full IbexCore body)

The proposal's risks #2, #3, #4 were validated by the spike, but C1
is significantly larger than the spike. Run these **3 smoke checks**
in `~/github/arch-ibex-c1/build_smoke/` before committing to the full
.arch shape — each is < 50 lines and rules out a class of late-discovery
failures:

1. **Single-stage upstream-SV inst smoke**: a 1-stage pipeline with
   one `inst` of `ibex_cs_registers` (the actual upstream module, not
   a hand-written stub). Build with the upstream SV path on the
   filelist. Confirm:
   - arch-com builds without "undefined name: ibex_cs_registers"
     (the dep walker fix in PR #283 handles `Item::Pipeline` now).
   - The upstream's `.svh` includes (`prim_assert.svh`, etc.) don't
     break Verilator lint; if they do, surface as a tasks-level open
     question before proceeding.
   - Wire types for cs_registers' output ports come out correctly
     sized (PR #283 fix). If any come out as bare `logic`, the
     `.archi` for cs_registers will need hand-writing to give arch-com
     the port types.

2. **EX↔ID backward feedback smoke**: a 2-stage pipeline with one
   `inst` per stage where the earlier stage reads
   `LaterStage.inst_q.field` in its `seq` block. Mirrors the
   `imd_val_q_ex` shape. The spike already covered this for plain
   stage regs; this confirms it works when the source is an
   inst-output wire.

3. **All-five-instances composition smoke**: a "skeleton" IbexCore
   with the 5 ARCH-side `inst` blocks but no real wiring (just
   tieoffs). Run `make build` to confirm scripts/build.sh still
   handles the new ordering (IbexCore last) and the cross-stage refs
   parse. Do NOT include cs_registers in this smoke — it's covered
   by smoke #1.

If any smoke fails, **stop and report**. Do not paper over with a
workaround.

## Spec extractor flags forwarded to implementer

(From the spec's "Spec notes" section — copying the load-bearing ones
here so the implementer doesn't need to re-derive them.)

- **N-2: cs_registers stays upstream**. Source is
  `~/github/ibex/rtl/ibex_cs_registers.sv` plus its dep chain
  (`ibex_pkg.sv`, `ibex_csr.sv`, `prim_pkg.sv`, `prim_buf.sv`,
  `prim_clock_gating.sv`, possibly more). The Verilator runner in
  `tests/test_ibex_core_unit.py` already lists the chain — sanity
  check it before the basic gate. The `.archi` for cs_registers may
  need to be hand-written if arch-com can't derive it from the .sv
  source (see smoke #1).
- **N-4: imd_val flop ownership**. The flop is in `id_stage_i`, NOT
  in `ex_block_i`. EX is combinational on `imd_val_d_o`; ID flops
  it as `imd_val_q_ex`. Don't add a redundant flop at the C1 level.
- **N-7: mubi encodings**. `IbexMuBiOn = 4'b0101` (=5),
  `IbexMuBiOff = 4'b1010` (=10). `core_busy_o` is the full 4-bit
  mubi pattern under SecureIbex=0, NOT a 1-bit OR.
- **N-19 / N-36: ARCH-construct decisions deferred to proposal**.
  Already resolved (above).

## ARCH syntax pitfalls (read once, internalize)

Per `~/.claude/projects/-Users-<user>-github-arch-ibex/memory/feedback_arch_syntax_pitfalls.md`,
the following 14 traps each cost a real fix-pass round-trip in earlier
swaps. Read the memory file in full before writing the .arch source.
Highlights especially relevant to C1:

- **Rule #5 — `unpacked` Vec ports**: only when interop'ing with
  upstream SV declaring `[W] x [N]`. With cs_registers as upstream-SV,
  any cs_registers ports declared as unpacked-array in the SV must be
  matched with `unpacked Vec<UInt<W>, N>` on the .arch side.
- **Rule #6 — operator-encoding constants**: declare as
  `let NAME: UInt<W> = W'd...;` not `local param NAME: const = W'd...;`
  to avoid WIDTHEXPAND.
- **Rule #11 — thread dead-skid**: not relevant for C1 (no
  `thread` blocks expected) but the same lesson applies to wait-FSM
  drives in pipeline stages — don't gate sub-modules on inputs that
  fall to 0 during stage stall.
- **Rule #14 — `use Pkg;` placement**: at file scope BEFORE the
  pipeline declaration. C1 will likely `use IbexCoreSharedPkg;` plus
  `use IbexPkg;` (auto-resolved from upstream).

## B-phase methodology lessons (forwarded)

- Per `feedback_full_gate_before_ready`: before claiming green, run
  `rm -rf build/ && make build && make test`. The narrow swap-local
  gate misses cross-cutting regressions. Especially relevant for C1
  since it touches the SoC's `cpu` instance.
- Per `feedback_avoid_verilator_in_comments` (B2): no literal word
  `Verilator` in `///` doc comments — Verilator preprocessor parses
  it as a directive and rejects the SV. Use `verilator` lowercase or
  `the simulator`.
- Per `feedback_thread_single_state_idiom` (A9): a single-state
  `thread` IS a `seq` block in disguise. Don't reach for `thread`.
  C1 expects no `thread` blocks at all.
- Per `feedback_shared_types_package` (B5): if any new struct/enum
  is needed for C1 routing (likely none — IbexCoreSharedPkg already
  has `ExcCause` etc.), extract to a package before the second
  consumer. Otherwise, `Duplicate TYPEDEF` Verilator errors at SoC
  link time.

## cs_registers integration — open question

The .archi for `ibex_cs_registers` will determine smoke #1's outcome.
Three options (from cheapest to most invasive):

1. **Run arch-com on the upstream SV directly to auto-emit a `.archi`** —
   probably won't work since arch-com doesn't parse SystemVerilog,
   only ARCH HDL. Skip.
2. **Hand-write the `.archi` from the SV port list**. Tedious
   (cs_registers has ~80 ports) but mechanical. Place at
   `src/ibex_cs_registers.archi`. Per the spike, the .archi can use
   concrete numeric widths (`UInt<32>`) instead of param refs to avoid
   the param-substitution path — preferred for upstream-SV stubs.
3. **Put cs_registers at module scope outside the pipeline** as a
   sibling module-level `inst`. Per proposal's risk #3b, this
   introduces ID↔CSRs combinational paths crossing the pipeline
   boundary. Avoid unless smoke #1 reveals option 2 is unworkable.

The implementer should try option 2 first. If smoke #1 shows it
works, move on. If it fails, escalate (don't fall through to option 3
without surfacing the issue first — option 3 affects the C1 demo
narrative).

## Verification gate

**Basic gate (blocking, run before READY.md)**:
```sh
rm -rf build/
make build
pytest tests/test_ibex_core_unit.py
pytest tests/test_soc_lint.py
pytest tests/test_cpu_programs.py
```

**Full SoC gate**:
```sh
make test
```

Expected after C1 lands: 38 (B5) + 21 (C1 new) = ~59 tests passing,
plus the 4 ISR programs (sw/ext/timer/multictx) which exercise the
full SoC at integration level. The 4 ISR programs are the real
acceptance criterion for "the swap is transparent at SoC boundary."

**Phase C end-gate** (deferred to a follow-up task): adds
riscv-arch-tests RV32IMC compliance per the project plan. Not
required for C1 to ship, but flagged as upcoming.
