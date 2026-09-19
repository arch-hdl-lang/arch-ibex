# 16 — Benchmark artifacts re-verified on the paper's pin (TASK3 Part C)

Scope: the two published artifact repositories, `arch-hdl-lang/verilogeval-rerun-results`
(156 VerilogEval spec-to-RTL problems) and `arch-hdl-lang/cvdp-spec-rtl-eval` (50 CVDP
pure spec-to-RTL problems). Every archived ARCH candidate was rebuilt with the released
compiler and re-judged by the repo's own black-box harness. **No LLM, Codex or MCP call
was made; no candidate was edited.** Work is on branch `reverify-v0.72.0` of each repo
(not pushed); the driver is `tools/reverify.py` in each. The numbers below cite the
CSVs copied into `reports/`.

## 1. Compiler pin

Both re-verifications were run on the paper's pin, `arch 0.72.2` (asset SHA-256
`e4eb0952…9b5c`, `10-toolchain.md`), and earlier on 0.72.0. **No benchmark candidate
uses `thread`**, so the 0.72.1 emitter change (compiler-introduced declaration
initializers removed, arch-com#995) touches none of them: every regenerated SV file is
byte-identical between the 0.72.0 and 0.72.2 runs. The archives were generated with
0.70.5 (VerilogEval) and 0.70.6 (CVDP).

## 2. VerilogEval — clean

`reports/verilogeval_reverify_v0722_results.csv` (final candidate per problem under the
max-4 repair budget), `..._all_candidates.csv` (every archived candidate).

| Metric | Result |
|---|---|
| Final candidates that build with 0.72.2 | 156 / 156 |
| Final candidates that pass the Icarus testbench | 154 / 156 — exactly the archived 154 |
| Outcome changes vs the archive, either direction | 0 |
| Regenerated SV byte-identical to the archived SV | 155 / 156 (Prob144_conwaylife differs only in a cosmetic function-body emission and passes) |
| All 170 archived candidates (incl. 14 repair attempts) | 170 build, 155 pass, 169 identical, 0 changes |

## 3. CVDP — the compiler is clean; three harness properties needed handling

Archived lane results: ARCH 47 / 50 (35 first pass + 12 repaired, 3 unrepaired),
direct-Verilog 46 / 50 (30 + 16, 4 unrepaired); both judged with the OSVB docker image
pinned by digest. All re-runs below use that image (`--runtime osvb-docker`); the
evaluator's local cocotb-1.9.2 runtime was tried first and is not comparable (41 / 50 on
identical SV; recorded in the repo, not used).

### 3.1 Compiler-side result

| Run (ARCH lane) | Build | SV identical to archive | Pass | CSV |
|---|---|---|---|---|
| 0.72.0, unseeded, no shims | 50 / 50 | 48 / 50 (the two 16-QAM mappers differ; both pass) | 46 | repo `reverify/v0.72.0/` |
| 0.72.2, unseeded, no shims | 50 / 50 | 48 / 50 (same two) | 44 | `reports/cvdp_reverify_v0722_results.csv` |
| 0.72.2, undriven-input shim (§3.3) | 50 / 50 | 48 / 50 | **46** | `reports/cvdp_reverify_v0722_initinputs_arch_results.csv` |
| direct-Verilog, undriven-input shim | — | — | **46** | `reports/cvdp_reverify_v0722_initinputs_direct_verilog_results.jsonl` |

Every pass/fail difference between these runs and the archive is on SV that is
byte-identical to the archived SV under the same image: **none is a compiler effect.**

### 3.2 Root cause of the run-to-run differences (debugged on `data_bus_controller_0001`)

The dataset harness drives one randomly chosen master on its first iteration and never
initialises the other master's `valid`/`data`, which are therefore `X` under Icarus.
The candidate's arbitration reads that `X`: the ARCH candidate's `choose_m1` mux puts
`X` on `s_data`, the direct-Verilog candidate's `select_*` put `X` on `s_valid`. The
harness then executes `int(dut.s_data.value)` on its first sample and cocotb raises
`ValueError: Cannot convert Logic('X') to int`, counted as a failure. Replayed under
Icarus with the idle master at `X`: the ARCH candidate produces `X` in 3 of the 4
(`AFINITY`, first-master) combinations, the direct-Verilog candidate in 2 of 4; the
"both masters first" draw is always safe (predicted failure rates 37.5 % / 25 %; observed
7 / 13 on the ARCH candidate). Two independent random sources decide the draw: cocotb
seeds Python's `random` from the wall clock (`Seeding Python random module with
<epoch seconds>`), and `test_runner.py` draws the `AFINITY` parameter with an unseeded
`random.randint` in the pytest process. All of this is verbatim in the CVDP v1.0.4
dataset harness and identical under CVDP's own `run_benchmark.py`, which runs the same
`pytest /src/test_runner.py` in the same image with no seed. `clock_jitter_detection_
module_0003` and `load_store_unit_0001` flip the same way (random clock periods, data,
grant delays).

### 3.3 Evaluator-side handling (documented shims in the repo README, both lanes)

1. **Undriven-input shim.** The evaluator parses the candidate's top-level input ports
   and injects `_cvdp_eval_init_inputs(dut)` as the first statement of every
   `@cocotb.test` coroutine (88 / 88 tests), driving each input to 0 before the harness's
   own stimulus; inputs the harness drives are overwritten as before. Verified: the
   seeded `data_bus_controller` case that failed 4 / 4 without it passes 4 / 4 on both
   lanes with it. With the shim both lanes score 46 / 50.
2. **Deterministic seed and multi-seed gate.** `evaluate_candidate.py --seed N` forwards
   `N` as `COCOTB_RANDOM_SEED` into the container (cocotb logs "supplied seed N"), seeds
   the pytest process (pins `AFINITY`), and redirects the three harnesses' own
   `random.seed(time.time())`. `tools/reverify.py --seeds 1,2,3,4,5` passes a problem
   only if it passes on every seed and flags `draw_dependent` problems. Validated on
   three problems; **the full five-seed run of both lanes is prepared and not yet run**
   (about 30 min per lane), pending instruction.

### 3.4 Remaining failures after the shim, characterised

| Problem | Lane | What it is |
|---|---|---|
| `digital_stopwatch_0001`, `packet_controller_0001`, `vending_machine_0001` | both | the archived unrepaired problems; fail in every run |
| `perf_counters_0001` | ARCH | **a genuine spec miss.** The spec requires the count to be output only during a software request and zero otherwise; the ARCH candidate emits `p_count_o = sw_req_i ? 1 : count_q` (unmasked when there is no request). The harness's reset check exposes it only when the last random `cpu_trig_i` was 1 (deterministic per seed: seeds 1, 2 pass, seed 3 fails). Its archived repair "pass" was a favourable draw, so the repair loop stopped early. Counted as a failure. |
| `clock_jitter_detection_module_0003` | direct-Verilog | a functional disagreement with the harness's reference model (`actual_jitter_detected: 1, expected 0` at 1248 ns) under the harness's random clock period; 6 / 6 failures here, while that lane's single archived run passed. The ARCH candidate passes it. |

### 3.5 What to quote

- Compiler: 0.72.2 reproduces every archived VerilogEval verdict and every archived
  CVDP build; all CVDP verdict differences are harness draws on identical SV.
- CVDP scores with the harness made deterministic on inputs: **ARCH 46 / 50,
  direct-Verilog 46 / 50** (one draw-dependent-but-really-failing problem per lane,
  §3.4). The archived 47 / 46 were single unseeded draws; three CVDP harnesses cannot
  give a stable verdict without a seed, and a single-draw pass is not a safe stopping
  signal for a generate/repair loop (that is how `perf_counters` slipped through).
- Caveat for the write-up: the two evaluator shims are additions to our evaluator; the
  benchmark's own runner has the nondeterminism.

## Commands

```
# VerilogEval (repo verilogeval-rerun-results, branch reverify-v0.72.0)
ARCH_BIN=~/.local/bin/arch-0.72.2 tools/reverify.py                       # → reverify/v0.72.2/
# CVDP (repo cvdp-spec-rtl-eval, branch reverify-v0.72.0; Docker daemon running)
ARCH_BIN=~/.local/bin/arch-0.72.2 tools/reverify.py --runtime osvb-docker --out reverify/v0.72.2-init-inputs
python3 scripts/evaluate_candidate.py --lane direct-verilog --all --runtime osvb-docker
ARCH_BIN=… tools/reverify.py --runtime osvb-docker --seeds 1,2,3,4,5 --out reverify/v0.72.2-seeded   # prepared, not run
```
