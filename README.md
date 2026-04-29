# arch-ibex

Port of [lowRISC Ibex](https://github.com/lowRISC/ibex) RV32IMC core to
[ARCH HDL](https://github.com/arch-hdl-lang/arch-com), via hybrid swap-out:
each Ibex SystemVerilog module is replaced one at a time with an ARCH
equivalent emitting an SV module of the same name, validated by re-running
the existing cocotb ISR test suite.

## Goal

Final state: a credible "ARCH expresses CPUs better than SV" demo — every
major ARCH first-class construct (`pipeline`, `bus`, `fsm`, `thread`,
`fifo`, `ram`, `arbiter`, `cam`, `handshake_channel`) exercised in its
natural habitat inside a real RISC-V core, while keeping the existing
RV32 ISR cocotb tests green throughout.

## Layout

```
arch-ibex/
├── src/                  # ARCH source (.arch) — one construct per file
├── build/                # generated .sv (gitignored)
├── soc/                  # hand-written SV scaffolding around the core
│   ├── ibex_mini_soc.sv          # top: RAM + simctrl + CLINT + PLIC + Ibex
│   ├── obi_to_axi_lite.sv        # OBI ↔ AXI-Lite single-trans bridge
│   └── ibex_cs_registers_hybrid.sv  # forks upstream CSR module name,
│                                    # instantiates rdl2arch-riscv's CsrFile
├── specs/                # source-of-truth port-contract specs (per module)
├── changes/              # active swaps (proposal/spec/tasks) +
│   └── archive/          # archived completed swaps
├── tests/                # pytest+cocotb harness; gates every swap
├── scripts/
│   ├── build.sh                  # arch build over src/*.arch into build/
│   └── gen_filelist.py           # emit fusesoc filter list (skip swapped
│                                 # upstream Ibex modules; include build/*.sv)
└── WORKFLOW.md           # spec-driven flow rules (adapted from OpenSpec)
```

## External dependencies (path-referenced for now)

- **Ibex checkout** at `$IBEX_ROOT` (default `~/github/ibex`) — provides
  upstream `.sv` for all modules not yet swapped, plus `ibex_pkg.sv`.
- **rdl2arch-riscv checkout** at `$RDL2ARCH_RISCV_ROOT` (default
  `~/github/rdl2arch-riscv`) — provides the CSR-file generator
  (`from rdl2arch_riscv import RiscvCsrExporter`) and RDL fixtures.
  Install editable: `pip install -e $RDL2ARCH_RISCV_ROOT`.
- **arch compiler** — built from `$ARCH_COM_ROOT` (default
  `~/github/arch-com`); `arch` binary on PATH.
- **Toolchain** — `riscv64-elf-gcc` (Homebrew), `verilator >= 5.0`,
  `fusesoc`, Python 3.11+ with `cocotb`, `cocotb-tools`, `pytest`.

## Plan

See `project_ibex_arch_plan` in arch-com auto-memory. Phases:

- **A** — 9 leaf-module swaps (Alu, RegFile, Counter, Decoder,
  CompressedDecoder, Multdiv, FetchFifo, LoadStoreUnit, PrefetchBuffer)
- **B** — 5 composite-stage swaps (ExBlock, WbStage, IfStage, Controller,
  IdStage)
- **C** — `IbexCore.arch` with **`pipeline` + internal `bus`** (the
  linchpin — turns hybrid into a strong demo) + `IbexTop.arch` (small
  config)
- **D** — opentitan-config extensions (Icache with `ram`+`arbiter`+`cam`,
  PMP, debug triggers)

## Verification gate per swap

1. `scripts/build.sh` — `arch build src/IbexFoo.arch` → `build/IbexFoo.sv`
2. `scripts/gen_filelist.py` — emit fusesoc filter list excluding swapped
   upstream Ibex module(s), including build artifacts
3. `verilator --lint-only` on the SoC
4. `pytest tests/test_cpu_programs.py` — 4 ISR programs (timer, sw, ext,
   multictx) all green
5. `pytest tests/test_soc_lint.py` — SoC-level lint pass
6. After Phase C: `pytest tests/riscv_arch_tests/` — RV32IMC compliance

## Status

- ✅ Phase 0 — repo scaffolded
- 🚧 Phase A1 — `IbexAlu.arch` (next)

## License

Apache-2.0. See `LICENSE`.
