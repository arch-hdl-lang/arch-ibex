# 01 — Inventory

Collected 2026-09-03 from the `arch-ibex` working tree at commit `8c4b3ca`
(branch `claude/code-arch-instructions-7b4027`, clean tree apart from the
`review-package/` directory). All paths are relative to the repo root
unless marked otherwise. Nothing under `src/`, `soc/`, `tests/`, or
`scripts/` was modified.

## 1. Ported Ibex configuration

The SoC top instantiates `ibex_top_tracing` (upstream simulation wrapper)
around the ARCH-emitted `ibex_top`. Configuration comes from two places:
compile-time `` `define``s in the SoC file and the parameter defaults
baked into `src/IbexTop.arch` (the ARCH top hardcodes most upstream
`ibex_top` parameters instead of exposing them).

| Knob | Value | Source |
|---|---|---|
| Base ISA | RV32I (`RV32E = 0`) | `src/IbexTop.arch:41` |
| M extension | `RV32MFast` | `soc/ibex_mini_soc.sv:45-47`, `src/IbexTop.arch:43` |
| B extension | `RV32BNone` | `soc/ibex_mini_soc.sv:48-50`, `src/IbexTop.arch:45` |
| C extension | `RV32ZcaZcbZcmp` | `soc/ibex_mini_soc.sv:51-53`, `src/IbexTop.arch:47` |
| Register file | `RegFileFF` | `soc/ibex_mini_soc.sv:54-56`, `src/IbexTop.arch:49` |
| Branch target ALU | 0 | `src/IbexTop.arch:50` |
| Writeback stage | 0 (2-stage pipeline) | `src/IbexTop.arch:51` |
| Branch predictor | 0 | `src/IbexTop.arch:54` |
| Instruction cache | 1, no ECC, no scramble | `soc/ibex_mini_soc.sv:470`, `src/IbexTop.arch:52-53,58` |
| ICache geometry | 2 ways, 8-bit index, 256 lines, 64-bit line | `src/IbexTop.arch:109-116` |
| PMP | enabled, 4 regions, granularity 0 | `soc/ibex_mini_soc.sv:471`, `src/IbexTop.arch:36-38` |
| Debug triggers | `DbgTriggerEn = 1`, `DbgHwBreakNum = 1` | `src/IbexTop.arch:55-56` |
| SecureIbex / Lockstep / DummyInstructions / MemECC | 0 | `src/IbexTop.arch:57,90-94` |
| MHPM counters | `MHPMCounterNum = 0` | `src/IbexTop.arch:39` |
| Debug module addresses | `DmBaseAddr=0`, `DmAddrMask=3`, `DmHaltAddr=0`, `DmExceptionAddr=0` | `soc/ibex_mini_soc.sv:472-475` |

`ICache`, `PMPEnable`, and the four `Dm*` values are also passed
explicitly at the SoC instantiation (`soc/ibex_mini_soc.sv:469-475`);
all other values are the ARCH top's defaults.

The ARCH-side `ibex_core` (`src/IbexCore.arch:69-178`) declares the same
parameter set; note its own `ICache` default is 0 (`src/IbexCore.arch:79`)
and the value 1 is threaded down from `IbexTop`.

## 2. Module mapping: upstream SV → ARCH

Rule used by the test harness (`tests/conftest.py:235-262`): every
`build/<name>.sv` emitted by `arch build` shadows the upstream
`rtl/<name>.sv` of the same basename in the fusesoc-resolved filelist.
`ibex_cs_registers.sv` is additionally shadowed by a hand-written fork
(`tests/conftest.py:227-231`).

Upstream file list: `$IBEX_ROOT/rtl/` (31 files). ARCH sources:
`src/*.arch` (23 files, 10,326 lines total per `wc -l`).

### 2a. Ported to ARCH (module of the same SV name is emitted)

| Upstream SV (`rtl/`) | ARCH source (`src/`) | Top-level ARCH construct |
|---|---|---|
| `ibex_alu.sv` | `IbexAlu.arch` | `module` |
| `ibex_compressed_decoder.sv` | `IbexCompressedDecoder.arch` | `module` |
| `ibex_controller.sv` | `IbexController.arch` | `fsm` |
| `ibex_core.sv` | `IbexCore.arch` | `module` |
| `ibex_counter.sv` | `IbexCounter.arch` | `module` |
| `ibex_decoder.sv` | `IbexDecoder.arch` | `module` |
| `ibex_ex_block.sv` | `IbexExBlock.arch` | `module` |
| `ibex_fetch_fifo.sv` | `IbexFetchFifo.arch` | `module` |
| `ibex_icache.sv` | `IbexIcache.arch` + helpers `InvalCtrl.arch` (`fsm`), `FbAgeArb.arch` (`arbiter`), `RamPortArb.arch` (`arbiter`), `IbexIcacheOutputStage.arch` (`module`) | `module` + sub-constructs |
| `ibex_id_stage.sv` | `IbexIdStage.arch` | `module` |
| `ibex_if_stage.sv` | `IbexIfStage.arch` | `module` |
| `ibex_load_store_unit.sv` | `IbexLoadStoreUnit.arch` | `module` |
| `ibex_multdiv_fast.sv` | `IbexMultdivFast.arch` | `module` containing a `thread` |
| `ibex_pmp.sv` | `IbexPmp.arch` | `module` |
| `ibex_prefetch_buffer.sv` | `IbexPrefetchBuffer.arch` | `module` |
| `ibex_register_file_ff.sv` | `IbexRegisterFileFf.arch` | `module` |
| `ibex_top.sv` | `IbexTop.arch` | `module` |
| `ibex_wb_stage.sv` | `IbexWbStage.arch` | `module` |
| (none — new) | `IbexCoreSharedPkg.arch` | `package` shared by several ported modules |

Construct names were read from the first top-level declaration in each
file (`grep -nE '^(module|fsm|thread|arbiter|package)'`). The
sub-construct files for the icache have no separate upstream counterpart;
upstream implements the same logic inline in `ibex_icache.sv`.

### 2b. Reused as-is from upstream SV

| Upstream SV | Status | Where it is pulled in |
|---|---|---|
| `rtl/ibex_pkg.sv` | reused (imported by every ARCH module) | fusesoc filelist |
| `rtl/ibex_csr.sv` | reused | instantiated 3× by `soc/ibex_cs_registers_hybrid.sv:1155-1183` |
| `rtl/ibex_top_tracing.sv`, `rtl/ibex_tracer.sv`, `rtl/ibex_tracer_pkg.sv` | reused (simulation-only wrapper and tracer) | `soc/ibex_mini_soc.sv:469` |
| `vendor/lowrisc_ip/ip/prim*/…` (`prim_ram_1p`, `prim_ram_1p_pkg`, `prim_clock_gating`, `prim_buf`, and their dependencies) | reused | instantiated by `src/IbexTop.arch:451-725` |
| `shared/rtl/ram_2p.sv`, `shared/rtl/sim/simulator_ctrl.sv` | reused (SoC memory + sim control, not part of the core) | `tests/conftest.py:336-337` |

### 2c. Forked (hand-written SV in this repo, derived from upstream)

| Upstream SV | Fork | Note |
|---|---|---|
| `rtl/ibex_cs_registers.sv` | `soc/ibex_cs_registers_hybrid.sv` | Same port list as upstream; internals route selected M-mode trap CSRs through a CSR file generated by the sibling `rdl2arch-riscv` project (header, lines 6-40). Not an ARCH port of this repo; counted as neither "ported" nor "reused" in the LOC step. |

### 2d. Not instantiated in this configuration (neither ported nor used)

| Upstream SV | Reason |
|---|---|
| `rtl/ibex_branch_predict.sv` | `BranchPredictor = 0` (upstream generate guard `rtl/ibex_if_stage.sv:595`) |
| `rtl/ibex_dummy_instr.sv` | `DummyInstructions = 0` (`rtl/ibex_if_stage.sv:430`) |
| `rtl/ibex_lockstep.sv` | `SecureIbex = 0` (`rtl/ibex_top.sv:993`) |
| `rtl/ibex_multdiv_slow.sv` | `RV32M = RV32MFast` (`rtl/ibex_ex_block.sv:140`) |
| `rtl/ibex_register_file_fpga.sv`, `rtl/ibex_register_file_latch.sv` | `RegFile = RegFileFF` (`rtl/ibex_top.sv:484,506`) |

The ARCH `ibex_if_stage` (`src/IbexIfStage.arch`) instantiates only
`ibex_icache` and `ibex_compressed_decoder`; the disabled generate
branches above have no ARCH equivalent.

### 2e. SoC scaffolding outside the Ibex core (for completeness)

Hand-written SV: `soc/ibex_mini_soc.sv`, `soc/obi_to_axi_lite.sv`.
Generated by `rdl2arch-riscv` (ARCH-generated, but not Ibex modules):
CLINT, PLIC, and the CSR file used by the hybrid CSR fork
(`tests/conftest.py:20-21,126-133`). These are excluded from the
"ported module set" in later steps.

## 3. Upstream Ibex reference

- Repository: `https://github.com/lowRISC/ibex.git`, checked out at
  `$IBEX_ROOT` (default `~/github/ibex`, per `README.md` "External
  dependencies"). There is no submodule, vendored copy, or lockfile in
  `arch-ibex`; the dependency is path-referenced.
- Commit: `eede2fbbef007d53cafbd85d937b897751c40a54`, dated
  2026-04-10 09:08:11 +0100, subject "[doc] Ibex Concierge updated"
  (`git -C ~/github/ibex log -1`).
- The checkout is a shallow clone: `git rev-list --count HEAD` = 1,
  `git tag | wc -l` = 0, branch `master`. No release tag can be
  associated with it locally; the commit hash above is the only
  identifier.
- `rtl/` is unmodified (`git status --short rtl/` is empty).
  `syn/` has local modifications (`syn/syn_yosys.sh`, plus untracked
  `syn/syn_setup.sh`, `syn/*.sky130.sdc`, `syn/syn_out/`). This matters
  for Step 4 and is recorded there.

## 4. ARCH compiler

- No version pin exists in `arch-ibex` (no lockfile, no `pyproject`,
  no version string in `README.md` or `WORKFLOW.md`). The compiler is
  path-referenced: `scripts/build.sh:17-33` resolves
  `$ARCH_BIN`, else `../arch-com/target/{release,debug}/arch`.
- Binary used for this package: `~/github/arch-com/target/release/arch`,
  `arch --version` → `arch 0.71.0`. Built 2026-09-02 from arch-com
  commit `f4569890111c50edc0002bf0ebc0ca28a4a86aa1` (2026-09-01),
  `git describe --tags` → `v0.71.0-233-gf4569890`.
  (`$ARCH_BIN` had to be set explicitly: from a git worktree the
  `../arch-com` relative lookup in `scripts/build.sh` does not resolve.)
- Every other `arch` binary on this machine (7 found under
  `~/github/arch-com*/`) is also `0.71.0` built between 2026-08-06 and
  2026-09-02; none predates July 2026.

### Finding: compiler/source version drift

Running `make build` with the binary above compiles 19 of the 23 ARCH
sources and then stops on `src/IbexIcache.arch`:

```
Error: × 4 errors
  × operands at cycle 0 and cycle 1   (src/IbexIcache.arch:551:5)
  × operands at cycle 0 and cycle 2
  × operands at cycle 0 and cycle 3
  × operands at cycle 0 and cycle 4
```

The offending expression is
`fb_busy_mask | fb_busy_prev@1 | fb_busy_prev@2 | fb_busy_prev@3 | fb_busy_prev@4`
(`src/IbexIcache.arch:550-552`). Because `scripts/build.sh` runs with
`set -e`, the four sources that depend on the icache were never
attempted: `IbexIcache`, `IbexIfStage`, `IbexCore`, `IbexTop`. The
other 19 `.sv` files are present under `build/`.

Timeline evidence:

| Event | Date | Source |
|---|---|---|
| Last change to `src/IbexIcache.arch` | 2026-05-13 | `git log -1 -- src/IbexIcache.arch` |
| Last change to any `src/*.arch` | 2026-06-24 (`IbexLoadStoreUnit.arch`) | `git log -1 -- src/` |
| Last `arch-ibex` commit | 2026-06-29 (`8c4b3ca`) | `git log -1` |
| Last arch-com commit on or before that date | `567af654`, 2026-06-29 | `git -C ~/github/arch-com log --before=2026-06-30 -1` |
| arch-com commit that introduced the "operands at cycle" diagnostic | `2aab897a`, 2026-07-12, "feat(lang): fma<pipelined, N> surface + latency typing" | `git -C ~/github/arch-com log -S'operands at cycle'` |
| Newest arch-com PRs cited in `arch-ibex` docs | #315, #317 (merged 2026-05-07), #321 (2026-05) | `grep -rhoE 'arch-com#[0-9]+'` |

Conclusion: the ARCH sources were last validated against an arch-com
build no newer than 2026-06-29; the compiler on this machine is from
2026-09-01 and contains a language check added on 2026-07-12 that
rejects one existing source. Whether that check is an intended
semantic change or a regression is not determined here. The Arch lane
cannot be fully regenerated with the current binary; see the open
question at the end of this file.

## Notes and caveats surfaced during inventory

- `README.md` "Status" section is stale: it lists only A1–A6 as landed,
  while `changes/archive/` records all Phase A–D swaps as archived
  (17 entries, 2026-04-29 → 2026-05-06), and `src/` contains all 23
  ARCH sources.
- `tests/conftest.py:7` and `README.md` require `riscv64-elf-gcc`
  (present at `/opt/homebrew/bin/riscv64-elf-gcc`). The Python that
  carries `cocotb 2.0.1` / `pytest 8.4.2` / `xdist` is
  `/opt/homebrew/anaconda3/bin/python3`; the default `python3` (3.14)
  lacks cocotb. Step 2 must invoke pytest from the anaconda environment.
- `cloc` is not installed; Step 3 will use `wc -l` with blank/comment
  lines counted separately.
- Vivado is not installed and no Xilinx installation exists under
  `/tools/Xilinx` or `/Applications/Xilinx`. Yosys 0.67, Verilator
  5.048, Icarus 12.0, and OpenROAD are available.

### Resolution: contemporaneous compiler rebuilt (decision by repo owner)

Three historical arch-com commits were checked out into scratch
directories outside the repo and built with `cargo build --release`
(each ≈30 s wall with cached crates). None of this touches
`arch-ibex` files.

| Candidate | arch-com commit | Date | `arch --version` | `make build` | `ibex_top.sv` RAM instance name |
|---|---|---|---|---|---|
| June | `567af654` (last commit ≤ last arch-ibex commit) | 2026-06-29 | 0.70.4 | 23/23 `.sv` | `prim_ram_1p__DataBitsPerMask_22_Width_22` — Verilator: "Can't resolve module reference" |
| A | `15735a77` (parent of `9ba64352`, "variant discovery uses enclosing params") | 2026-05-23 | 0.70.0 | 23/23 `.sv` | `prim_ram_1p` — links |
| **B (used)** | `2ffcc60b` (arch-com head at the end of 2026-05-13, the last green-gate date) | 2026-05-14 05:59 −0700 | 0.70.0 | 23/23 `.sv` | `prim_ram_1p` — links |

The June compiler compiles everything but specialises the external
`prim_ram_1p` stub (`src/prim_ram_1p.archi`, a committed hand-written
interface for an upstream SV cell) into a parameter-mangled module
name that no SV file defines, so the SoC does not elaborate. The last
commit in `arch-ibex` whose message quotes a full green gate is
`dcdbbc8` (2026-05-13, "130 passed / 0 failed / 75 skipped"); the
three later commits (2026-06-21 → 06-29) quote no gate result.

**All Arch-lane numbers in Steps 2–4 use candidate B:
`arch 0.70.0 @ arch-com 2ffcc60b`.** A and B behaved identically on
every measurement taken (same lint warnings, same simulation
outcome); B was kept because it is the closest datable match to the
last recorded green gate. The break between working and non-working
compilers was not bisected further than "somewhere in
`15735a77..567af654`". The compiler the sources were originally
validated with is not recorded anywhere in the repo.

Note on the build script: `scripts/build.sh` resolves instantiation
dependencies through `src/*.archi` files, four of which are committed
hand-written stubs for upstream SV modules (`ibex_cs_registers`,
`prim_buf`, `prim_clock_gating`, `prim_ram_1p`); the rest are
compiler-emitted and gitignored. During this task those four were
accidentally removed by a clean-up glob and restored verbatim with
`git checkout -- src/` before any measurement; `git status` shows
`src/` unchanged.
