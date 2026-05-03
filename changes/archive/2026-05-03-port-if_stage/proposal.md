# Proposal: Port `ibex_if_stage` to ARCH

## Intent

This swap replaces `ibex_if_stage.sv` (839 LoC upstream, ~400 effective LoC
under the SoC's parameter pins) with `src/IbexIfStage.arch`. `ibex_if_stage`
is the IF (instruction-fetch) stage container that:

1. Drives the fetch-address mux (`PC_BOOT` / `PC_JUMP` / `PC_EXC` / `PC_ERET` /
   `PC_DRET` / `PC_BP`).
2. Instantiates the prefetch buffer (`ibex_prefetch_buffer`, ported as A8
   `IbexPrefetchBuffer`) and routes its instr-bus side to the SoC.
3. Instantiates the compressed-instruction expander
   (`ibex_compressed_decoder`, ported as A5 `IbexCompressedDecoder`).
4. Combines bus-side and PMP-side instruction errors.
5. Holds the IF→ID pipeline registers (`instr_rdata_id_o`,
   `instr_rdata_alu_id_o`, `instr_rdata_c_id_o`, `instr_is_compressed_id_o`,
   `instr_gets_expanded_id_o`, `instr_expanded_id_o`, `illegal_c_insn_id_o`,
   `instr_fetch_err_o`, `instr_fetch_err_plus2_o`, `pc_id_o`).
6. Drives `instr_valid_id_o` / `instr_new_id_o` so the ID stage knows when a
   new instruction has landed.

This is the third Phase B composite swap. It follows B1 IbexExBlock and
B2 IbexWbStage which are merged on `main`.

## Scope

**In scope (matches `mini_soc.sv` parameter pins):**

- `ICache = 1'b0` — no I-cache instance; the `gen_prefetch_buffer` branch is
  the only fetch path.
- `BranchPredictor = 1'b0` — no skid buffer or predicted-PC mux.
- `DummyInstructions = 1'b0` — no dummy-instruction insertion; the
  `gen_no_dummy_instr` pass-through is the only path.
- `MemECC = 1'b0` — no integrity decode; `instr_intg_err = 0`.
- `PCIncrCheck = 1'b0` — `pc_mismatch_alert_o` ties to 0.
- `ResetAll = 1'b0` — IF→ID pipeline regs use the no-reset `always_ff`
  variant. The two state registers `instr_valid_id_q` and `instr_new_id_q`
  still take async-low reset.
- `RV32ZC = RV32ZcaZcbZcmp` — passed through to `IbexCompressedDecoder`.
- All comb logic for: exception PC mux, fetch address mux, branch_req,
  prefetch_branch / prefetch_addr selection, bus+PMP error combination,
  fetch_valid squash on misprediction, `csr_mtvec_init_o`, `if_busy_o`.
- IF→ID pipeline registers (no-reset variant) and the two state regs
  (`instr_valid_id_q`, `instr_new_id_q`).
- Sub-module instantiation via ARCH `inst` of `IbexPrefetchBuffer` and
  `IbexCompressedDecoder`.

**Out of scope:**

- `ICache = 1`: the `gen_icache` branch (unused under SoC).
- `BranchPredictor = 1`: skid buffer, predicted-PC path,
  `instr_bp_taken_o`/`instr_bp_taken_q` reg, `predict_branch_*` signals.
  Under `BranchPredictor = 0`, `predict_branch_taken = 0` and
  `predict_branch_pc = 0` per the upstream tieoff.
- `DummyInstructions = 1`: dummy-instr insertion + dummy LFSR + `dummy_instr_id_o`
  reg. Under `DummyInstructions = 0`, the pass-through wires `instr_out`,
  `instr_is_compressed_out`, etc. directly from the compressed decoder.
- `MemECC = 1`: SECDED integrity decode + `prim_buf`. Under `MemECC = 0`,
  `instr_intg_err = 0`, `MemDataWidth = 32`.
- `PCIncrCheck = 1`: secure-PC consistency assertion + `prim_buf` (debug
  hardening; not part of synthesizable spec).
- `ResetAll = 1`: alternative reset variant (Lockstep config, not used here).
- ICache tieoff scaffold (`ic_tag_*_o`, `ic_data_*_o`, `ic_scr_key_req_o`,
  `icache_ecc_error_o`) — drive to 0 directly.
- SVA assertions (`NoMispredBranch` and others) — simulation-only.
- DPI exports (`simutil_get_scramble_*`) — simulation-only stub.

## Construct enumeration

| Construct      | Status | Reason |
|----------------|--------|--------|
| `module`       | **picked** | Outer container wiring two sub-modules + a handful of comb muxes + IF→ID pipeline regs. Direct structural description. |
| `fsm`          | **rejected** | No multi-state sequencing in the container itself; the prefetch buffer's internal FSM is inside `IbexPrefetchBuffer`. |
| `thread`       | **rejected** | No mid-walk yield or multi-cycle wait in the container; sub-modules handle their own timing. |
| `fifo`         | **rejected** | No push/pop FIFO semantics — the fetch FIFO lives inside `IbexPrefetchBuffer` (already ported as A7 `IbexFetchFifo`, and `IbexPrefetchBuffer` instantiates it). |
| `ram`          | **N/A** | Address-indexed storage lives only in the (out-of-scope) ICache. |
| `cam`          | **N/A** | No content-addressed lookup. |
| `linklist`     | **N/A** | No pointer-chained storage. |
| `regfile`      | **N/A** | The IF→ID pipeline registers are a fixed set of write-enabled flops fanned out from one shared `if_id_pipe_reg_we`. Modelled as plain `reg ... guard if_id_pipe_reg_we` to match upstream's `always_ff @ ... if (if_id_pipe_reg_we)` shape, not a multi-port regfile. |
| `arbiter`      | **N/A** | No request-grant arbitration; `pc_mux_internal` is a static fall-through case statement. |
| `counter`      | **N/A** | Not a freestanding count primitive. |
| `pipeline`     | **rejected** | The IF→ID write-enabled flops aren't a uniform-latency stage chain — they're a single boundary register set with one shared write enable. A generic `pipeline` construct adds latency-tracking machinery the design doesn't need. |
| `synchronizer` | **N/A** | Single clock domain. |
| `clkgate`      | **N/A** | No clock gating at this level. |

## Approach

**Outer structure:** `module IbexIfStage` with const params:
- `param DM_HALT_ADDR: const = 32'h1A11_0800;` (used by `EXC_PC_DBD` mux case)
- `param DM_EXCEPTION_ADDR: const = 32'h1A11_0808;` (used by `EXC_PC_DBG_EXC`)

**Port declarations:** match the upstream port list under SoC pinning:
- Clock + async-low reset
- Boot address, instruction-bus side (`req_i`, `instr_req_o`, `instr_addr_o`,
  `instr_gnt_i`, `instr_rvalid_i`, `instr_rdata_i: in UInt<32>`,
  `instr_bus_err_i`, `instr_intg_err_o`)
- ICache tieoff outputs (drive to 0): `ic_*_o`, `icache_ecc_error_o`
- IF→ID outputs: `instr_valid_id_o`, `instr_new_id_o`, `instr_rdata_id_o`,
  `instr_rdata_alu_id_o`, `instr_rdata_c_id_o`, `instr_is_compressed_id_o`,
  `instr_gets_expanded_id_o`, `instr_expanded_id_o`, `instr_fetch_err_o`,
  `instr_fetch_err_plus2_o`, `illegal_c_insn_id_o`, `dummy_instr_id_o = 0`,
  `instr_bp_taken_o = 0`
- ID→IF control: `instr_valid_clear_i`, `id_in_ready_i`, `pc_set_i`,
  `pc_mux_i: in PcSel`, `nt_branch_mispredict_i`,
  `nt_branch_addr_i: in UInt<32>`, `exc_pc_mux_i: in ExcPcSel`,
  `exc_cause: in ExcCause`
- CSRs: `csr_mepc_i`, `csr_depc_i`, `csr_mtvec_i`, `csr_mtvec_init_o`
- Branch target: `branch_target_ex_i`
- PMP: `pmp_err_if_i`, `pmp_err_if_plus2_i`
- Dummy / icache / BP unused-input tieoffs (drive to ignore via `let`)
- `if_busy_o`, `pc_if_o`, `pc_id_o`, `pc_mismatch_alert_o = 0`

**Internal wires:**
- `wire prefetch_busy: Bool` — from PrefetchBuffer
- `wire branch_req: Bool` — `pc_set_i | predict_branch_taken` (= `pc_set_i`
  under BranchPredictor=0)
- `wire fetch_addr_n: UInt<32>` — fetch address mux output
- `wire prefetch_branch: Bool` — `branch_req | nt_branch_mispredict_i`
- `wire prefetch_addr: UInt<32>` — `branch_req ? {fetch_addr_n[31:1], 1'b0} : nt_branch_addr_i`
- `wire fetch_valid_raw, fetch_valid: Bool` — from PrefetchBuffer, then squashed
- `wire fetch_ready: Bool` — `id_in_ready_i & ~stall_dummy_instr` (= `id_in_ready_i` under DummyInstructions=0)
- `wire fetch_rdata: UInt<32>`, `fetch_addr: UInt<32>`, `fetch_err: Bool`, `fetch_err_plus2: Bool`
- `wire instr_decompressed: UInt<32>`, `illegal_c_insn: Bool`,
  `instr_is_compressed: Bool`, `instr_gets_expanded: InstrExp`
- `wire if_instr_valid: Bool` — `fetch_valid & ~stall_dummy_instr` (= `fetch_valid`)
- `wire if_instr_rdata: UInt<32>`, `if_instr_addr: UInt<32>`
- `wire if_instr_bus_err: Bool`, `if_instr_pmp_err: Bool`, `if_instr_err: Bool`,
  `if_instr_err_plus2: Bool`
- `wire exc_pc: UInt<32>`, `irq_vec: UInt<5>`, `pc_mux_internal: PcSel`
- `wire instr_valid_id_d, instr_new_id_d: Bool`
- `wire if_id_pipe_reg_we: Bool`
- `wire instr_intg_err: Bool` — `0` under MemECC=0
- `wire instr_err: Bool` — `instr_intg_err | instr_bus_err_i`

**Registers:**
- `reg instr_valid_id_q: Bool reset rst_ni => 1'b0;`
- `reg instr_new_id_q: Bool reset rst_ni => 1'b0;`
- IF→ID pipeline registers (no-reset variant under ResetAll=0). The
  ARCH idiom is `port reg ... guard if_id_pipe_reg_we` so the synthesized
  `always_ff` mirrors upstream's `if (if_id_pipe_reg_we)` write enable.

**Sub-module instantiation:**
- `inst pb: IbexPrefetchBuffer` — drives instr-bus side, returns
  `valid_o → fetch_valid_raw`, `rdata_o → fetch_rdata`, etc.
- `inst cd: IbexCompressedDecoder` — drives `instr_decompressed`,
  `is_compressed_o`, `gets_expanded_o`, `illegal_instr_o`.

**Comb block(s):** one `comb` block handling:
- Exception PC mux (5-way `match exc_pc_mux_i`)
- Fetch address mux (5-way `match pc_mux_internal`; the `PC_BP` case
  collapses to the BOOT default under BranchPredictor=0)
- `pc_mux_internal = pc_mux_i` (BranchPredictor=0)
- `csr_mtvec_init_o = (pc_mux_i == PC_BOOT) & pc_set_i`
- `branch_req`, `prefetch_branch`, `prefetch_addr`, `fetch_valid` math
- PMP / bus error combination + `if_instr_err`, `if_instr_err_plus2`
- `instr_*_out` pass-through wiring (DummyInstructions=0 path)
- `instr_valid_id_d`, `instr_new_id_d`, `if_id_pipe_reg_we`
- ICache tieoffs: `ic_tag_*_o = 0`, `ic_data_*_o = 0`, `ic_scr_key_req_o = 0`,
  `icache_ecc_error_o = 0`
- BranchPredictor=0 tieoffs: `instr_bp_taken_o = 0`, `pc_mismatch_alert_o = 0`
- DummyInstructions=0 tieoff: `dummy_instr_id_o = 0`, `stall_dummy_instr = 0`

**Unused-input absorbers:** `icache_enable_i`, `icache_inval_i`,
`ic_scr_key_valid_i`, `ic_tag_rdata_i`, `ic_data_rdata_i`,
`dummy_instr_en_i`, `dummy_instr_mask_i`, `dummy_instr_seed_en_i`,
`dummy_instr_seed_i`, `boot_addr_i[7:0]`, `csr_mtvec_i[7:0]`,
`exc_cause.irq_ext`/`exc_cause.irq_int` — wire to `let unused_*` per
upstream's pattern.

## Verification gate

**Basic gate (blocking):**
```
make build
pytest tests/test_if_stage_unit.py tests/test_soc_lint.py tests/test_cpu_programs.py
```

**Full regression (background):**
```
pytest tests/test_if_stage_unit_full.py
```

The basic suite covers: PC mux paths (BOOT, JUMP, EXC, ERET, DRET),
exception PC mux variants (EXC, IRQ, DBD, DBG_EXC), `csr_mtvec_init_o`
on BOOT+pc_set, prefetch_branch / prefetch_addr selection, fetch_valid
squash on misprediction, IF→ID pipeline write-enable timing,
`instr_valid_id_q` / `instr_new_id_q` state register update,
PMP-error and bus-error combination paths, ICache tieoff outputs all
zero. The SoC lint and 4 ISR programs validate end-to-end IF→ID
plumbing.

## Verification gate caveats

1. **Sub-module timing**: `IbexPrefetchBuffer` has its own multi-cycle
   prefetch FSM (the A8 internal one). The unit test must drive the
   bus side with realistic gnt/rvalid handshakes so the buffer
   actually emits a fetched instruction. Reuse the A8 test fixtures'
   bus-driver patterns.

2. **`InstrExp` enum**: `instr_gets_expanded_o` from the compressed
   decoder is an `instr_exp_e` enum (`INSTR_NOT_EXPANDED` /
   `INSTR_EXPANDED`). This must round-trip through the IF→ID pipeline
   register without translation.

3. **IF→ID pipe-reg variant**: under ResetAll=0 the upstream
   `always_ff @(posedge clk_i)` uses no reset (no `if (!rst_ni)` arm).
   The ARCH `port reg ... guard if_id_pipe_reg_we` pattern must lower
   to the same shape (pure clocked write-enable, no reset).
   `instr_valid_id_q` / `instr_new_id_q` keep async-low reset.

4. **Branch req synthesis**: under BranchPredictor=0,
   `predict_branch_taken = 0` is hard-tied; the ARCH source can write
   `branch_req = pc_set_i` directly without keeping the OR-gate.

5. **ICache tieoffs**: the `gen_prefetch_buffer` branch in upstream
   drives all `ic_*_o` outputs to 0. The ARCH module must drive these
   identically; the SoC lint will complain if any is left undriven.

## Reference

- Upstream: `~/github/ibex/rtl/ibex_if_stage.sv` (839 LoC; ~400 effective)
- Sub-modules:
  - `~/github/arch-ibex/src/IbexPrefetchBuffer.arch` (A8)
  - `~/github/arch-ibex/src/IbexCompressedDecoder.arch` (A5)
- Producer neighbor: `~/github/ibex/rtl/ibex_id_stage.sv` (drives `pc_set_i`,
  `pc_mux_i`, `id_in_ready_i`, `instr_valid_clear_i`, `nt_branch_mispredict_i`,
  `nt_branch_addr_i`, `branch_target_ex_i`, `exc_pc_mux_i`, `exc_cause`)
- Consumer neighbor: `~/github/ibex/rtl/ibex_id_stage.sv` (samples
  `instr_valid_id_o`, `instr_new_id_o`, `instr_rdata_id_o`,
  `instr_rdata_alu_id_o`, `instr_rdata_c_id_o`,
  `instr_is_compressed_id_o`, `instr_gets_expanded_id_o`,
  `instr_expanded_id_o`, `illegal_c_insn_id_o`, `instr_fetch_err_o`,
  `instr_fetch_err_plus2_o`, `pc_id_o`)
- Related reference doc: `~/github/ibex/doc/03_reference/instruction_fetch.rst`
- Pipeline reference: `~/github/ibex/doc/03_reference/pipeline_details.rst`
