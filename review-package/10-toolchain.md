# 10 — Toolchain (TASK2)

Recorded 2026-09-03 on the machine that produced every number in this
package (macOS 25.6, Apple silicon). Branch `review-package`, created
from `claude/code-arch-instructions-7b4027` at `8c4b3ca` (= `main`).

## Tools present

| Tool | Version | Identity / path | Used in |
|---|---|---|---|
| Verilator | 5.048 (2026-04-26) | `/opt/homebrew/bin/verilator`, installed 2026-05-26 | lint, cocotb sims |
| Yosys | 0.67+post, git `b8e7da6f` | `/opt/homebrew/bin/yosys` (has `synth_ecp5`, `synth_sky130` help entries) | Phase 4, 5 |
| sv2v | 0.0.13 | `/opt/homebrew/bin/sv2v` | Phase 4 |
| OpenROAD | 26Q2-1287-g5894d0639d (local build, `~/github/OpenROAD`) | `~/.local/bin/openroad` | Phase 4.4 (needs ORFS, see below) |
| OpenSTA | 3.1.0 `6eb6911d30` (local build) | `~/OpenSTA/build/sta` (not on `PATH`) | Phase 4.3 |
| Python / cocotb / pytest / xdist | 3.13.9 / 2.0.1 / 8.4.2 / present | `/opt/homebrew/anaconda3/bin/python3` (the default `python3` 3.14 lacks cocotb) | Phase 2 |
| riscv64-elf-gcc | 15.2.0 | `/opt/homebrew/bin/riscv64-elf-gcc` | Phase 2 |
| fusesoc | 2.4.5 | `/opt/homebrew/anaconda3/bin/fusesoc` | file lists |
| sky130 PDK | `~/.volare/sky130A` (`sky130_fd_sc_hd`, tt_025C_1v80 lib), also `sky130B` | volare install | Phase 4 |
| Nangate45 | `~/pdks/nangate45` | ORFS platform sparse checkout | not used |
| Upstream Ibex | lowRISC/ibex `eede2fbbef007d53cafbd85d937b897751c40a54` (2026-04-10), shallow clone | `~/github/ibex` (`rtl/` clean, `syn/` locally modified) | both lanes |

## Decisions taken at the Phase 0 gate (repo owner, 2026-09-03)

| Decision | Choice |
|---|---|
| ARCH compiler pin | **v0.71.0 + two compiler fixes**: arch-com `fa4c864f0ef887254f210e17d997a9a186166a5e` = tag `v0.71.0` (`1a7d9fd7`, 2026-07-26) + `reports/arch_com_v0.71.0_stub_variant_fix.patch` (`ead3aa8f`, interface stubs exempt from variant-name mangling; Phase 1) + `reports/arch_com_v0.71.0_arbiter_valid_only_fix.patch` (`fa4c864f`, arbiter `valid_only` request channel keeps an internal ready wire; Phase 2). `arch --version` → `arch 0.71.0`. Rebuild: `git checkout v0.71.0 && git am <both patches> && cargo build --release`. |
| arch-com PR for the arbiter fix | [arch-hdl-lang/arch-com#994](https://github.com/arch-hdl-lang/arch-com/pull/994), branch `fix/arbiter-valid-only-ready` off `origin/main` `f4569890`: same change plus `test_arbiter_valid_only_request_channel_keeps_internal_ready`; local `cargo test --release` green; **CI: all checks passed**. |
| arch-com PR for the stub fix | [arch-hdl-lang/arch-com#993](https://github.com/arch-hdl-lang/arch-com/pull/993), branch `fix/stub-variant-mangling` (commit `a814dc62` on `origin/main` `f4569890`): same 12-line change plus regression test `test_interface_stub_not_variant_mangled`; local `cargo test --release` green (30 suites); **CI: all checks passed**. |
| Commit messages on `review-package` | plain descriptive messages, no AI-authorship trailer |
| ECP5 (Phase 5) | `nextpnr-ecp5` is **not installed** (owner confirmed); Phase 5 stays blocked unless it is installed later |
| sky130 P&R (Phase 4.4) | OpenROAD-flow-scripts is not present (`~/github/OpenROAD/test/orfs` is OpenROAD's Bazel test dir, not ORFS; no Docker image); a concrete install plan will be proposed when Phase 4.4 is reached |

## Tools missing (blockers for later phases)

| Tool | Needed by | Status |
|---|---|---|
| `nextpnr-ecp5` (+ `prjtrellis` DB, `ecppack`) | Phase 5 | Not installed. Homebrew has `nextpnr-ice40` and `prjtrellis` only, no `nextpnr-ecp5` formula; no oss-cad-suite install found. Options: build nextpnr from source against `brew install prjtrellis`, or install YosysHQ oss-cad-suite (macOS arm64 tarball). Either is a system-level install → needs your OK. |
| OpenROAD-flow-scripts (ORFS) | Phase 4.4 | Not present anywhere under `~`. The local OpenROAD binary exists, but ORFS (Makefile flow, `designs/sky130hd/ibex`, platform files) must be cloned; ORFS expects its own Yosys/OpenROAD builds and is not routinely supported on macOS. Needs your OK and likely >15 min of setup. |

## ARCH compiler candidates (Phase 0)

Method, per candidate: `git worktree add --detach <scratch>/arch-com-<tag> <tag>`,
`cargo build --release` (≈25–30 s each with cached crates), then in this
repo `git clean -fXq -- src/ build/`, `make build` (all 23 sources, in
dependency order), then `arch check` on each of the 23 files *after*
the build (so sibling `.archi` interface files exist), then
`pytest tests/test_soc_lint.py` to see whether the emitted SV
elaborates with the upstream tree under Verilator 5.048. Logs:
`<scratch>/phase0.log`, `<scratch>/phase0-sweep.log`,
`<scratch>/make-build-<tag>.log`, `<scratch>/check2-<tag>-<Module>.log`,
`<scratch>/soclint-<tag>.log`.

| Release / commit | arch-com commit | Date | `arch --version` | `make build` | `arch check` (23 files) | SoC elaborates (Verilator) |
|---|---|---|---|---|---|---|
| dev `2ffcc60b` (used in the first package) | `2ffcc60b` | 2026-05-14 | 0.70.0 | 23 / 23 | 23 / 23 | **yes** |
| dev `15735a77` (parent of the breaking commit) | `15735a77` | 2026-05-23 | 0.70.0 | 23 / 23 | 23 / 23 | **yes** |
| dev `9ba64352` "elaborate: variant discovery uses enclosing params for generate_if + rewrite_inst" | `9ba64352` | 2026-05-23 | 0.70.0 | 23 / 23 | — | **no** (first commit that emits `prim_ram_1p__DataBitsPerMask_22_Width_22`) |
| **v0.70.0** | `96326d89` | 2026-05-26 | 0.70.0 | 23 / 23 | 23 / 23 | no — `Can't resolve module reference: 'prim_ram_1p__DataBitsPerMask_22_Width_22'` |
| v0.70.1 | `dc813c92` | 2026-06-04 | 0.70.1 | 23 / 23 | 23 / 23 | no (same) |
| v0.70.2 | `80b3d2df` | 2026-06-07 | 0.70.2 | 23 / 23 | 23 / 23 | no (same) |
| v0.70.3 | `e1e7e2d0` | 2026-06-08 | 0.70.3 | 23 / 23 | 23 / 23 | no (same) |
| v0.70.4 | `88c7a613` | 2026-06-08 | 0.70.4 | 23 / 23 | 23 / 23 | no (same) |
| **v0.70.6 (paper pin)** | `afba7d8b` | 2026-07-11 | 0.70.6 | **23 / 23** | **23 / 23** | **no** (same) |
| v0.70.7 | `0e1871af` | 2026-07-11 | 0.70.7 | 23 / 23 | 23 / 23 | no (same) |
| v0.70.8 | `c78f818d` | 2026-07-15 | 0.70.8 | 19 / 23 — stops at `IbexIcache` | 19 / 23 | n/a (no `ibex_top.sv`) |
| **v0.71.0 (newest release)** | `1a7d9fd7` | 2026-07-26 | 0.71.0 | 19 / 23 — stops at `IbexIcache` | 19 / 23 | n/a |
| dev HEAD `f4569890` | `f4569890` | 2026-09-01 | 0.71.0 | 19 / 23 | 22 / 23 (only `IbexIcache` fails when checked after a partial build) | n/a |

Per-file detail for the two failure modes:

- **v0.70.8, v0.71.0, HEAD:** `src/IbexIcache.arch:551` → "operands at
  cycle 0 and cycle 1/2/3/4" (4 errors). The rule (spec §"No
  auto-alignment (v1)", `typecheck.rs::check_operand_latency_alignment`)
  forbids combining operands that materialise at different `@N` cycle
  offsets in one expression; the icache ORs a pipe-register's `@1..@4`
  taps with a cycle-0 signal. `IbexIfStage`, `IbexCore`, `IbexTop` then
  fail only because `ibex_icache.archi` was never produced.
- **v0.70.0 … v0.70.7 (and every dev commit from 9ba64352 on):** all 23
  files compile, but `build/ibex_top.sv` instantiates
  `prim_ram_1p__DataBitsPerMask_22_Width_22` (tag banks) and
  `prim_ram_1p__DataBitsPerMask_64_Width_64` (data banks) instead of
  `prim_ram_1p`. Mechanism: `elaborate.rs::compute_all_variants` mangles a
  module's name whenever it is instantiated with two or more distinct
  parameter sets, and since `9ba64352` it evaluates parameters passed
  from the enclosing module (`Width = TagSizeECC` vs `Width = LineSizeECC`),
  so the two RAM shapes become two variants. `prim_ram_1p` is not an ARCH
  module but a committed hand-written interface stub
  (`src/prim_ram_1p.archi`) for the upstream SV cell; the compiler emits
  no definition for interface stubs, so the mangled names have no
  definition anywhere and the SoC cannot elaborate. No `.arch` source
  triggers this; it is compiler behaviour on an external stub.

**Bottom line for the pin decision:** no release tag both compiles the
port and produces SV that elaborates. Releases split into two groups:
0.70.0–0.70.7 (compile, do not link) and 0.70.8–0.71.0 (reject
`IbexIcache.arch`). The last commits that pass end-to-end are
pre-release dev commits (`15735a77`, 2026-05-23, or `2ffcc60b`,
2026-05-14). Whichever pin is chosen, Phase 1 has to address:

| Pin | Phase 1 work implied |
|---|---|
| v0.70.6 (paper) | the RAM-stub variant mangling only |
| v0.71.0 (newest) | the RAM-stub mangling **and** the icache `@N` operand-alignment error |
| `15735a77` / `2ffcc60b` (dev) | nothing — but it is not a release and predates the paper's pin |

Possible remedies for the mangling, for discussion (none applied):
(1) fix in arch-com — skip interface stubs in `compute_all_variants`
(an internal codegen fix with no language-surface change; would need a
patched build of the chosen pin, or a new release); (2) in this repo,
avoid two parameterisations of one stub — e.g. two stubs
`prim_ram_1p_tag` / `prim_ram_1p_data`, which then need thin upstream-SV
wrappers of those names; (3) a rename pass in `scripts/build.sh` mapping
`prim_ram_1p__*` back to `prim_ram_1p` (does not change what is
measured, but is a flow-script workaround of a compiler bug).
