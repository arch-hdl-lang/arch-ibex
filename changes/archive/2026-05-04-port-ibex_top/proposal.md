# Proposal: Port `ibex_top` to ARCH

## Intent

This swap replaces `ibex_top.sv` (1394 LoC upstream; ~250 LoC effective
under SoC pinning, after subtracting the `if (Lockstep)`,
`if (ICache)`, `if (ICacheScramble)`, `if (RegFile == RegFileFPGA)`,
`if (RegFile == RegFileLatch)`, `if (MemECC)`, the `` `ifdef
INC_ASSERT `` blocks and the `` `ifdef RVFI `` block) with
`src/IbexTop.arch`. `ibex_top` is the SoC's actual cpu instantiation
point: `soc/ibex_mini_soc.sv` line 469 binds
`ibex_top_tracing #(...) u_ibex(...)` (the upstream tracing wrapper
itself just instantiates `ibex_top`), so replacing this module makes
the entire CPU pipeline ARCH-side from the SoC's point of view.

C2 is the **second swap of Phase C**, building on C1 IbexCore (PR #9,
just merged) which proved out the ARCH `pipeline` construct on the
inner CPU. Where C1 demonstrated that `pipeline` can host a real CPU
body, C2 closes the loop by porting the outer wrapper that the SoC
binds against. C2 is structurally simpler than C1 — `ibex_top` has no
pipelined behavior of its own; it is **glue**: a clock-gate, a few
input buffers, an `ibex_core` instance, an `ibex_register_file_ff`
instance, ECC-data-merge wiring (collapsed under `MemECC=0`), the
`core_busy_q` mubi flop, and a pile of `Lockstep`/`ICache`/`Scramble`
generates that all evaporate under our pins.

The post-merge build has already produced `src/ibex_core.archi`
(reflecting C1's actual port shape including the typed-value params
landed via arch-com #286/#288); C2 instantiates `ibex_core` from
ARCH using that stub. After C2 lands, Phase C's end-gate adds
riscv-arch-tests RV32IMC compliance per the project plan — that
test-infrastructure work is **not** part of C2.

## Scope

**In scope (matches `ibex_top.sv` parameter pins under
`soc/ibex_mini_soc.sv`):**

- `RV32E = 1'b0` (line 24 default, no override at `u_ibex`) — full
  32-entry RF; the regfile inst's `RV32E` param is passed through.
- `RV32M = ibex_pkg::RV32MFast` (line 25 default; `RV32M` macro
  override at SoC line 46 binds the same value through
  `ibex_top_tracing`) — multdiv enabled, fast variant. Pure
  pass-through into `u_ibex_core`.
- `RV32B = ibex_pkg::RV32BNone` (line 26 default; SoC override at
  line 49 same value) — no bitmanip.
- `RV32ZC = ibex_pkg::RV32ZcaZcbZcmp` (line 27 default; SoC override
  at line 52 same value) — pass-through.
- `RegFile = ibex_pkg::RegFileFF` (line 28 default; SoC override at
  line 55 same value) — selects the `gen_regfile_ff` arm at line 462.
  The **`RegFileFPGA` and `RegFileLatch` arms (lines 484-528) are
  out of scope** (project plan: "stay upstream forever").
- `BranchTargetALU = 1'b0` (line 29) — pass-through.
- `WritebackStage = 1'b0` (line 30) — pass-through.
- `ICache = 1'b0` (line 31) — selects `gen_norams` (line 753), which
  ties `ic_*_rdata` to 0, sinks `ram_cfg_*` ports, and lets the
  `prim_ram_1p` instances (lines 600+, 707+) **collapse to nothing**.
- `ICacheECC = 1'b0` (line 32) — `BusSizeECC = BUS_SIZE = 32`,
  `TagSizeECC = IC_TAG_SIZE`. Pass-through.
- `BranchPredictor = 1'b0` (line 33) — pass-through.
- `DbgTriggerEn = 1'b0` (line 34) — pass-through.
- `DbgHwBreakNum = 1` (line 35) — pass-through.
- `SecureIbex = 1'b0` (line 36) — selects `g_clock_en_non_secure`
  (line 264) for `core_busy_q`. Also makes `localparam Lockstep =
  SecureIbex = 0` (line 187) so the entire `if (Lockstep)` arm
  (lines 784-1118) collapses to `gen_no_lockstep` (lines 1119-1136).
  Also makes `DummyInstructions = SecureIbex = 0` (line 189),
  `MemECC = SecureIbex = 0` (line 38), `ICacheTweakInfection =
  SecureIbex = 0` (line 42).
- `LockstepOffset = 1` (line 37) — unused under `Lockstep=0`.
- `MemECC = 1'b0` (derived) — selects `gen_non_mem_rdata_ecc`
  (line 307); `data_rdata_core[31:0] = data_rdata_i`,
  `instr_rdata_core[31:0] = instr_rdata_i`, no ECC bit merging.
  The `gen_mem_wdata_ecc` arm (line 774) collapses to
  `gen_no_mem_ecc` (line 779): `data_wdata_intg_o = '0`. The
  upper-7 ECC bits of `core_busy_q` and the data buses are not
  wired (the `prim_buf u_prim_buf_data_wdata_intg` at line 775 is
  out of scope).
- `MemDataWidth = MemECC ? 39 : 32` (line 39) — collapses to 32.
- `ICacheScramble = 1'b0` (line 40) — selects `gen_noscramble`
  (line 568): `scramble_req_q = scramble_req_d = 0`, `scramble_key_q
  = scramble_nonce_q = '0`, `scramble_key_valid_q = 1`,
  `scramble_req_o = 1'b0`. The entire `gen_scramble` arm (lines
  534-561) and its scrambling flops collapse.
- `RegFileECC = 1'b0` (`localparam` line 190) — pass-through; the
  regfile is non-ECC.
- `RegFileDataWidth = 32` (`localparam` line 192) — fixed 32.
- `DmHaltAddr = 32'h0000_0000`, `DmExceptionAddr = 32'h0000_0000`,
  `DmBaseAddr = 32'h0000_0000`, `DmAddrMask = 32'h0000_0003` (per
  SoC override lines 470-473). Pass-through.
- `MHPMCounterNum = 0`, `MHPMCounterWidth = 40`,
  `PMPEnable = 0`, `PMPGranularity = 0`, `PMPNumRegions = 4` —
  defaults; pass-through.
- `CsrMvendorId = 32'b0`, `CsrMimpId = 32'b0` — pass-through.
- `RndCnstIbexKey`, `RndCnstIbexNonce`, `RndCnstLfsrSeed`,
  `RndCnstLfsrPerm` — pass-through (only the LFSR seed/perm
  reach `ibex_core`; key/nonce only feed scramble paths and
  collapse).

**The two ARCH sub-module instances inside the IbexTop body:**

| Upstream line | Instance               | ARCH leaf |
|---------------|------------------------|-----------|
| 313           | `ibex_core u_ibex_core`| `IbexCore.arch` (C1, port stub `src/ibex_core.archi`) |
| 463           | `ibex_register_file_ff register_file_i` | `IbexRegisterFileFf.arch` (A2, port stub `src/ibex_register_file_ff.archi`) |

**The upstream-SV cells that stay as `inst` against hand-written
`.archi` stubs** (same pattern as B4's `ibex_cs_registers` and the C1
SV-from-pipeline-stage `inst`):

| Upstream line | Cell | Width / pins |
|---------------|------|--------------|
| 282           | `prim_clock_gating core_clock_gate_i` | 4 single-bit pins (`clk_i`, `en_i`, `test_en_i`, `clk_o`) |
| 294           | `prim_buf #(.Width($bits(ibex_mubi_t))) u_fetch_enable_buf` | 4-bit `in_i`/`out_o` (`ibex_mubi_t = logic [3:0]`) |

**Non-instance glue at module scope** (per upstream-SV body):

- `core_sleep_o = ~clock_en;` (line 280).
- `clock_en = core_busy_q[0] | debug_req_i | irq_pending |
  irq_nm_i;` (line 274, non-secure form).
- `core_busy_q` is a 4-bit mubi async-reset flop driven by
  `core_busy_d` from `u_ibex_core` (lines 267-273, the
  `g_clock_en_non_secure` arm). Plain `reg` + `seq on clk_i` with
  `reset rst_ni => IbexMuBiOff` is the natural ARCH form.
- `unused_core_busy = ^core_busy_q[$bits(ibex_mubi_t)-1:1];` (line
  277) — XOR sink for the unused upper 3 bits of mubi.
- `data_rdata_core[31:0] = data_rdata_i;`,
  `instr_rdata_core[31:0] = instr_rdata_i;` (lines 301-302).
- `unused_intg = ^{instr_rdata_intg_i, data_rdata_intg_i};` (line
  310, `gen_non_mem_rdata_ecc` arm).
- `data_wdata_o = data_wdata_core[31:0];` (line 772). Under
  `MemECC=0`, `data_wdata_core` is 32-bit (no upper ECC slice), so
  this reduces to `data_wdata_o = data_wdata_core;` — but keeping
  the slice form preserves waveform-name equivalence with upstream.
- `data_wdata_intg_o = '0;` (line 780, `gen_no_mem_ecc` arm).
- `gen_no_lockstep` block (lines 1119-1136): all 9 lockstep / shadow
  output ties (`lockstep_*_alert_* = 0`, `lockstep_cmp_en_o =
  IbexMuBiOff`, `data_*_shadow_o = 0`, `instr_*_shadow_o = 0`) plus
  `unused_scan = scan_rst_ni`.
- `gen_norams` block (lines 753-770): `ram_cfg_rsp_icache_*_o = '0`,
  `ic_tag_rdata = '0`, `ic_data_rdata = '0`, `icache_*_alert = '0`,
  plus the `unused_ram_*` xor-sinks.
- `gen_noscramble` block (lines 568-583): all 8 scrambling-state
  ties.
- `icache_alert_major_internal = (|icache_tag_alert) |
  (|icache_data_alert);` (line 1141) — under `ICache=0` both reduce
  to 0.
- Final 3 alert OR-trees (lines 1143-1147):
  `alert_major_internal_o = core_alert_major_internal |
  lockstep_alert_major_internal | icache_alert_major_internal`,
  same shape for `_bus` and `_minor`. Under `ICache=0`/`Lockstep=0`
  these collapse to `alert_*_o = core_alert_*`.

## Out of scope

Per the project plan and the SoC pin matrix, the following collapse
under our pins to either constant ties or upstream-SV black boxes
that we do not port:

- **`ibex_lockstep` instance (lines 993-1102)** — gated on `if
  (Lockstep)` which is `SecureIbex=0` ⇒ `Lockstep=0`. Project plan:
  "stays upstream forever." The `gen_lockstep` arm's entire
  buffer-rail (`buf_in`/`buf_out`, the per-way `prim_buf u_*`
  instances, the 3 `prim_buf u_prim_buf_alert_*` cells, lines
  784-1118) is therefore unreachable. Under `Lockstep=0` we emit
  the `gen_no_lockstep` ties only.
- **`ibex_register_file_fpga` (line 484)** and
  **`ibex_register_file_latch` (line 506)** — non-FF regfile
  variants. Project plan: "stays upstream forever." Under
  `RegFile=RegFileFF` only the `gen_regfile_ff` arm (line 462)
  emits; the other two arms are dead `genif` branches.
- **`prim_ram_1p_scr` / `prim_ram_1p` (lines 600-746)** — guarded by
  `if (ICache)`. With `ICache=0` we emit `gen_norams` ties only.
  These RAMs become relevant in Phase D (icache port).
- **`prim_secded_inv_39_32_dec` (lines 1374, 1383)** — sim-only
  decoders inside `` `ifdef INC_ASSERT `` + `if (MemECC)`. Both
  guards false; out of scope.
- **`prim_buf u_prim_buf_data_wdata_intg` (line 775)** — inside
  `if (MemECC) gen_mem_wdata_ecc`. Under `MemECC=0` we emit
  `data_wdata_intg_o = '0`; this `prim_buf` is unreachable.
- **All `prim_buf` cells inside `if (Lockstep)`** (lines 972-988,
  1104-1117) — unreachable under `Lockstep=0`.
- **The `gen_scramble` arm's flop bank** (lines 534-561,
  `scramble_key_q`, `scramble_nonce_q`, `scramble_key_valid_q`,
  `scramble_req_q` flops) — unreachable under `ICacheScramble=0`.
- **dummy_instr seed flop chain** — `DummyInstructions =
  SecureIbex = 0` lifts all dummy-instr LFSR/seed paths out of
  `ibex_top`; the `dummy_instr_id`/`dummy_instr_wb` wires from
  `u_ibex_core` (lines 376-377) propagate to `register_file_i`
  (lines 473-474) but are guaranteed 0 by the inner core.
- **All `` `ifdef RVFI `` ports (lines 120-159 and 410-449)** — the
  SoC build does not define `RVFI`. The `ibex_top_tracing` wrapper
  layered above us also does not propagate RVFI ports out of
  `ibex_mini_soc.sv` (line 548 reads `u_ibex.rvfi_pc_rdata` via
  hierarchical reference, not via the port boundary). C2's IbexTop
  port list omits the RVFI block to match.
- **All `` `ifdef INC_ASSERT `` blocks** (lines 674-702, 1178-1342)
  — sim-only SVA tracking. Not synthesizable; ARCH does not model
  SVAs in this proposal.
- **Module-level `` `ASSERT_KNOWN `` / `` `ASSERT `` calls** (lines
  1150-1174, 1344-1391) — sim-only.
- **`scan_rst_ni` DFT bypass** (line 169) — the port is in our list
  for SoC binding compatibility but is sunk via `unused_scan`
  (line 1135) since it only matters under `Lockstep=1`.
- **`test_en_i`** — wired into both `core_clock_gate_i` (test-mode
  clock-gate bypass) and `register_file_i` (line 472). Plain
  pass-through; no ARCH logic needed beyond port routing.
- **`prim_secded_pkg::SecdedInv3932ZeroWord`** — used by the
  upstream `WordZeroVal` param expression
  `RegFileDataWidth'(prim_secded_pkg::SecdedInv3932ZeroWord)` (line
  467). Under `RegFileDataWidth = 32` and `RegFileECC = 0`, the
  word-zero pattern is functionally irrelevant (it only matters
  when an attacker reads through the ECC layer). See **Risks §3**
  for the param-default expression handling.
- **The `ibex_top_tracing` wrapper** (where the SoC's `u_ibex`
  binds) — out of scope. C2 ports `ibex_top` itself; the
  `_tracing` shim around it is upstream-SV and stays. The
  conftest's swap-shadow logic targets `build/ibex_top.sv`, which
  the tracing wrapper instantiates by name.

## Construct enumeration

Required per `feedback_proposal_construct_enumeration.md`. One row
per ARCH first-class construct (per arch-com `ARCH_HDL_Specification`
§8-§12 + `pipeline`). C2 is structurally simpler than C1: most
constructs are N/A because `ibex_top` is glue, not a CPU body.

| Construct           | Status | Reason |
|---------------------|--------|--------|
| `module`            | **picked (primary)** | `ibex_top` IS a plain `module` — no stage decomposition, no FSM, no walker. The body is two `inst`s (IbexCore + IbexRegisterFileFf), two upstream-SV `inst`s (`prim_clock_gating` + `prim_buf`), one tiny `core_busy_q` flop, and a pile of constant-tied outputs and combinational glue. Unlike C1 (a `pipeline`), C2 has no pipelined behaviour at this scope. |
| `pipeline`          | **rejected** | The pipeline is **inside** `IbexCore` (C1, just merged). At the `ibex_top` scope every output is a function of the current cycle's inputs, the `core_busy_q` flop, or a sub-module output. There is no architectural stage at this layer. |
| `inst`              | **picked (heavily)** | Two ARCH instances (`u_ibex_core: IbexCore`, `register_file_i: IbexRegisterFileFf`) + two upstream-SV instances (`core_clock_gate_i: prim_clock_gating`, `u_fetch_enable_buf: prim_buf`). The SV-from-ARCH-`module`-scope `inst` shape is well-trodden (B4 used it for `ibex_cs_registers`, A6 has SV cells inside multdiv). Fewer integration questions than C1's SV-from-pipeline-stage variant. |
| `fsm`               | **rejected** | No state machine outside sub-modules. The only state at `ibex_top` scope is `core_busy_q` (4-bit mubi flop) which is a value-passing register, not an FSM. |
| `thread`            | **rejected** | Per `feedback_thread_single_state_idiom.md`, `thread` is for `do { ... } until cond;` walkers. `ibex_top` has no walker; all logic is reactive (every output a function of the current cycle's inputs / sub-module outputs / `core_busy_q`). Per the same memory entry, even a single-state thread would be a `seq` block in disguise — and we have nothing of that shape either. |
| `pipe_reg`          | **rejected** | No fixed-shift pipeline registers at this scope. |
| `fifo`              | **rejected** | No queueing. (The IF stage's prefetch FIFO is internal to `IbexCore`.) |
| `ram`               | **N/A** | Address-indexed storage exists at this scope only inside `if (ICache) gen_rams` (lines 600+); under `ICache=0` we emit `gen_norams` ties. The icache RAMs are deferred to Phase D. The regfile is **not** a `ram` (see `regfile` row). |
| `cam`               | **N/A** | No content-addressable lookup. |
| `linklist`          | **N/A** | No pointer-chained storage. |
| `regfile`           | **rejected (do NOT re-pick)** | The GPR file is `IbexRegisterFileFf` (A2, already ported). C2 instantiates it via `inst register_file_i: IbexRegisterFileFf { ... };`; the regfile primitive itself stays put. |
| `arbiter`           | **rejected** | No request/grant arbitration at this scope. |
| `bus`               | **assess → rejected for C2** | The OBI instr/data interfaces (`instr_*_i/o`, `data_*_i/o`, ~16 wires total at the IbexTop boundary) are the textbook candidate for a `bus typedef BusObi { req; gnt; rvalid; we; addr; ... };`. **Decided against** for C2: a `BusObi.archi` stub already exists in `src/` (likely from a prior exploration), but adopting it now means re-cutting the merged port shapes of `IbexCore.arch` (C1) and the SoC's `ibex_mini_soc.sv` binding. C2's value is the SoC-boundary swap, not a port-shape refactor. **Documented as a future follow-on** alongside the analogous C1 deferral of `bus` for the LSU/IF channels. |
| `handshake_channel` | **rejected** | The OBI req/gnt/rvalid handshake at the IbexTop port boundary is a candidate, but for the same reason as `bus`: lifting it now requires re-port-ing C1's IbexCore, which is just-merged. Defer. |
| `synchronizer`      | **N/A** | Single clock domain (`clk_i` ⇒ gated `clk` ⇒ everything inside). The `core_clock_gate_i` produces a gated **version** of the same clock, not a new domain. No CDC. |
| `clkgate`           | **rejected (use upstream-SV `inst`)** | `prim_clock_gating core_clock_gate_i` (line 282) is a true clock-gate — its output `clk` drives every internal flop including `u_ibex_core.clk_i` and `register_file_i.clk_i` (lines 353, 469). ARCH **does** have a `clkgate` first-class concept (per the construct catalog), but using it here would require either (a) ARCH lowering an explicit clock-gate primitive that emits `prim_clock_gating` — which the framework does not do today — or (b) hand-modeling the gate as `clk_o = clk_i & en_i`, which is wrong for ASIC synthesis (gates need a latch on `en`). **Cleanest path: keep `prim_clock_gating` as an upstream-SV `inst` against a hand-written `.archi` stub.** Same disposition as the `prim_buf` cell. |
| `counter`           | **rejected** | No counters at this scope. (Performance counters live inside `ibex_cs_registers` via `IbexCounter` instances; `ibex_top` doesn't see them.) |

## Module structure (proposed IbexTop.arch shape)

```
domain SysDomain
  freq_mhz: 100
end domain SysDomain

use IbexPkg;                  // for ibex_mubi_t, IbexMuBiOff, RV32MFast etc.
// (no IbexCoreSharedPkg needed at top — those types are internal to IbexCore)

module IbexTop
  // -- params (1:1 mirror of upstream ibex_top.sv lines 16-60) --
  param PMPEnable[0:0]:           const = 1'd0;
  param PMPGranularity:           const = 0;
  param PMPNumRegions:            const = 4;
  param MHPMCounterNum:           const = 0;
  param MHPMCounterWidth:         const = 40;
  param RV32E[0:0]:               const = 1'd0;
  param RV32M:                    ibex_pkg::rv32m_e = ibex_pkg::RV32MFast;
  param RV32B:                    ibex_pkg::rv32b_e = ibex_pkg::RV32BNone;
  param RV32ZC:                   ibex_pkg::rv32zc_e = ibex_pkg::RV32ZcaZcbZcmp;
  param RegFile:                  ibex_pkg::regfile_e = ibex_pkg::RegFileFF;
  param BranchTargetALU[0:0]:     const = 1'd0;
  param WritebackStage[0:0]:      const = 1'd0;
  param ICache[0:0]:              const = 1'd0;
  param ICacheECC[0:0]:           const = 1'd0;
  param BranchPredictor[0:0]:     const = 1'd0;
  param DbgTriggerEn[0:0]:        const = 1'd0;
  param DbgHwBreakNum:            const = 1;
  param SecureIbex[0:0]:          const = 1'd0;
  param LockstepOffset:           const = 1;
  param MemECC[0:0]:              const = 1'd0;
  param MemDataWidth:             const = 32;
  param ICacheScramble[0:0]:      const = 1'd0;
  param DmBaseAddr[31:0]:         const = 32'h1A11_0000;
  param DmAddrMask[31:0]:         const = 32'h0000_0FFF;
  param DmHaltAddr[31:0]:         const = 32'h1A11_0800;
  param DmExceptionAddr[31:0]:    const = 32'h1A11_0808;
  param CsrMvendorId[31:0]:       const = 32'd0;
  param CsrMimpId[31:0]:          const = 32'd0;
  // (RndCnst* + PMPRst* + Scramble Key/Nonce: see Risks §4)

  local param Lockstep[0:0]:           const = 1'd0;   // = SecureIbex
  local param ResetAll[0:0]:           const = 1'd0;   // = Lockstep
  local param DummyInstructions[0:0]:  const = 1'd0;   // = SecureIbex
  local param RegFileECC[0:0]:         const = 1'd0;
  local param RegFileLockstepECC[0:0]: const = 1'd0;   // = Lockstep
  local param RegFileDataWidth:        const = 32;
  local param RegFileDataEccWidth:     const = 39;
  local param BusSizeECC:              const = 32;     // BUS_SIZE
  // ... TagSizeECC, LineSizeECC, NumAddrScrRounds (all 0 / pin defaults)

  // -- ports: 1:1 mirror of ibex_top.sv lines 62-185, MINUS the
  --        `ifdef RVFI` block --
  // (see "Port matrix" below — 50+ ports)

  // -- internals --
  wire clk: Clock<SysDomain>;
  reg core_busy_q: ibex_mubi_t;     // 4-bit mubi flop
  wire core_busy_d: ibex_mubi_t;    // from u_ibex_core.core_busy_o
  wire clock_en: Bool;
  wire irq_pending: Bool;
  wire dummy_instr_id: Bool;
  wire dummy_instr_wb: Bool;
  wire rf_raddr_a: UInt<5>;
  wire rf_raddr_b: UInt<5>;
  wire rf_waddr_wb: UInt<5>;
  wire rf_we_wb: Bool;
  wire rf_wdata_wb: UInt<RegFileDataWidth>;
  wire rf_rdata_a: UInt<RegFileDataWidth>;
  wire rf_rdata_b: UInt<RegFileDataWidth>;
  wire fetch_enable_buf: ibex_mubi_t;
  wire core_alert_minor: Bool;
  wire core_alert_major_internal: Bool;
  wire core_alert_major_bus: Bool;
  // (icache + scramble locals — all tied off under our pins)

  // -- core_busy_q flop (g_clock_en_non_secure arm, lines 267-273) --
  seq on clk_i
    reset rst_ni => core_busy_q <= IbexMuBiOff;
    core_busy_q <= core_busy_d;
  end seq

  comb
    clock_en   = core_busy_q[0] | debug_req_i | irq_pending | irq_nm_i;  // line 274
    core_sleep_o = ~clock_en;                                            // line 280
  end comb

  // -- main clock-gate (upstream-SV inst against prim_clock_gating.archi) --
  inst core_clock_gate_i: prim_clock_gating {
    clk_i,
    en_i      <- clock_en,
    test_en_i,
    clk_o     -> clk
  };

  // -- fetch_enable buffer (upstream-SV inst against prim_buf.archi) --
  inst u_fetch_enable_buf: prim_buf<Width = 4> {
    in_i  <- fetch_enable_i,
    out_o -> fetch_enable_buf
  };

  // -- IbexCore (C1 ARCH inst) --
  inst u_ibex_core: IbexCore<...all params, see below...> {
    clk_i  <- clk,
    rst_ni,
    hart_id_i,
    boot_addr_i,
    instr_req_o, instr_gnt_i, instr_rvalid_i, instr_addr_o,
    instr_rdata_i  <- instr_rdata_core,
    instr_err_i,
    data_req_o,  data_gnt_i,  data_rvalid_i,
    data_we_o,   data_be_o,   data_addr_o,
    data_wdata_o <- data_wdata_core,
    data_rdata_i <- data_rdata_core,
    data_err_i,
    dummy_instr_id_o   -> dummy_instr_id,
    dummy_instr_wb_o   -> dummy_instr_wb,
    rf_raddr_a_o       -> rf_raddr_a,
    rf_raddr_b_o       -> rf_raddr_b,
    rf_waddr_wb_o      -> rf_waddr_wb,
    rf_we_wb_o         -> rf_we_wb,
    rf_wdata_wb_ecc_o  -> rf_wdata_wb,
    rf_rdata_a_ecc_i   <- rf_rdata_a,
    rf_rdata_b_ecc_i   <- rf_rdata_b,
    ic_*_o, ic_*_i, ic_scr_key_*  <- icache tieoffs (see Risks §6),
    irq_software_i, irq_timer_i, irq_external_i, irq_fast_i, irq_nm_i,
    irq_pending_o      -> irq_pending,
    debug_req_i,
    crash_dump_o,
    double_fault_seen_o,
    fetch_enable_i     <- fetch_enable_buf,
    alert_minor_o      -> core_alert_minor,
    alert_major_internal_o -> core_alert_major_internal,
    alert_major_bus_o  -> core_alert_major_bus,
    core_busy_o        -> core_busy_d
  };

  // -- IbexRegisterFileFf (A2 ARCH inst, gen_regfile_ff arm only) --
  inst register_file_i: IbexRegisterFileFf<
      RV32E             = RV32E,
      DataWidth         = RegFileDataWidth,
      DummyInstructions = DummyInstructions,
      WordZeroVal       = 0> {                  // see Risks §3
    clk_i             <- clk,
    rst_ni,
    test_en_i,
    dummy_instr_id_i  <- dummy_instr_id,
    dummy_instr_wb_i  <- dummy_instr_wb,
    raddr_a_i  <- rf_raddr_a,  rdata_a_o -> rf_rdata_a,
    raddr_b_i  <- rf_raddr_b,  rdata_b_o -> rf_rdata_b,
    waddr_a_i  <- rf_waddr_wb, wdata_a_i <- rf_wdata_wb,
    we_a_i     <- rf_we_wb
  };

  // -- mem-data-merge glue (gen_non_mem_rdata_ecc + gen_no_mem_ecc) --
  comb
    // gen_non_mem_rdata_ecc, lines 301-302 + 307-310:
    data_rdata_core    = data_rdata_i;          // MemDataWidth=32
    instr_rdata_core   = instr_rdata_i;
    let unused_intg = ^{instr_rdata_intg_i, data_rdata_intg_i};
    // gen_no_mem_ecc, lines 779-780:
    data_wdata_o       = data_wdata_core;        // MemECC=0 ⇒ no slice
    data_wdata_intg_o  = 0;
  end comb

  // -- gen_norams ties (lines 753-770) --
  comb
    ram_cfg_rsp_icache_tag_o  = 0;
    ram_cfg_rsp_icache_data_o = 0;
    ic_tag_rdata              = 0;     // unpacked Vec, broadcast 0
    ic_data_rdata             = 0;
    icache_tag_alert          = 0;
    icache_data_alert         = 0;
    let unused_ram_cfg = ...;          // xor sinks per upstream
    let unused_ram_inputs = ...;
  end comb

  // -- gen_noscramble ties (lines 568-583) --
  comb
    scramble_req_o       = false;
    // scramble_key_q / nonce_q / valid_q: declared but tied
    let unused_scramble_inputs = ...;  // big xor sink, line 570
  end comb

  // -- gen_no_lockstep ties (lines 1119-1136) --
  comb
    lockstep_alert_major_internal = false;
    lockstep_alert_major_bus      = false;
    lockstep_alert_minor          = false;
    lockstep_cmp_en_o             = IbexMuBiOff;
    data_req_shadow_o, data_we_shadow_o, data_be_shadow_o,
    data_addr_shadow_o, data_wdata_shadow_o,
    data_wdata_intg_shadow_o      = 0;
    instr_req_shadow_o, instr_addr_shadow_o = 0;
    let unused_scan = scan_rst_ni;     // line 1135
  end comb

  // -- final alert OR-trees (lines 1141-1147) --
  comb
    icache_alert_major_internal = (|icache_tag_alert) | (|icache_data_alert);  // = 0
    alert_major_internal_o = core_alert_major_internal
                           | lockstep_alert_major_internal
                           | icache_alert_major_internal;
    alert_major_bus_o      = core_alert_major_bus | lockstep_alert_major_bus;
    alert_minor_o          = core_alert_minor      | lockstep_alert_minor;
  end comb

  // -- core_busy_q's unused upper-3 mubi bits (line 277) --
  comb
    let unused_core_busy = ^core_busy_q[3:1];
  end comb

end module IbexTop
```

The above is **structural sketch only** — final spec / tests /
implementation are downstream of this proposal.

## Hazard handling

There are **no new hazards** at the `ibex_top` scope. C2 is structural
glue: every output of `ibex_top` is either (a) a passthrough from
`u_ibex_core` / `register_file_i`, (b) a constant tieoff, (c) a
1-cycle-delayed version of `core_busy_d` via the `core_busy_q` flop,
or (d) a small combinational reduction (alert OR-trees, the
`clock_en` OR, the mem-data merge).

The one timing subtlety worth flagging:

- **`core_busy_q` reset value.** Upstream's non-secure flop (lines
  267-273) resets to `IbexMuBiOff`. Out of reset, `core_busy_q[0] =
  0` ⇒ `clock_en = debug_req_i | irq_pending | irq_nm_i`. With all
  three IRQ/debug inputs low at reset, `clock_en = 0` ⇒ the gated
  `clk` is dead from cycle 0. The first thing that wakes the gate
  is `u_ibex_core` asserting `core_busy_d != IbexMuBiOff` — but
  that requires `clk` to be ticking inside `u_ibex_core` to drive
  any `if_busy`/`ctrl_busy`/`lsu_busy` reduction... **wait, no:**
  the upstream FSM relies on the regfile + core flops being on the
  *gated* clock, but `core_busy_q` itself is on **`clk_i`**
  (ungated, line 267) — which is the entire point of the
  non-secure form: the busy flop is always running, so a single
  combinational kick from any IRQ pin or `debug_req_i` releases the
  gate. The ARCH translation must keep `core_busy_q`'s `seq on
  clk_i`, NOT `seq on clk`. Worth flagging in the implementer
  prompt.

## Risks / open questions

1. **`prim_clock_gating.archi` and `prim_buf.archi` need
   hand-writing.** Both are tiny (4 pins / 2 pins respectively),
   stable, and parameterized by a single `Width`. Same approach as
   B4's `ibex_cs_registers.archi` (already in `src/`). The
   `prim_buf` stub needs `param Width: const = 1` so the IbexTop
   instance can pass `Width = 4` for the `fetch_enable_buf`. The
   `prim_clock_gating` cell has no params (always 1-bit `clk`/`en`).
   No arch-com extension needed.

2. **`core_busy_q` is a 4-bit mubi async-low-reset flop.** Two
   options: (a) plain `reg` with `reset rst_ni => IbexMuBiOff;`
   inside a `seq on clk_i` block, or (b) instantiate `prim_flop`
   (line 254 secure form) as upstream-SV `inst`. Under our pins the
   secure-form flop is dead anyway (the `g_clock_en_secure` arm
   doesn't emit). **Decision: option (a)** — plain `reg` + `seq` is
   the natural ARCH form, matches the lowering of the
   `g_clock_en_non_secure` `always_ff` block (lines 267-273), and
   avoids hand-writing a `prim_flop.archi` stub for a cell that
   only exists in the secure arm we're not emitting. Per
   `feedback_arch_syntax_pitfalls` rule #1, Vec/wide-bus reset uses
   scalar broadcast, but `IbexMuBiOff` is a 4-bit named constant
   from `ibex_pkg`; the reset clause `reset rst_ni =>
   IbexMuBiOff;` should work directly.

3. **`WordZeroVal` param in the regfile inst.** Upstream passes
   `RegFileDataWidth'(prim_secded_pkg::SecdedInv3932ZeroWord)` (line
   467) — a cross-package SV constant cast. Under
   `RegFileDataWidth=32` and `RegFileECC=0`, this value is
   functionally a don't-care: it's only ever read out of x0 (the
   hard-wired-zero register), and the consumer (the regfile read
   ports) doesn't do ECC checking. **Decision: pass `WordZeroVal =
   0`** at the IbexTop inst site. This diverges from upstream's
   bit-pattern but is observationally equivalent under our pins.
   Document this in the spec so a future ECC-enable swap re-visits
   it. **If this turns out to surface a Verilator equivalence
   diff** (e.g. an SVA in `register_file_ff.sv` checks the literal
   pattern) we'd need either a new arch-com extension to support
   cross-package const expressions in inst-site param values, or a
   `let WordZeroVal_value: UInt<32> = 32'h<literal>;` workaround at
   the IbexTop inst site. Current bet: not needed.

4. **`PMPRstCfg`, `PMPRstAddr`, `PMPRstMsecCfg`, `RndCnstLfsrSeed`,
   `RndCnstLfsrPerm`, `RndCnstIbexKey`, `RndCnstIbexNonce` —
   typed-array / typed-record param defaults.** These are upstream's
   "complex" param defaults: `PmpCfgRst` is `pmp_cfg_t [16]`,
   `PmpAddrRst` is `[33:0] [16]`, etc. (lines 21-23, 43-44, 50-51).
   The auto-emitted `src/ibex_core.archi` (line 39-43) shows the C1
   port stub already accepts these as `pmp_cfg_t [16]`,
   `UInt<34> [16]`, `pmp_mseccfg_t`, scalar consts. **At the IbexTop
   inst site we just pass them through as the same names.** No new
   const-expression evaluation needed at this scope (the values come
   from `ibex_pkg` which we `use` at file scope). Risk that arch-com
   doesn't yet accept `param X: pmp_cfg_t [16] = ibex_pkg::PmpCfgRst`
   syntax for the IbexTop param declaration itself; if so, a fallback
   is to inline-default to `0`-initialized arrays and let the SoC
   override at bind site. Watch for this in build.

5. **`ic_tag_rdata` / `ic_data_rdata` are unpacked Vec.** Per
   `feedback_arch_syntax_pitfalls` rule #5 + the C1 ic_*_rdata port
   shape (`src/ibex_core.archi` lines 76, 81 declares them as
   packed `Vec<UInt<TagSizeECC>, IC_NUM_WAYS>`), the IbexTop side
   must match. **Wait — the auto-emitted stub shows `Vec<UInt<W>,
   N>` without the `unpacked` modifier.** Upstream
   `ibex_top.sv` line 229, 234 declares them as `logic [W-1:0]
   x [IC_NUM_WAYS]` — SV unpacked array. C1 emitted them packed in
   the .archi stub. **Either the stub is wrong** (and the C1 SV
   emission is currently broken at this junction, manifesting only
   if `ICache=1`), **or** arch-com is silently emitting them
   unpacked despite the lack of an `unpacked` modifier in the
   stub, **or** this never gets exercised because under our pins
   both ports tie to 0. **Action**: spec extractor should verify
   how the C1 build emits these ports (read `build/ibex_core.sv`
   port list); the resulting IbexTop stub must match upstream's
   unpacked declaration to compile. If a fix is needed in the
   `ibex_core.archi` stub, that's a follow-up to C1, not C2.

6. **ICache port wiring under `ICache=0`.** `gen_norams` (line 753)
   ties `ic_tag_rdata` / `ic_data_rdata` (the **internal** wires
   feeding back into `u_ibex_core.ic_tag_rdata_i` /
   `ic_data_rdata_i`) to 0. The IbexTop ports
   `ram_cfg_icache_tag_i`, `ram_cfg_rsp_icache_tag_o`,
   `ram_cfg_icache_data_i`, `ram_cfg_rsp_icache_data_o` (lines
   68-71) are SoC-boundary ports that the SoC binds to
   `prim_ram_1p_pkg::RAM_1P_CFG_DEFAULT` / unconnected (SoC lines
   480-483). The `unused_ram_cfg = |{...};` xor-sink (line 758)
   absorbs the input cfgs; `ram_cfg_rsp_*_o = '0` drives the
   outputs. ARCH translation: `let unused_ram_cfg = |...;` and
   `ram_cfg_rsp_*_o = 0;` in `comb`. The `ram_1p_cfg_t` /
   `ram_1p_cfg_rsp_t` struct types (`prim_ram_1p_pkg`) need a `use`
   import; check they exist in arch-com's allowed-package list.

7. **`unused_*` xor-sink generation.** Upstream-SV uses `|{...}`
   reduction to lint-silence dead inputs (lines 310, 758, 761-763,
   570-574). ARCH equivalent: `let unused_x = |{...};` or
   `let unused_x = ^{...};` in `comb`. The B-series swaps already
   established the pattern; reuse it. Watch for the
   `feedback_arch_syntax_pitfalls` rule #13 caveat: bare `let foo =
   ...;` (no type) for fresh declarations of `unused_*`.

8. **Snake-case file basename.** Per `feedback_shared_types_package`
   (B5 lesson) and `feedback_arch_syntax_pitfalls` rule #8: the
   .arch source is `IbexTop.arch`, the build script emits
   `build/ibex_top.sv`. The conftest swap-shadow logic matches on
   basename equality with upstream. The SoC's
   `ibex_top_tracing #(...) u_ibex(...)` instance binds to
   `ibex_top` (the wrapper around our module), so the SV filename
   must be exactly `ibex_top.sv`.

9. **`Verilator` in doc comments.** Per
   `feedback_avoid_verilator_in_comments.md` (B2 lesson), don't
   use the literal capital-V `Verilator` in `///` doc comments —
   use lowercase `verilator` or `the simulator`. Bake into the
   implementer prompt.

10. **Param-default ternary `MemDataWidth = MemECC ? 39 : 32`.** Per
    `feedback_arch_syntax_pitfalls` rule #12, **`param MemECC[0:0]:
    const = 1'd0`** (the `[0:0]` form) lets us write ternaries
    directly. The auto-emitted `ibex_core.archi` (line 25) already
    uses `param MemDataWidth: const = 32` (i.e. const-folded under
    `MemECC=0`); IbexTop should follow the same approach — declare
    `MemDataWidth` as a `local param` with the const-folded value
    32, not as a ternary on `MemECC`. This matches `WriteBackStage`
    / `ICache` / etc. handling in the C1 stub.

## Verification gate

**Basic gate (blocking, must pass before READY.md):**

```
rm -rf build/
make build
pytest tests/test_ibex_top_unit.py     # swap-local Requirements
pytest tests/test_soc_lint.py
pytest tests/test_cpu_programs.py
```

The unit suite (`test_ibex_top_unit.py`) has one cocotb test per
spec Requirement. Per the spec-first methodology
(`feedback_spec_first_arch_blind`), the spec extractor will define
Reqs covering at minimum:

- Reset state: `core_busy_q = IbexMuBiOff`, `clock_en = 0`,
  `core_sleep_o = 1`.
- Wake on `irq_software_i`: `clock_en` rises combinationally;
  gated `clk` resumes.
- Wake on `debug_req_i`: same pattern.
- Wake on `irq_nm_i`: same pattern.
- `core_busy_d → core_busy_q` 1-cycle latency on `clk_i` (ungated).
- `data_wdata_intg_o = 0` always (under MemECC=0).
- `data_rdata_core[31:0] = data_rdata_i` direct passthrough.
- Regfile read/write address+data passthrough through the IbexTop
  scope (raddr_a/b → rdata_a/b round-trip).
- All `_shadow_o` / `lockstep_*_o` / `scramble_req_o` outputs are 0
  in steady state (under Lockstep=0, ICacheScramble=0).
- `alert_*_o` reduces to `core_alert_*` (lockstep & icache contribs
  are 0).

**Full SoC regression (blocking; per
`feedback_full_gate_before_ready`):**

```
rm -rf build/
make build
make test          # full SoC gate, all archived ISR programs + sanity
```

Per `feedback_full_gate_before_ready` (B1 lesson), this **must run
on a clean build/ tree** — `make build` short-circuits on first
error, so a leftover `build/ibex_top.sv` from a prior good run can
mask a current break. The 4 ISR programs from B4 (`timer_isr`,
`sw_isr`, `ext_isr`, `multictx_isr`) plus the `cpu_programs` sanity
suite are the integration-level gate; a green C1 unit suite is
necessary but not sufficient (per
`feedback_unit_tests_dont_catch_integration`).

**Parallel runner** (per `feedback_parallel_pytest`):
```
pytest -n auto --dist=loadfile tests/
```

**Phase C end-gate (deferred follow-on, NOT blocking C2):** per
`project_ibex_arch_plan.md`, Phase C end-gate adds **riscv-arch-tests
RV32IMC compliance** *after* C2 lands. C2 itself targets only the
standard SoC gate above. Compliance test integration is a separate
test-infrastructure workstream.

## Verification gate caveats

1. **`prim_clock_gating.sv` + `prim_buf.sv` stay upstream.** The
   build flow needs to copy these (and any vendor'd `prim_*` they
   transitively depend on) into the build tree alongside
   `build/ibex_top.sv`. Already in the upstream Ibex source tree
   under `vendor/lowrisc_ip/ip/prim_generic/rtl/`; the existing
   fusesoc filelist for `ibex_mini_soc` already includes them
   (because the upstream `ibex_top.sv` references them). When we
   swap `build/ibex_top.sv` in, those `prim_*.sv` files remain
   reachable through the same fusesoc path. **No new file copies
   needed.**

2. **`ibex_top_tracing` wrapper.** The SoC's `u_ibex` binds to
   `ibex_top_tracing` (SoC line 469), not directly to `ibex_top`.
   The tracing wrapper is upstream-SV; it instantiates `ibex_top`
   by name and passes the RVFI ports through to its own
   tracing-output infrastructure. Our `build/ibex_top.sv` must
   match the signature `ibex_top_tracing` expects from
   `ibex_top` — but **without the `` `ifdef RVFI `` ports**,
   because the SoC build does not define `RVFI` and therefore
   `ibex_top_tracing.sv` itself compiles with the same ports
   excluded. Sanity-check: `ibex_top_tracing` reads
   `u_ibex.rvfi_pc_rdata` (SoC line 548) only via hierarchical
   reference, which works regardless of port presence as long as
   the inner `ibex_core` exports the signal — which it does.

3. **`unused_*` ARCH-side handling.** ARCH's lint pass differs from
   Verilator's; the `unused_*` xor-sinks in upstream (lines 310,
   546, 570, 758, 1135) exist to silence Verilator's unused-input
   warnings. ARCH may already silence these via its own analysis;
   if not, the same `let unused_x = ^{...};` pattern that B-series
   used should work.

4. **Unpacked Vec ports.** The IbexTop port-boundary ports
   `ram_cfg_rsp_icache_tag_o` and `ram_cfg_rsp_icache_data_o` are
   declared in upstream as `prim_ram_1p_pkg::ram_1p_cfg_rsp_t
   [IC_NUM_WAYS-1:0]` (line 69) — that's a packed Vec of struct,
   not unpacked. Confirm with the auto-emitted `IbexCore` stub
   shape; the IbexTop ports must use the same packing
   (IC_NUM_WAYS=2 by default, struct type imported from
   `prim_ram_1p_pkg`).

## Reference

- **Upstream**: `~/github/ibex/rtl/ibex_top.sv` (1394 LoC; ~250
  effective under SoC pinning, after subtracting the
  `if (Lockstep)` arm (~330 LoC), the `if (ICache)` arm (~150 LoC),
  the `if (ICacheScramble)` arm (~30 LoC), the `if (RegFile ==
  RegFileFPGA / RegFileLatch)` arms (~45 LoC each), the
  `` `ifdef RVFI `` ports (~40 LoC), the `` `ifdef INC_ASSERT ``
  blocks (~170 LoC), and the module-level `` `ASSERT_KNOWN ``
  calls (~25 LoC).)

- **C1 IbexCore (predecessor)**: PR #9 merged 2026-05-04. Archive at
  `changes/archive/2026-05-04-port-ibex_core/` (proposal as
  template; spec; tests-inventory; tasks). C1 demonstrated:
  - ARCH `pipeline` on a real CPU body (4 stages: IF/ID/EX/WB).
  - Cross-stage references, hazard composition.
  - SV-from-pipeline-stage `inst` (for `ibex_cs_registers`).
  - File-scope `pipeline` + module-scope `comb` glue coexistence.

- **C1 port stub (auto-emitted)**: `src/ibex_core.archi` (137
  lines) — reflects the C1-merged port shape including typed-value
  params (arch-com #286/#288).

- **A2 IbexRegisterFileFf**: `src/IbexRegisterFileFf.arch` (port
  stub at `src/ibex_register_file_ff.archi`, 19 lines).

- **B4 SV-from-ARCH-`module`-scope `inst` precedent**:
  `src/ibex_cs_registers.archi` (hand-written stub, used inside
  `IbexController.arch` and now `IbexCore.arch`).

- **Stays upstream-SV (per project plan)**:
  `~/github/ibex/rtl/ibex_register_file_fpga.sv`,
  `~/github/ibex/rtl/ibex_register_file_latch.sv`,
  `~/github/ibex/rtl/ibex_lockstep.sv`,
  `~/github/ibex/rtl/ibex_pmp.sv`,
  `~/github/ibex/rtl/ibex_cs_registers.sv`,
  `~/github/ibex/vendor/lowrisc_ip/ip/prim_generic/rtl/prim_clock_gating.sv`,
  `~/github/ibex/vendor/lowrisc_ip/ip/prim_generic/rtl/prim_buf.sv`,
  `~/github/ibex/vendor/lowrisc_ip/ip/prim_generic/rtl/prim_flop.sv`,
  `~/github/ibex/vendor/lowrisc_ip/ip/prim_generic/rtl/prim_ram_1p.sv`,
  `~/github/ibex/vendor/lowrisc_ip/ip/prim_generic/rtl/prim_ram_1p_scr.sv`.

- **SoC binding point**: `soc/ibex_mini_soc.sv` line 469
  (`ibex_top_tracing #(...) u_ibex(...)`). The conftest's
  swap-shadow logic targets `build/ibex_top.sv`; the
  `_tracing` wrapper instantiates `ibex_top` by name.

- **Project plan**:
  `~/.claude/projects/-Users-<user>-github-arch-com/memory/project_ibex_arch_plan.md`
  (Phase C: C1 IbexCore + C2 IbexTop; Phase C end-gate adds
  riscv-arch-tests RV32IMC compliance after C2).

- **Memory inputs consulted**:
  - `feedback_proposal_construct_enumeration.md` — required table
    above.
  - `feedback_arch_syntax_pitfalls.md` — Vec reset, indexed-LHS,
    reset polarity, unpacked Vec ports, param ternary, `use Pkg;`
    placement, "Verilator" in comments.
  - `feedback_thread_single_state_idiom.md` — why `thread` is
    rejected for ibex_top (no walker; no single-state idiom either;
    body is plain reactive `comb` + one `seq` flop).
  - `feedback_spec_first_arch_blind.md` — spec extractor + test
    writer + implementer are isolated agents.
  - `feedback_full_gate_before_ready.md` — `rm -rf build/` before
    READY.md.
  - `feedback_parallel_pytest.md` — `pytest -n auto
    --dist=loadfile`.
  - `feedback_unit_tests_dont_catch_integration.md` — green unit
    suite is necessary but not sufficient.
  - `feedback_shared_types_package.md` — keep CamelCase
    `IbexTop.arch` source; let build script emit
    `build/ibex_top.sv`.
  - `feedback_avoid_verilator_in_comments.md` — lowercase
    `verilator` only.

- **ARCH HDL spec sections relevant to C2**:
  - §2 (`module` / file-scope structure)
  - §3.6 (`unpacked` Vec port modifier)
  - §8-§12 (first-class construct catalog used for the enumeration
    table)
  - `clkgate` / `prim_clock_gating` integration discussion (held in
    the `arch-com` design notes — see Risks §1).
