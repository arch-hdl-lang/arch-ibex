# 10 — Toolchain (TASK2)

Recorded 2026-09-03 on the machine that produced every number in this
package (macOS 25.6, Apple silicon). Branch `review-package`, created
from `claude/code-arch-instructions-7b4027` at `8c4b3ca` (= `main`).

## Tools present

| Tool | Version | Identity / path | Used in |
|---|---|---|---|
| ARCH compiler | 0.72.0 (release asset, see decisions table) | `~/.local/arch-v0.72.0/arch-aarch64-apple-darwin/arch` (symlink `~/.local/bin/arch-0.72.0`) | everything from TASK3 on |
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
| ARCH compiler pin (final) | **arch `0.72.0` from the published release** (https://github.com/arch-hdl-lang/arch-com/releases/tag/v0.72.0, tag on merge commit `e5e93bf8`, 2026-09-05). Installed asset: `arch-aarch64-apple-darwin.tar.xz` (2,462,548 bytes), SHA-256 `a6163bacfbd892c1cb7751382bf5cd186f9f22ff380a72fc33dcb83896de1586` (matches the release's `sha256.sum`), unpacked to `~/.local/arch-v0.72.0/arch-aarch64-apple-darwin/arch`, `arch --version` → `arch 0.72.0`. The repo now pins this version in `.arch-version`; `scripts/build.sh` refuses any other `arch` (TASK3 A1). Install on another machine: download the platform asset from the release page (or run its `arch-installer.sh`), verify the SHA-256 against `sha256.sum`, set `ARCH_BIN`. History: the TASK2 measurements (Phases 2–5) were produced with the local merge commit `89ec0522` = main `f4569890` + PR #993 + PR #994, whose two patches are kept under `attic/` for provenance only (both PRs are merged; nothing needs `git am` any more); rebuilding the port with v0.72.0 emits byte-identical SV for all 23 files (`diff -r`, 2026-09-05), and the TASK3 re-gate below reproduces every TASK2 number. |
| Earlier pin (Phases 1–3 measurements) | v0.71.0 (`1a7d9fd7`) + the same two fixes (`ead3aa8f`, `fa4c864f`), plus a hand backport of the `sext` emitter fix. Abandoned at the Phase 4 gate because release v0.71.0's SV emitter still indexes unnamed expressions (`{a,b}[hi:lo]`, `f(x)[i]`, `$signed(x)[i]`) that Verilator accepts but Yosys and sv2v reject; arch-com main fixed those in August (arch#827, #919, #834, `b0a4daba`, `27b4c313`), and the cherry-picks do not apply cleanly to v0.71.0. Decision by the repo owner. All Phase 2/3 numbers were re-run on the final pin (see `12-icache-handshake.md` §8, `13-lint.md`). |
| arch-com PR for the arbiter fix | [arch-hdl-lang/arch-com#994](https://github.com/arch-hdl-lang/arch-com/pull/994), branch `fix/arbiter-valid-only-ready` off `origin/main` `f4569890`: same change plus `test_arbiter_valid_only_request_channel_keeps_internal_ready`; local `cargo test --release` green; **CI: all checks passed**; squash-merged 2026-09-05 as `dfff1523`. |
| arch-com PR for the stub fix | [arch-hdl-lang/arch-com#993](https://github.com/arch-hdl-lang/arch-com/pull/993), branch `fix/stub-variant-mangling` (commit `a814dc62` on `origin/main` `f4569890`): same 12-line change plus regression test `test_interface_stub_not_variant_mangled`; local `cargo test --release` green (30 suites); **CI: all checks passed**; squash-merged 2026-09-05 as `0b6a6976`. |
| arch-com issues filed (2026-09-04) | [#995](https://github.com/arch-hdl-lang/arch-com/issues/995) thread lowering `PROCASSINIT` pattern; [#996](https://github.com/arch-hdl-lang/arch-com/issues/996) `arch sim --pybind` reference-member binding (the two `test_archsim_units` gate failures); [#997](https://github.com/arch-hdl-lang/arch-com/issues/997) `pipe_reg` tap reads vs operand-latency check (spec's FIR example no longer compiles) |
| Commit messages on `review-package` | plain descriptive messages, no AI-authorship trailer |
| ECP5 (Phase 5) | `nextpnr-ecp5` was not installed; the owner chose a source build (2026-09-04): `brew install prjtrellis` (1.4) + `git clone --depth 1 https://github.com/YosysHQ/nextpnr` at `8dbcee5`, `cmake -DARCH=ecp5 -DTRELLIS_INSTALL_PREFIX=$(brew --prefix prjtrellis)`, binary `~/github/nextpnr/build/nextpnr-ecp5` (110 MB). Yosys `synth_ecp5` comes from the Homebrew Yosys. |
| sky130 P&R (Phase 4.4) | OpenROAD-flow-scripts is not present anywhere on the host (shell history, memory notes and a depth-9 filesystem search; `~/github/OpenROAD/test/orfs` is OpenROAD's Bazel test dir, `test/sky130hd` its platform files). Used instead: **OpenROAD's own regression flow** `~/github/OpenROAD/test/flow.tcl` (floorplan → tapcell → PDN → global/detailed placement → repair → CTS → global + detailed route → antenna repair → filler → RCX) with its sky130hd platform, driven by `flow/openroad/run.sh`; smoke-tested on OpenROAD's `gcd_sky130hd` design (9 s, exit 0). The prepared ORFS configs under `flow/orfs/` remain for a host that has ORFS. Three flow fixes were needed before both lanes completed (all identical on both lanes, `14-sky130.md` §4.4): die sized at 25 % (not 50 %) of the synthesised area, the `signed`-stripped netlist, and `setundef -zero; hilomap` tie cells at synthesis. Final reports come from `flow/openroad/report.tcl` on the saved design (OpenROAD's logger ignores OpenSTA's `log_begin`, so the script prints marker-delimited sections that `run.sh` splits). |

## Tools missing (as found at Phase 0; resolved as recorded in the decisions table above)

| Tool | Needed by | Status at Phase 0 → outcome |
|---|---|---|
| `nextpnr-ecp5` (+ `prjtrellis` DB) | Phase 5 | Not installed, no Homebrew formula → built from source on 2026-09-04 (see decisions table). |
| OpenROAD-flow-scripts (ORFS) | Phase 4.4 | Not present → replaced by OpenROAD's own regression flow (see decisions table); ORFS configs kept under `flow/orfs/` for reference. |

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


## TASK3 Part A — re-gate on the released arch 0.72.0 (2026-09-05)

`.arch-version` = `0.72.0`; `scripts/build.sh` checks `arch --version` against it and
refuses a mismatch (verified: the 0.70.7 binary on `PATH` is rejected with the
install hint). `make build` with the release binary: 23 / 23 `.sv`, no port change
(`<scratch>/make-build-A3.log`); `arch check` 23 / 23, one warning (the suppressed comb
SCC in `IbexCoreSharedPkg`; `reports/arch_check_v0720.log`).

| Suite (assertions on) | Result | Wall | Files |
|---|---|---|---|
| `make lint` | FAIL, the same 3 warnings as TASK2 (2 × `PROCASSINIT`, 1 × `SYNCASYNCNET`) | 1 s | `reports/gate_v0720_make_lint.{log,junit.xml}` |
| `make test` (249 items) | **162 passed / 12 failed / 75 skipped** — identical to TASK2 | 60 s | `reports/gate_v0720_make_test.{log,junit.xml}` |
| `tests/test_arch_tests.py` | **74 / 74 pass** (74 reference-generation variants skipped by design) | 21 s | `reports/gate_v0720_arch_tests.{log,junit.xml}` |
| CoreMark compare | pass, validated: Arch 112,855 vs SV 111,651 ticks, ratio **1.0108** (8.861 vs 8.956 CoreMark/MHz) — identical to TASK2 | 46 s | `reports/gate_v0720_coremark.{log,junit.xml}` |

The 12 `make test` failures by cause, none in a design suite: `test_soc_lint` (1, the
lint warnings above); `test_archsim_units` (6 — `arch sim --pybind` still emits the
`cannot form a pointer-to-member to member … of reference type` wrapper, i.e.
**arch-com#996 is not fixed in 0.72.0**; the six modules fail exactly as on the
TASK2 pin); `test_harc_phase1_canaries` (4, "HARC binary not found": the runner's
default HARC path is wrong inside a git worktree, HARC drift); `test_harc_runner`
(1, the never-committed `tests/harc/plans/ibex_compressed_decoder_*` files).

Core-level lint on the 0.72.0 output (`13-lint.md`, TASK3 A5): identical counts to
TASK2 — 141 with waivers (`UNUSEDPARAM` 73, `UNUSEDSIGNAL` 54, `DECLFILENAME` 6,
`IMPORTSTAR` 4, `WIDTHEXPAND` 2, `PROCASSINIT` 2) and 490 without; the
`PROCASSINIT` thread-state-initializer pattern (arch-com#995) is still emitted
(`build/ibex_multdiv_fast.sv:107`, `_t0_state`). Logs
`reports/lint_v0720_arch_lane_ibex_top{,_nowaiver}.log`.

### TASK3 Part B2 — gate on the RVFI = 1 simulation build (2026-09-05)

After Phase B (`11-port-changes.md`), `make build` produces the RVFI = 1 `ibex_top`.
Same four suites, assertions on, `reports/gate_v0720_rvfi1_*`: `make lint` FAIL with
the same 3 warnings; `make test` 162 passed / 12 failed / 75 skipped (same 12 drift
failures; 10 / 10 CPU programs, 39 / 39 unit cases); `test_arch_tests.py` 74 / 74;
CoreMark ratio 1.0108 validated. Number-for-number identical to the Part A gate.
