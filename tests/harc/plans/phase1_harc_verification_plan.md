# Phase 1 HARC Verification Plan

## Scope

Phase 1 migrates four canary unit testbenches from cocotb to HARC:

- `ibex_alu`
- `ibex_counter`
- `ibex_register_file_ff`
- `ibex_wb_stage`

The first gate is parity with the existing cocotb scenario intent. The
completion gate is reusable HARC verification IP plus 100% functional
coverage and 100% code coverage for each migrated DUT, with reviewed
exclusions only for unreachable design behavior.

## Methodology

Each unit migration must produce reusable verification components, not only
directed tests. Reusable components belong under `tests/harc/lib/`; concrete
unit suites belong under `tests/harc/unit/`.

For every unit:

1. Reuse the existing archived spec/test plan when available.
2. Preserve all current cocotb scenario intent.
3. Define transactions for externally meaningful operations.
4. Put raw DUT pin access inside testbench helpers, drivers, or monitors.
5. Provide passive monitor hooks where a higher-level bench could observe the
   same behavior through top-level ports or HARC probes.
6. Centralize scoreboarding, final checks, and required coverage in the HARC
   testbench `check` block.
7. Run independent review on this plan before writing HARC testbench code.
8. Run independent review on completed HARC/Python code before running tests.

## Common Coverage Gates

Functional coverage is closed by HARC covergroups and required bin assertions.
Every planned coverpoint and cross must be hit by the suite.

Code coverage is collected with `harc sim --coverage` and merged per DUT from
the generated Verilator `coverage.dat` outputs. Unhit code must drive either
new stimulus or a reviewed exclusion with a written design rationale.

## Runner Requirements

The shared pytest runner must:

- resolve `HARC_BIN` from the environment, sibling `harc-com`, or `PATH`;
- run `harc check` before simulation;
- support `harc sim --emit-only`;
- support `harc sim --dut ... --top ... --test ... --coverage` for ARCH
  canaries and `harc sim --sv ... --top ... --test ... --coverage` for
  generated/SystemVerilog parity runs;
- pass existing Verilator warning flags through `--verilator-arg`;
- keep build artifacts under pytest-provided temporary directories;
- expose coverage output locations for later merge/reporting.
- merge Verilator `coverage.dat` files per DUT, emit LCOV `.info`, and fail
  the pytest gate unless post-exclusion line/branch coverage is 100%.
- keep any exclusion mechanism explicit: a waiver must name the uncovered item,
  source file, and design reason before it can be removed from the coverage
  denominator.
