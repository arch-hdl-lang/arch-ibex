# Results: multdiv activity gate probe

## Status

Paused on 2026-05-11 after landing the first low-risk operand-isolation
change and measuring its impact with the existing sky130 OpenSTA flow.

This note captures what was tried, what it changed, and the measured
effect. It is not a signoff power result; activity was OpenSTA uniform
global activity, not CoreMark VCD/SAIF annotation.

## Motivation

The swap core's post-icache-area-trim power estimate was much worse than
its area delta:

| metric | upstream | swap before | ratio |
|---|---:|---:|---:|
| SoC area | 1,715,080 um^2 | 1,812,378 um^2 | 1.057x |
| OpenSTA active power, 30% activity | 464.2 mW | 625.8 mW | 1.348x |

The active-power delta was mostly combinational/internal power, suggesting
unused alternate datapaths were still toggling. The first hypothesis was
that the multdiv datapath was receiving raw RF operands even for non-M/D
instructions.

## Root Cause Confirmed

`IbexIdStage` previously forwarded RF operands and multdiv decode outputs
directly to the EX multdiv interface:

```arch
let multdiv_operator_ex_o    = multdiv_operator;
let multdiv_signed_mode_ex_o = multdiv_signed_mode;
let multdiv_operand_a_ex_o   = rf_rdata_a_fwd;
let multdiv_operand_b_ex_o   = rf_rdata_b_fwd;
```

That means ALU, LSU, branch, jump, CSR, and other non-M/D instructions
could still toggle the multdiv module's input cones whenever the RF read
data changed.

Generated `ibex_multdiv_fast.sv` also made this visible: in the idle state,
the shared `MacRes` harness and divide helpers still referenced `op_a_i`,
`op_b_i`, `signed_mode_i`, and `operator_i`.

## Change

Add a simple ID-stage activity gate:

```arch
let multdiv_live: Bool = instr_executing and multdiv_en_dec;

let multdiv_operator_ex_o    = multdiv_live ? multdiv_operator : 2'd0;
let multdiv_signed_mode_ex_o = multdiv_live ? multdiv_signed_mode : 2'b00;
let multdiv_operand_a_ex_o   = multdiv_live ? rf_rdata_a_fwd : 32'h0;
let multdiv_operand_b_ex_o   = multdiv_live ? rf_rdata_b_fwd : 32'h0;
```

The enable pulses themselves (`mult_en_ex_o`, `div_en_ex_o`) are unchanged.
The gate only drives stable defaults when the current ID-stage instruction
is not an executing M/D operation.

## Measured Result

OpenSTA setup:

- Liberty: `sky130_fd_sc_hd__tt_025C_1v80.lib`
- Clock: 100 MHz
- Activity: uniform global activity via `set_power_activity`
- Netlists: fresh Yosys sky130 structural full-SoC netlists

| scenario | upstream | swap before | swap after | after vs upstream | after vs before |
|---|---:|---:|---:|---:|---:|
| Idle, 5% activity | 257.3 mW | 288.9 mW | 273.1 mW | 1.061x | 0.945x |
| Active, 30% activity | 464.2 mW | 625.8 mW | 529.8 mW | 1.141x | 0.847x |
| Peak, 80% activity | 877.1 mW | 1299.3 mW | 1043.3 mW | 1.190x | 0.803x |

Active-power breakdown for swap:

| component | before | after | delta |
|---|---:|---:|---:|
| Internal | 587.2 mW | 491.6 mW | -95.6 mW |
| Switching | 38.6 mW | 38.1 mW | -0.4 mW |
| Leakage | 0.0006 mW | 0.0006 mW | ~0 |
| Total | 625.8 mW | 529.8 mW | -96.0 mW |

Area also improved slightly:

| design | area |
|---|---:|
| upstream | 1,715,080 um^2 |
| swap before | 1,812,378 um^2 |
| swap after | 1,803,009 um^2 |

The gate saved about 9,369 um^2 in the full-SoC synth run.

## Validation

Commands run before rebasing onto `origin/main`:

```sh
ARCH_BIN=/private/tmp/arch-com-ifgap/target/debug/arch ./scripts/build.sh
/Users/<user>/github/arch-com/.venv/bin/python -m pytest -q tests/test_ibex_multdiv_fast_unit_full.py
RUN_COREMARK_COMPARE=1 ARCH_BIN=/private/tmp/arch-com-ifgap/target/debug/arch \
  RDL2ARCH_RISCV_ROOT=/Users/<user>/github/rdl2arch-riscv \
  /Users/<user>/github/arch-com/.venv/bin/python -m pytest -q -s tests/test_coremark_compare.py \
  --basetemp=/tmp/arch_ibex_multdiv_power_coremark
```

Results:

- `tests/test_ibex_multdiv_fast_unit_full.py`: passed.
- CoreMark compare unchanged: DUT `113150`, upstream `111651`, ratio
  `1.0134`.

After rebasing onto `origin/main` (`6af12be`), `./scripts/build.sh` still
passes, but the Verilator-backed multdiv/CoreMark tests are currently blocked
by an unrelated generated-SV issue from main: `_ibex_multdiv_fast_threads`
references `MD_OP_DIV`, `MD_OP_REM`, `MD_OP_MULL`, and `MD_OP_MULH` after those
constants were converted to `local param` declarations scoped to the outer
`ibex_multdiv_fast` module. Before that main change, the same tests passed with
this activity gate applied.

## Artifacts

Power artifacts from this run:

- Baseline upstream/swap: `/tmp/ibex-power-compare-struct`
- Gated swap: `/tmp/ibex-power-multdiv-gate`

Key reports:

- `/tmp/ibex-power-multdiv-gate/swap/power_active.rpt`
- `/tmp/ibex-power-multdiv-gate/swap/power_idle.rpt`
- `/tmp/ibex-power-multdiv-gate/swap/power_peak.rpt`
- `/tmp/ibex-power-multdiv-gate/swap/area.rpt`

## Remaining Follow-Ups

1. Replace uniform activity with CoreMark VCD/SAIF-annotated power so the
   estimate reflects workload toggles instead of a global toggle heuristic.
2. Inspect other alternate datapaths for the same pattern:
   decoder immediate paths, CSR/debug paths, and icache output/fill paths.
3. Consider an ARCH/compiler-level operand-isolation idiom once a second
   hand-written gating case proves the pattern is broadly useful.
