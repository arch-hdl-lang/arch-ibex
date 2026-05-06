# Proposal: Port `ibex_pmp` to ARCH (D2)

## Intent

D2 ports `ibex_pmp.sv` (263 LoC upstream) to `src/IbexPmp.arch`. PMP
is a pure combinational permission-check module that takes a CSR-
supplied region table and per-channel access requests, and emits a
per-channel "access denied" signal. No clock, no reset, no state.

D2 is the **second swap of Phase D** and the first arch-ibex port of
a module that lives behind a SoC-disabled `if (PMPEnable)` block.
Under the SoC's current pinning (`PMPEnable=0`, set in `IbexTop.arch:40`)
PMP is not instantiated — `g_no_pmp` ties off the per-channel error
output to 0. **D2 ports the module standalone**; flipping
`PMPEnable=1` in the SoC is deferred to a follow-up swap (D2-flip,
mirrors the D1 pattern).

D2's value is exercising the new WORKFLOW.md checkpoints (ambiguity
resolutions, construct compliance audit, cross-scenario tests) on a
small, well-bounded module while D1's lessons are fresh.

## Scope

**In scope** — pinned to the values flowing through `IbexTop.arch`
to the SoC's `ibex_top_tracing` instantiation:

- `DmBaseAddr = 32'h0000_0000` (SoC override, `ibex_mini_soc.sv:472`)
- `DmAddrMask = 32'h0000_0003` (SoC override, `ibex_mini_soc.sv:473`)
- `PMPGranularity = 0` (default, no NAPOT restriction)
- `PMPNumChan = 3` (overridden in `ibex_core.sv:177` via `localparam` — channels: `PMP_I` instruction fetch addr, `PMP_I2` fetch addr + 2 for unaligned-32-bit upper halfword, `PMP_D` data load/store addr; the module's default of 2 is unused in this SoC)
- `PMPNumRegions = 4` (default, 4 PMP regions)

The standalone module-port does NOT depend on `PMPEnable`; the
module behaves the same whether instantiated or not.

**Out of scope:**
- SoC integration (flipping `PMPEnable=1`) — separate follow-up.
- Larger `PMPNumRegions` (8, 16) — fixed at 4 per SoC.
- ePMP non-default `mseccfg` settings beyond what the existing CSR
  file exposes — the ARCH module accepts the input, doesn't validate.
- Coverage macros (`dv_fcov_macros.svh`) — vendor-only.

## Construct enumeration

Per `feedback_proposal_construct_enumeration.md`. PMP is a pure
combinational permission checker; constructs that require state or
sequencing don't fit.

| Construct        | Status | Reason |
|------------------|--------|--------|
| `module`         | **picked** | Outer wrapper. Body is `comb` only — per-region match logic, per-channel permission AND, MML/lockdown rules, output denial OR. |
| `fsm`            | rejected | No state machine — pure combinational. |
| `thread`         | rejected | No multi-cycle sequencing. |
| `fifo`           | N/A    | No queue. |
| `ram`            | N/A    | No memory. |
| `cam`            | rejected | The PMP region match looks like associative lookup but doesn't fit `cam`'s shape — multiple regions can match a single addr (priority by lowest region index per RISC-V spec); `cam`'s `search_first` would also work but the policy and per-region permission AND-mask are simpler as a flat `comb` Vec reduction. |
| `linklist`       | N/A    | No pointer chain. |
| `regfile`        | N/A    | The PMP region table is CSR-driven — supplied as inputs by `ibex_cs_registers`, not stored locally. |
| `arbiter`        | N/A    | No request-grant arbitration. |
| `counter`        | N/A    | No count primitive. |
| `pipeline`       | N/A    | No pipelining. |
| `synchronizer`   | N/A    | Single clock domain. |
| `clkgate`        | N/A    | No clock at all. |

D2 exercises **typed-value `param`s + struct ports** (the
`pmp_cfg_t` / `pmp_mseccfg_t` / `pmp_req_e` / `priv_lvl_e` types) on
a clean small surface. These were lightly exercised in C2 IbexTop;
D2 uses them in the central role of a module's interface.

## Spec ambiguity resolutions

The spec extractor flagged 5 ambiguities (`spec.md §A1-A5`); each
has a `> Resolution:` line in the spec. The proposal commits to
each resolution here so the test author + arch implementer cite
ONE table:

| Ambiguity (spec §) | Picked reading | Rationale |
|---|---|---|
| **A1** MML retroactive reinterpretation of locked regions | match upstream — MML re-reads all region L/R/W/X bits on the cycle MML is set, no latch in PMP module | Upstream behaviour; CSR-side sticky/RLB protections handled by `ibex_cs_registers`, not PMP |
| **A2** Non-contiguous `DmAddrMask` — debug bypass window shape | SoC pinning is `DmAddrMask=0x3` (contiguous); use literal masked-equality `(addr & ~DmAddrMask) == DmBaseAddr` formula in code, but spec body covers only contiguous case | Out-of-scope masks would force a different test surface; pinning closes the gate |
| **A3** PMPGranularity=0 NAPOT degenerate case (no size bits set → 4-byte region) | implement the literal `~&csr_pmp_addr_i[r][b-1:2]` rule exactly; degenerate region is by-construction 4 bytes | Matches upstream; no special-case branch needed |
| **A4** `csr_pmp_mseccfg_i.rlb` unused at module boundary | model the field for type-shape compat; mark unused inside IbexPmp.arch with a doc comment | Dropping the field would break `pmp_mseccfg_t` interop with `ibex_cs_registers` |
| **A5** `pmp_req_e == 2'b11` reserved encoding | match upstream — reserved encoding yields denied (unless debug bypass); no assertion | Consumer never drives this; failure-safe is denied |

Test author and arch implementer cite this table, NOT the spec's
`§ Spec ambiguities flagged` punt list.

## Approach

1. **Type modeling.** Define `priv_lvl_e`, `pmp_cfg_t`,
   `pmp_mseccfg_t`, `pmp_req_e` as ARCH typedefs — local to
   `IbexPmp.arch` if no other ARCH consumer needs them, else
   extracted to `IbexCoreSharedPkg.arch`. Initial pick: local, since
   no other arch swap has needed them under PMPEnable=0.

2. **Body shape.** One `module IbexPmp` with one `comb` block. The
   block computes `region_match`, `region_perm_check`,
   `access_fault_check_res`, `debug_mode_allowed_access`,
   `pmp_req_err_o` per channel. No `seq`, no `reg`.

3. **Vec-of-struct unpacked ports.** `csr_pmp_cfg_i: in unpacked
   Vec<pmp_cfg_t, PMPNumRegions>`, similar for the other unpacked
   ports. Match the upstream port shape; the consumer (`ibex_core`)
   already drives them as unpacked SV arrays.

4. **Per-region match logic.** Three sub-modes (TOR / NA4 / NAPOT)
   plus OFF. Implement as a flat `comb` over indexed Vec elements
   (no `for` generate — straight per-region expressions; with
   `PMPNumRegions=4` this is 4 small unrolled checks).

## Tests

Per the new workflow:

- **Per-Requirement basic suite** — one test per RFC-2119 MUST in
  the spec. Estimated 8-12 tests (region match for each mode, plus
  permission rules, MML rules, debug-mode bypass, OFF region).
- **Cross-scenario integration tests** — combinations:
  - Locked region + M-mode access (lock semantics differ for M-mode
    pre-MML vs post-MML).
  - Multiple regions matching the same address (lowest-idx wins).
  - Granularity != 0 with NAPOT (address-mask interaction).
  - Debug-mode access overriding lockdown.
- **No `boot_during_cold_init` test** — PMP isn't a fetch-path
  module; it's a downstream check. The fetch-path equivalent ("PMP
  decision arrives in time for the IF-stage's bus request") is a
  multi-module integration concern, not a PMP unit test.

## Risks

1. **First arch-ibex use of struct-typed unpacked Vec ports.**
   `unpacked Vec<pmp_cfg_t, 4>` may surface arch-com codegen issues
   around struct serialization at port boundaries. C2 used `unpacked
   Vec<UInt<W>, N>` (no struct payload). Mitigation: write a small
   smoke first if the arch-implementer hits issues.

2. **`priv_lvl_e` enum at port boundary.** Encoded as `UInt<2>` in
   our types model, but upstream uses the typed enum. The consumer
   (`ibex_core`) would drive a typed enum value; cross-boundary
   interop may need `bits()` casting. Same shape as `pmp_req_e`.

3. **MML corner cases in spec.** Resolved at proposal stage (above)
   to "match upstream RISC-V ePMP" — but the test author still
   needs to enumerate the corner cases. Tests-inventory spot-check
   at orchestrator review.

4. **No SoC integration in D2.** The standalone port can compile
   + lint clean and pass unit tests, but won't actually be exercised
   by any CPU program. SoC-flip is deferred. The READY.md must be
   honest about this — D2's basic gate is unit suite + SoC lint
   (which stays unchanged), not CPU programs.

## Done when

- `src/IbexPmp.arch` builds and emits SV that lints under Verilator.
- All basic-suite tests pass (≥ 8 tests, exact count after spec).
- Cross-scenario tests pass (≥ 4 tests).
- SoC lint stays GREEN (PMP module is built but not instantiated).
- Background regression on `_unit_full.py` reports green.
- READY.md updated; change folder ready for archive.
