# Proposal: Port `ibex_prefetch_buffer` to ARCH

## Intent

This swap replaces `ibex_prefetch_buffer.sv` (264 LoC) with `src/IbexPrefetchBuffer.arch`.
The prefetch buffer is the IF-stage bus-side driver: it issues word-aligned instruction-fetch
requests to the OBI instruction bus, tracks up to `NUM_REQS=2` outstanding requests, discards
stale responses after a branch, and drives the `IbexFetchFifo` (A7, already ported) with
valid instruction words. It is the producer side of the IF instruction-flow chain:
`ibex_if_stage → ibex_prefetch_buffer → ibex_fetch_fifo → ibex_if_stage (decoder)`.

This is swap A8 in Phase A; A7 (`IbexFetchFifo`) is the immediate prior swap.

## Scope

**In scope:**
- `ResetAll = 0` (SoC default): only `valid_req_q`, `discard_req_q`, `rdata_outstanding_q`,
  and `branch_discard_q` are asynchronously reset; address registers (`stored_addr_q`,
  `fetch_addr_q`) are not.
- `NUM_REQS = 2` (fixed localparam, not exposed as a parameter in SV — no port-parameterization
  needed).
- All combinational paths: `fifo_ready`, `valid_new_req`, `valid_req`, `instr_addr` mux,
  `fifo_valid`, `busy_o`, `instr_req_o`, `instr_addr_o`.
- OBI handshake (`instr_req_o` / `instr_gnt_i`) including hold-stable-until-granted logic
  (`valid_req_q` / `stored_addr_q`).
- Branch discard tracking: `branch_discard_q` shift register prevents stale rvalid data from
  being pushed into the FIFO after a branch.
- IbexFetchFifo submodule instantiation.

**Out of scope:**
- `ResetAll = 1` path (not used in the SoC).
- Instruction cache variants (only direct-to-bus path).
- Parameterization of `NUM_REQS` (fixed at 2 in the SoC).

## Construct enumeration

| Construct      | Status | Reason |
|----------------|--------|--------|
| `module`       | **picked** | Bespoke request-tracking shift registers + combinational mux logic + submodule instantiation — handle directly. No single construct captures the whole shape. |
| `fsm`          | rejected | No named states with qualitatively different behavior paths. The `valid_req_q`/`discard_req_q` bits form a 1-bit request latch, not a multi-state machine with named arcs. |
| `thread`       | rejected | The OBI bus handshake (req→gnt→rvalid) could be threaded, but the 2-deep outstanding-request shift register has no mid-walk yield / wait-cycle structure — it's purely combinational shift logic clocked each cycle. |
| `fifo`         | rejected | `rdata_outstanding_q[1:0]` is a 2-bit shift register tracking the presence of outstanding requests, not a data-payload queue. The `fifo` construct exposes push/pop data ports; there is no data payload associated with each "slot." |
| `ram` / `cam`  | N/A | Not address-indexed storage. |
| `linklist`     | N/A | Not pointer-chained storage. |
| `regfile`      | N/A | Not a multi-port register array. |
| `arbiter`      | N/A | Not request-grant arbitration between competing sources. |
| `counter`      | N/A | No freestanding count primitive — the request tracking is shift-register, not a count. |
| `pipeline`     | rejected | The 2-deep outstanding-request tracking resembles a 2-stage pipeline but has bespoke gating (branch discard, rvalid shift-down, fifo-fill back-pressure) that a generic `pipeline` stage chain cannot express. |
| `synchronizer` | N/A | Single clock domain. |
| `clkgate`      | N/A | No clock gating. |

## Approach

The implementer should model the module as a flat `module` with:

1. **Four reset registers**: `valid_req_q: Bool`, `discard_req_q: Bool`,
   `rdata_outstanding_q: Vec<Bool, 2>`, `branch_discard_q: Vec<Bool, 2>` — all
   asynchronously reset to `false` / `0`.
2. **Two non-reset address registers** (ResetAll=0 path):
   `stored_addr_q: UInt<32>` (enabled by `stored_addr_en`),
   `fetch_addr_q: UInt<32>` (enabled by `branch_i | (valid_new_req & ~valid_req_q)`).
3. **Combinational wires** for: `valid_new_req`, `valid_req`, `valid_req_d`, `discard_req_d`,
   `rdata_outstanding_n/s`, `branch_discard_n/s`, `fifo_ready`, `fifo_valid`, `instr_addr`,
   `instr_addr_w_aligned`.
4. **IbexFetchFifo submodule instantiation** driven by the above wires.
5. **Output assignments**: `instr_req_o = valid_req`, `instr_addr_o = instr_addr_w_aligned`,
   `busy_o = (|rdata_outstanding_q) | instr_req_o`; FIFO outputs pass through directly.

The Vec reset should use scalar broadcast (`reset rst_ni => 0`) per the syntax pitfalls guide.
Address registers without reset should use conditional `seq` blocks with no reset clause, or
be written as `reg ... ;` with an `if enable { ... }` guard.

## Verification gate

**Basic gate**: `pytest tests/test_prefetch_buffer_unit.py tests/test_soc_lint.py tests/test_cpu_programs.py`

One cocotb test per spec Requirement (≥3 Requirements expected → two-stage review mandatory):
1. Request issuance gating (req_i, fifo_ready, OBI handshake, hold-until-granted).
2. Branch discard / flush (branch_i clears outstanding tracking, stale rvalid discarded).
3. FIFO back-pressure (fifo_busy controls fifo_ready, back-pressure to valid_new_req).
4. busy_o driven from rdata_outstanding + instr_req_o.
5. fetch_addr_q sequencing (advances per issued request, resets on branch).

**Full regression**: `pytest tests/test_prefetch_buffer_unit_full.py`

## Verification gate caveats

- The prefetch buffer instantiates IbexFetchFifo internally. The testbench must compile and
  link both `build/ibex_prefetch_buffer.sv` and `build/ibex_fetch_fifo.sv` (the existing
  arch-built SV for the A7 FIFO). The conftest's `build/<stem>.sv` shadow lookup should
  already handle this if the Verilator compilation step lists both.
- OBI handshake: `instr_req_o` and `instr_gnt_i` are synchronous — the testbench drives
  `instr_gnt_i` the same or next cycle after `instr_req_o` goes high.
- The reset-cycle invariant: after reset, a branch (clear) is issued before any rvalid arrives,
  so unreset address registers are never observed. Tests can rely on this.

## Reference

- Upstream: `~/github/ibex/rtl/ibex_prefetch_buffer.sv` (264 LoC)
- Package: `~/github/ibex/rtl/ibex_pkg.sv` (constants / enums used by wider design)
- Neighbor producer: `~/github/ibex/rtl/ibex_if_stage.sv` (drives `branch_i`, `addr_i`,
  `req_i`, `ready_i`)
- Neighbor consumer: `~/github/ibex/rtl/ibex_fetch_fifo.sv` (now `src/IbexFetchFifo.arch`)
- Reference doc: `~/github/ibex/doc/03_reference/instruction_fetch.rst`
- A7 archived spec (pre-derived integration constraints): `specs/fetch_fifo/spec.md §"Integration
  constraints — Producer side"`
