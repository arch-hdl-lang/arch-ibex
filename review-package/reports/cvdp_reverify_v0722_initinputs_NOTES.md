# Re-verification on arch 0.72.2 with the undriven-input shim (2026-09-06)

Same archived candidates, same pinned docker OSVB image, evaluator at commit
`45c0928` with the shim documented in `README.md` ("never-driven DUT inputs are
initialised to 0" as the first statement of all 88 cocotb tests). Both lanes run.

| Lane | Pass | Fails | Notes |
|---|---|---|---|
| ARCH (0.72.2; `results.csv`) | **46 / 50** | `digital_stopwatch_0001`, `packet_controller_0001`, `vending_machine_0001` (the archived unrepaired three), `perf_counters_0001` | 50 / 50 build, 48 / 50 SV byte-identical to the archive (the two 16-QAM mappers differ and pass) |
| direct-Verilog (`direct-verilog-results.jsonl`) | **46 / 50** | the same three, plus `clock_jitter_detection_module_0003` | |

**What the shim fixed.** The three harnesses that sampled outputs derived from
undriven (`X`) inputs — `data_bus_controller_0001`, `clock_jitter_detection_module_0003`,
`load_store_unit_0001` — now pass deterministically on the ARCH lane; the seeded
`data_bus_controller` case that failed 4 / 4 without the shim passes 4 / 4 with it on
both lanes.

**What remains random-draw dependent (not addressed by the shim, both lanes).**
- `perf_counters_0001` (ARCH lane): **a genuine spec miss exposed by the random draw.**
  The spec says the count "should only be readable via a software request; if there is
  no read request, the output should remain zero", but the ARCH candidate emits
  `p_count_o = sw_req_i ? 1 : count_q` — the running count is exposed exactly when there
  is *no* request. The harness's step-4 check (`p_count_o == 0` after a reset with
  `sw_req_i = 0`) holds unconditionally for a compliant design and, for this candidate,
  only when the last random `cpu_trig_i` value of the previous loop happened to be 0.
  Deterministic per seed (`--seed 1,2`: pass; `--seed 3`: fail, "Counter value 00000010").
  Its archived pass at repair attempt 1 was such a draw, and the repair loop stopped on
  it. Unrelated to the undriven-input shim (this harness initialises its inputs).
  Counted as a failure.
- `clock_jitter_detection_module_0003` on the **direct-Verilog** lane: a functional
  disagreement with the harness's reference (`actual_jitter_detected: 1, expected 0`
  at 1248 ns) under the harness's random clock period / cycle count; 6 / 6 failures
  here with or without the shim, while the archived direct-Verilog run passed. The
  ARCH candidate passes this harness with the shim (its earlier failures were the
  undriven-input `X`).

Deterministic decomposition on the ARCH lane after the shim: 46 problems pass on
every seed, 4 fail — the archived unrepaired three plus `perf_counters` (a spec miss
that single unseeded runs pass about half the time). The archived 47 was one draw;
the multi-seed gate (`tools/reverify.py --seeds 1,2,3,4,5`, README) is the verdict a
regeneration or repair loop should stop on.
