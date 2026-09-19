# TASK5: full benchmark regeneration on one stack (Claude Code + Opus 4.8)

Repos: `cvdp-spec-rtl-eval` (Parts 0–4) and `verilogeval-rerun-results`
(Part 5). This task DOES call the LLM. It regenerates ALL 206 in-scope
problems — 50 CVDP under a corrected multi-seed gate, 156 VerilogEval
under its existing deterministic harness — in three lanes, three
independent runs each, on a single generation stack, capturing
everything Reviewer 1 asked to see. Nothing about the prompts, budget,
harness rules, or black-box conditions changes except the CVDP gate,
the added lane, and the stack switch (disclosed).

Run CVDP first (Parts 0–4); its Lane B run validates the stack and the
driver. Then Part 5.

Compiler: released **arch 0.72.2** (pinned, SHA-256 recorded).

## Ground rules

- Read `README.md`, `tools/reverify.py`, the archived prompts, and the
  existing lane-driver scripts first. Reuse them; do not write a new
  driver from scratch. Show me the diff of every change to the driver
  before running anything.
- The agent under test must never see: the seed list, the evaluator
  shim, the reference testbench source, or any prior run's outputs.
  Black-box rules from the archived protocol stay exactly as they were.
- Each run uses a fresh worker/session and a fresh, empty learning
  store where the lane allows one. Runs must not share state.
- The archived Codex/gpt-5.5 results in both repos are never modified
  or deleted; new runs go under `runs/2026-09/`.
- Ask before starting each lane's first run (cost gate), and stop on
  any driver error rather than retrying silently.

## Phase 0 — pin the generation stack (write `runs/2026-09/00-stack.md`)

Generation stack for this task: **Claude Code + `claude-opus-4-8`,
effort medium, everything else at defaults.** Record:

- `claude --version`; the model id string as returned by the API in a
  test call (`claude-opus-4-8`); the effort level and where it is set
  (settings file contents, verbatim). State that temperature is not
  user-configurable in Claude Code.
- Permission mode for non-interactive runs: `--dangerously-skip-permissions`
  in every lane. Because this removes the approval gate, the run
  directory for each problem must be a disposable sandbox containing
  only that problem's inputs, and the tool restrictions below are what
  bound the agent. Record the flag verbatim.
- Tool configuration: WebSearch and WebFetch DISABLED in all lanes
  (black-box rule); auto-memory disabled; no `CLAUDE.md` anywhere in
  the run directories or the profile; no `-c`/resume; one fresh
  directory and session per problem. Use a clean profile with no user
  preferences. Record the subagent/dynamic-workflow policy (same for
  all lanes).
- The MCP config used by Lane A, verbatim; confirm Lanes B and C have
  no MCP servers configured.
- Note that Claude Code's built-in system prompt and tools are part of
  the harness in every lane and are not user-inspectable.
- The archived prompt files by hash, the docker OSVB image digest,
  evaluator commit, shim commit, arch 0.72.2 asset SHA-256.
- State plainly that this stack differs from the archived run (Codex
  CLI 0.142.5 / gpt-5.5).

## Phase 1 — gate change (driver diff, then wait)

1. The repair loop's success test becomes: `tools/reverify.py
   --seeds 1,2,3,4,5` all pass, with the undriven-input shim active.
   A single-seed pass is not a stop.
2. First-pass accounting is unchanged: record the pre-repair candidate
   and its multi-seed verdict.
3. Budget unchanged: max 4 repair attempts after the first pass.
4. Add per-attempt capture. Run each attempt as a non-interactive
   invocation (`claude -p ... --output-format json`) and parse the
   result object's `usage`: `input_tokens`, `output_tokens`,
   `cache_creation_input_tokens`, `cache_read_input_tokens`; also
   `duration_ms` and, for cross-checking only, `total_cost_usd`. Save
   the raw JSON per attempt. Record the tool-call names from the
   transcript. Never scrape the terminal for these numbers.
4b. Report tokens, not dollars: cost depends on plan and price list
   and is not comparable across readers. Keep the CLI's
   `total_cost_usd` in the raw JSON only; do not report it. Cache
   tokens must be reported separately — repair attempts will show
   large cache reads for the reference card and problem statement,
   and a reviewer must be able to see the real context size, not just
   uncached input.
5. Show me the diff. Wait.

## Phase 2 — lanes

The Arch reference card / SKILL (the static language documentation the
archived protocol supplied) stays in EVERY Arch lane; it is the
language's documentation and is part of what the paper evaluates
(§5.2). The ablation removes only run-time, cross-problem assistance.

- **Lane A: Arch, full tooling** — exactly the archived Arch protocol
  (reference card + MCP check/build/lint tools + learning store +
  `arch_advise` + graph index/context/impact tools), new gate.
- **Lane B: direct SystemVerilog, symmetrized** — the archived direct
  lane plus: `verilator --lint-only -Wall` available via shell (the
  Arch lane has a lint tool), and a language reference of comparable
  size to the Arch reference card supplied the same way (lowRISC
  Verilog style guide excerpts; commit the exact file and its token
  count). New gate. Show me the prompt diff versus the archived Lane B
  prompt before running.
- **Lane C: Arch, no cross-problem retrieval** — reference card +
  `arch check`/`arch build` + `verilator --lint-only` via shell, same
  Icarus feedback as Lane B. NO MCP server, NO learning store
  (`ARCH_NO_LEARN=1`; verify `~/.arch/learn/` is not written), NO
  `arch_advise`, NO graph tools. Prompt identical to Lane A's except
  the tool-access preamble; commit the exact prompt.

Record the token count of each lane's reference document as prompt
context; report it separately from generation tokens.

Order: run Lane B first (cheapest, validates the gate), then A, then C.

## Phase 3 — runs

Three independent runs per lane: `runs/2026-09/<lane>/run{1,2,3}/`.
Per problem per attempt, save: candidate source, generated SV (Arch
lanes), gate verdict per seed, tokens, wall time, tool-call names.
Per run, save a `results.csv` with the same columns as
`reverify/v0.72.2/results.csv` plus `first_pass_multiseed`,
`final_multiseed`, `passing_attempt`, `attempts`, `tokens_in`,
`tokens_out`, `cache_write`, `cache_read`, `wall_s`
(all token columns summed over the problem's attempts).

If budget forces a cut, cut Lane C to two runs; do not cut seeds or
budget.

## Phase 4 — report (write `runs/2026-09/10-results.md`)

1. Per lane: first-pass and final pass counts per run; mean and range
   across runs; the set of problems that never passed in any run.
2. Per lane: mean and total for each of the four token counters,
   presented as input split into uncached / cache-write / cache-read
   plus output; mean attempts; mean wall time; and the reference
   document's token count as a separate line (it recurs on every
   attempt, mostly as cache reads).
3. The difference between Lane A and Lane C, per run and on average —
   this is the "cross-problem retrieval contribution" number.
3b. For Lane A: pass rate and mean attempts for the first 25 versus the
   last 25 problems in run order, and the number of `arch_advise` hits
   that returned a fix from an earlier problem in the same run. Report
   whether later problems benefit from the store.
4. `perf_counters_0001` and `clock_jitter_detection_module_0003`:
   what happened to each in each lane and run.
5. A table of the three harness-quality findings (undriven inputs;
   unseeded stimulus; any new ones), with problem ids and what the
   shim / multi-seed gate does about each.
6. Commands run, in order.

## Part 5 — VerilogEval on the same stack (repo `verilogeval-rerun-results`)

5.1 Reuse the CVDP `00-stack.md` verbatim (copy it in; same versions,
    same flags, same disabled tools). If anything differs, stop.
5.2 Driver: the archived VerilogEval driver with the same tool/lane
    changes as CVDP Phase 1 items 4–5 (per-attempt tokens, wall time,
    tool-call names). The gate is the existing harness — it is
    deterministic (re-verification showed zero outcome changes across
    compilers), so no seed set; do NOT add one. Budget unchanged
    (first pass + max 4 repairs). Show me the driver diff; wait.
5.3 Lanes A, B, C exactly as defined for CVDP (same reference
    documents, same tool restrictions; Lane B keeps the VerilogEval
    reference-testbench black-box rules as archived).
5.4 Three independent runs per lane, `runs/2026-09/<lane>/run{1,2,3}/`,
    same per-problem sandbox and independence rules. Order B, A, C.
    Ask before each lane's first run.
5.5 Keep the archived Prob066 rule: a pass on attempt > 4 is
    unrepaired. Apply it identically in every lane.
5.6 Report (`runs/2026-09/10-results.md` in this repo): the same
    sections as CVDP Phase 4 items 1–3, 3b, 6, plus: the problems
    that failed in the archived gpt-5.5 run versus now, per lane.

## Deliverable

From each repo: `runs/2026-09/00-stack.md`, `10-results.md`, the nine
`results.csv` files, and the driver diff. Eighteen `results.csv` in
total.
