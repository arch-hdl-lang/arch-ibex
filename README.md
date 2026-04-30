# arch-ibex

Port of [lowRISC Ibex](https://github.com/lowRISC/ibex) RV32IMC core to
[ARCH HDL](https://github.com/arch-hdl-lang/arch-com), via hybrid swap-out:
each Ibex SystemVerilog module is replaced one at a time with an ARCH
equivalent that emits an SV module of the same name, validated by re-running
the existing cocotb ISR test suite plus per-module unit tests.

## Goal

A credible "ARCH expresses CPUs better than SV" demo — every major ARCH
first-class construct (`pipeline`, `bus`, `fsm`, `thread`, `fifo`, `ram`,
`arbiter`, `cam`, `handshake_channel`) exercised in its natural habitat
inside a real RISC-V core, while keeping the existing RV32 ISR cocotb
tests green throughout.

## Quick start

```bash
# 1. Clone + sibling deps. Defaults assume ~/github/{arch-com,ibex,rdl2arch-riscv};
#    override via env vars below if your layout differs.
mkdir -p ~/github && cd ~/github
git clone git@github.com:arch-hdl-lang/arch-ibex.git
git clone git@github.com:arch-hdl-lang/arch-com.git
git clone https://github.com/lowRISC/ibex.git
git clone git@github.com:arch-hdl-lang/rdl2arch-riscv.git

# 2. Build the arch compiler.
cd arch-com && cargo build --release && cd ..

# 3. Python deps.
cd arch-ibex
pip install -e ../rdl2arch-riscv
pip install cocotb cocotb-tools fusesoc pytest pytest-xdist systemrdl-compiler

# 4. System tools (macOS examples; adjust for your distro).
brew install verilator riscv-gnu-toolchain    # need verilator >= 5.0

# 5. Build all ARCH modules + run the gate.
make build      # arch -> build/*.sv
make test       # parallel pytest: SoC lint + 4 ISR programs + per-module units
```

If your checkouts live elsewhere, set:

```bash
export ARCH_BIN=/path/to/arch-com/target/release/arch
export IBEX_ROOT=/path/to/ibex
export RDL2ARCH_RISCV_ROOT=/path/to/rdl2arch-riscv
```

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
│   └── build.sh                  # arch build over src/*.arch into build/
└── WORKFLOW.md           # spec-driven flow rules (adapted from OpenSpec)
```

## External dependencies

Path-referenced for now (no submodules / lockfile):

- **Ibex** at `$IBEX_ROOT` (default `~/github/ibex`) — provides upstream
  `.sv` for all modules not yet swapped, plus `ibex_pkg.sv`.
- **arch compiler** at `$ARCH_COM_ROOT` (default `~/github/arch-com`) —
  built via `cargo build --release`. The `arch` binary is auto-discovered
  by the test harness; override with `$ARCH_BIN`.
- **rdl2arch-riscv** at `$RDL2ARCH_RISCV_ROOT` (default
  `~/github/rdl2arch-riscv`) — CSR-file generator + RDL fixtures.
  Install editable: `pip install -e $RDL2ARCH_RISCV_ROOT`.
- **Toolchain**: `verilator >= 5.0`, `riscv64-elf-gcc`, `fusesoc`,
  Python 3.11+ with `cocotb`, `cocotb-tools`, `pytest`, `pytest-xdist`.

## Make targets

```
make build      # compile every src/*.arch into build/*.sv
make lint       # verilator --lint-only on the swapped SoC
make test       # pytest (parallel) — full gate (lint + ISRs + unit suites)
make clean      # rm -rf build/
```

## Verification gate per swap

1. `make build` — `arch build src/IbexFoo.arch` → `build/ibex_foo.sv`
2. `make lint` — verilator --lint-only on the SoC
3. `pytest tests/test_cpu_programs.py` — 4 ISR programs (timer, sw, ext,
   multictx) all green
4. `pytest tests/test_<module>_unit*.py` — per-module unit + regression
5. After Phase C: `pytest tests/riscv_arch_tests/` — RV32IMC compliance

`make test` runs items 2–4 in parallel via `pytest -n auto --dist=loadfile`.

## Plan

Phases (see `WORKFLOW.md` for the per-swap process):

- **A** — 9 leaf-module swaps (Alu, RegFile, Counter, Decoder,
  CompressedDecoder, Multdiv, FetchFifo, LoadStoreUnit, PrefetchBuffer)
- **B** — 5 composite-stage swaps (ExBlock, WbStage, IfStage, Controller,
  IdStage)
- **C** — `IbexCore.arch` with **`pipeline` + internal `bus`** (the
  linchpin — turns hybrid into a strong demo) + `IbexTop.arch`
- **D** — opentitan-config extensions (Icache with `ram`+`arbiter`+`cam`,
  PMP, debug triggers)

## Status

Landed: A1 `IbexAlu`, A2 `IbexRegisterFileFf`, A3 `IbexCounter`,
A4 `IbexDecoder`, A5 `IbexCompressedDecoder`, A6 `IbexMultdivFast`
(`thread`-based).

Next: A7 `IbexFetchFifo`.

## License

Apache-2.0. See `LICENSE`.
