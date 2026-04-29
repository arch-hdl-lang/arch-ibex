# Counter Specification

## Purpose

`ibex_counter` is a parameterizable up-counter that backs the architectural
performance counters in the Ibex CSR block — `mcycle`, `minstret`, and the
HPM event counters. The module presents a uniform 64-bit interface
(`counter_val_o`, `counter_val_upd_o`) regardless of the underlying storage
width, so that CSR read/write logic can stay 64-bit-shaped while the
synthesizable counter occupies only `CounterWidth` flip-flops. Bits
`[63:CounterWidth]` of every output are tied to zero. The counter advances
by one per cycle when `counter_inc_i` is asserted, supports
software-initiated half-word writes via `counter_we_i` (low 32 bits) and
`counterh_we_i` (high 32 bits), and can optionally publish a same-cycle
incremented "next value" on `counter_val_upd_o` for forwarding into a
same-cycle CSR read (`ProvideValUpd = 1`).

## Port contract

### Parameters

| Name | Type | Allowed values (per CSR-block scope) | Description |
|---|---|---|---|
| `CounterWidth`  | `int`  | `1`, `32`, `64` | Number of physical counter bits. Bits above this are tied to zero on every output. (ref: ibex_counter.sv:6) |
| `ProvideValUpd` | `bit`  | `0`, `1`        | When `1`, `counter_val_upd_o` carries the incremented next-value of the counter; when `0`, `counter_val_upd_o` is hard-wired to zero. (ref: ibex_counter.sv:10) |

### Ports

| Direction | Name | Type | Description |
|---|---|---|---|
| in  | `clk_i`             | `Clock`     | Rising-edge clock for the counter register. (ref: ibex_counter.sv:12) |
| in  | `rst_ni`            | `Bool`      | Asynchronous, active-low reset. While asserted (`rst_ni = 0`), the internal counter is held at zero. Behavioral semantics: async negedge-asserting reset. (ref: ibex_counter.sv:13, 76) |
| in  | `counter_inc_i`     | `Bool`      | When `1` and no write fires, the counter increments by one on the next rising edge of `clk_i`. (ref: ibex_counter.sv:46) |
| in  | `counterh_we_i`     | `Bool`      | When `1`, write the high half (`counter[63:32]`) from `counter_val_i` on the next rising edge. Has higher priority than `counter_we_i` when both are asserted. (ref: ibex_counter.sv:38) |
| in  | `counter_we_i`      | `Bool`      | When `1` and `counterh_we_i = 0`, write the low half (`counter[31:0]`) from `counter_val_i` on the next rising edge. (ref: ibex_counter.sv:35-37) |
| in  | `counter_val_i`     | `UInt<32>`  | Write data for both half-word writes. (ref: ibex_counter.sv:18) |
| out | `counter_val_o`     | `UInt<64>`  | Current counter value, zero-extended to 64 bits when `CounterWidth < 64`. Combinational view of the register. (ref: ibex_counter.sv:19, 89-90, 100, 109) |
| out | `counter_val_upd_o` | `UInt<64>`  | When `ProvideValUpd = 1`, the same-cycle incremented value of the counter (`counter_val_o + 1` truncated to `CounterWidth`, zero-extended to 64). When `ProvideValUpd = 0`, hard-wired to `64'h0`. (ref: ibex_counter.sv:92-97, 102-106) |

## Requirements

### Requirement: Asynchronous reset clears the counter

The counter register SHALL be cleared to zero whenever `rst_ni` is
asserted low, asynchronously and independently of `clk_i`. The reset
SHALL override every other input. While `rst_ni` is held low,
`counter_val_o` SHALL read `64'h0000_0000_0000_0000`.

#### Scenario: Reset from arbitrary state
- GIVEN any prior state of the counter (e.g. `counter_val_o = 64'h0000_0000_DEAD_BEEF` for `CounterWidth = 32`)
- WHEN `rst_ni` is driven low
- THEN within an asynchronous propagation delay, `counter_val_o = 64'h0`
- (ref: ibex_counter.sv:76-78)

#### Scenario: Reset overrides simultaneous increment and write
- GIVEN `rst_ni = 0`
- AND `counter_inc_i = 1`, `counter_we_i = 1`, `counter_val_i = 32'hFFFF_FFFF`
- WHEN a rising edge of `clk_i` occurs
- THEN `counter_val_o = 64'h0` (reset wins)
- (ref: ibex_counter.sv:76-78)

#### Scenario: Counter starts at zero after reset deassertion
- GIVEN `rst_ni` has been low for at least one cycle
- WHEN `rst_ni` rises and `counter_inc_i = counter_we_i = counterh_we_i = 0` on the same cycle
- THEN `counter_val_o = 64'h0` and remains zero until an input event occurs

### Requirement: Increment advances the low CounterWidth bits and wraps

When `counter_inc_i = 1` and neither `counter_we_i` nor `counterh_we_i` is
asserted, the counter register SHALL update on the next rising edge of
`clk_i` to `(counter + 1) mod 2^CounterWidth`. Bits `[63:CounterWidth]` of
`counter_val_o` SHALL remain zero at all times when `CounterWidth < 64`.
The increment SHALL wrap modulo `2^CounterWidth` when the low
`CounterWidth` bits are all ones.

#### Scenario: Single-step increment, CounterWidth = 64
- GIVEN `CounterWidth = 64`, `counter_val_o = 64'h0000_0000_0000_002A`
- AND `counter_inc_i = 1`, `counter_we_i = 0`, `counterh_we_i = 0`
- WHEN a rising edge of `clk_i` occurs
- THEN `counter_val_o = 64'h0000_0000_0000_002B`
- (ref: ibex_counter.sv:30, 46-47)

#### Scenario: Wraparound at CounterWidth = 32
- GIVEN `CounterWidth = 32`, `counter_val_o = 64'h0000_0000_FFFF_FFFF`
- AND `counter_inc_i = 1`
- WHEN a rising edge of `clk_i` occurs
- THEN `counter_val_o = 64'h0000_0000_0000_0000`
- (ref: ibex_counter.sv:30, 47)

#### Scenario: Wraparound at CounterWidth = 64
- GIVEN `CounterWidth = 64`, `counter_val_o = 64'hFFFF_FFFF_FFFF_FFFF`
- AND `counter_inc_i = 1`
- WHEN a rising edge of `clk_i` occurs
- THEN `counter_val_o = 64'h0000_0000_0000_0000`
- (ref: ibex_counter.sv:30, 47)

#### Scenario: Toggle behaviour at CounterWidth = 1
- GIVEN `CounterWidth = 1`, `counter_val_o = 64'h0`
- AND `counter_inc_i = 1` held high for two consecutive cycles
- WHEN two successive rising edges of `clk_i` occur
- THEN after the first edge `counter_val_o = 64'h1`, and after the second edge `counter_val_o = 64'h0`
- (ref: ibex_counter.sv:30, 47)

#### Scenario: No increment when counter_inc_i is low
- GIVEN `counter_val_o = 64'h0000_0000_0000_0042`
- AND `counter_inc_i = 0`, `counter_we_i = 0`, `counterh_we_i = 0`
- WHEN a rising edge of `clk_i` occurs
- THEN `counter_val_o = 64'h0000_0000_0000_0042` (unchanged)
- (ref: ibex_counter.sv:48-50)

### Requirement: Bits above CounterWidth are tied to zero on counter_val_o

`counter_val_o[63:CounterWidth]` SHALL read as zero in every cycle, for
every value of `CounterWidth < 64`. No input combination — including
`counterh_we_i` writes carrying ones in those positions — SHALL be
observable on those output bits. When `CounterWidth = 64`, the entire
64-bit register is observable.

#### Scenario: Tied-zero high half for CounterWidth = 32
- GIVEN `CounterWidth = 32`
- AND any sequence of inputs has been applied
- WHEN `counter_val_o` is sampled at any cycle
- THEN `counter_val_o[63:32] = 32'h0000_0000`
- (ref: ibex_counter.sv:90)

#### Scenario: Tied-zero high half for CounterWidth = 1
- GIVEN `CounterWidth = 1`
- AND any sequence of inputs has been applied
- WHEN `counter_val_o` is sampled at any cycle
- THEN `counter_val_o[63:1] = 63'h0` and `counter_val_o[0]` is the live counter bit
- (ref: ibex_counter.sv:90)

### Requirement: Write priority — any write beats increment

When either `counter_we_i` or `counterh_we_i` is asserted at a rising
edge of `clk_i`, the write SHALL win and `counter_inc_i` SHALL have no
effect for that cycle. There is no carry, no addition; the next-cycle
register value is determined entirely by the write logic.

#### Scenario: counter_we_i and counter_inc_i asserted together
- GIVEN `CounterWidth = 32`, `counter_val_o = 64'h0000_0000_0000_0000`
- AND `counter_we_i = 1`, `counter_inc_i = 1`, `counter_val_i = 32'h1234_5678`, `counterh_we_i = 0`
- WHEN a rising edge of `clk_i` occurs
- THEN `counter_val_o = 64'h0000_0000_1234_5678` (the write value, NOT the write value + 1)
- (ref: ibex_counter.sv:35, 44-47)

#### Scenario: counterh_we_i and counter_inc_i asserted together
- GIVEN `CounterWidth = 64`, `counter_val_o = 64'h0000_0001_FFFF_FFFF`
- AND `counterh_we_i = 1`, `counter_inc_i = 1`, `counter_val_i = 32'hCAFE_BABE`, `counter_we_i = 0`
- WHEN a rising edge of `clk_i` occurs
- THEN `counter_val_o = 64'hCAFE_BABE_FFFF_FFFF` (high half written, low half preserved, no increment)
- (ref: ibex_counter.sv:35, 38-41, 44-45)

### Requirement: Half-word write semantics

When `counter_we_i = 1` and `counterh_we_i = 0`, the next-cycle value of
`counter[31:0]` SHALL be `counter_val_i` and `counter[63:32]` SHALL be
preserved. When `counterh_we_i = 1` (regardless of `counter_we_i`), the
next-cycle value of `counter[63:32]` SHALL be `counter_val_i` and
`counter[31:0]` SHALL be preserved. The actual register storage is only
`CounterWidth` bits wide; bits of either write that fall above
`CounterWidth-1` SHALL be silently discarded and SHALL NOT appear on
`counter_val_o`.

#### Scenario: Low-half write only, CounterWidth = 64
- GIVEN `CounterWidth = 64`, `counter_val_o = 64'hAAAA_AAAA_BBBB_BBBB`
- AND `counter_we_i = 1`, `counterh_we_i = 0`, `counter_val_i = 32'h1111_2222`, `counter_inc_i = 0`
- WHEN a rising edge of `clk_i` occurs
- THEN `counter_val_o = 64'hAAAA_AAAA_1111_2222`
- (ref: ibex_counter.sv:36-37, 44-45)

#### Scenario: High-half write only, CounterWidth = 64
- GIVEN `CounterWidth = 64`, `counter_val_o = 64'hAAAA_AAAA_BBBB_BBBB`
- AND `counterh_we_i = 1`, `counter_we_i = 0`, `counter_val_i = 32'h3333_4444`, `counter_inc_i = 0`
- WHEN a rising edge of `clk_i` occurs
- THEN `counter_val_o = 64'h3333_4444_BBBB_BBBB`
- (ref: ibex_counter.sv:38-41, 44-45)

#### Scenario: counterh_we_i has priority when both write strobes are high
- GIVEN `CounterWidth = 64`, `counter_val_o = 64'hAAAA_AAAA_BBBB_BBBB`
- AND `counter_we_i = 1`, `counterh_we_i = 1`, `counter_val_i = 32'h5555_6666`, `counter_inc_i = 0`
- WHEN a rising edge of `clk_i` occurs
- THEN `counter_val_o = 64'h5555_6666_BBBB_BBBB`
- AND the low half is **not** updated to `counter_val_i` (i.e., `counter_we_i` is suppressed by the same-cycle `counterh_we_i`)
- (ref: ibex_counter.sv:38-41 — when `counterh_we_i` is true, `counter_load[31:0]` is overridden back to `counter[31:0]`)

#### Scenario: Low-half write at CounterWidth = 32
- GIVEN `CounterWidth = 32`, `counter_val_o = 64'h0000_0000_DEAD_BEEF`
- AND `counter_we_i = 1`, `counterh_we_i = 0`, `counter_val_i = 32'hFEED_FACE`, `counter_inc_i = 0`
- WHEN a rising edge of `clk_i` occurs
- THEN `counter_val_o = 64'h0000_0000_FEED_FACE`
- (ref: ibex_counter.sv:36-37, 44-45)

#### Scenario: High-half write is silently discarded when CounterWidth = 32
- GIVEN `CounterWidth = 32`, `counter_val_o = 64'h0000_0000_DEAD_BEEF`
- AND `counterh_we_i = 1`, `counter_we_i = 0`, `counter_val_i = 32'hCAFE_BABE`, `counter_inc_i = 0`
- WHEN a rising edge of `clk_i` occurs
- THEN `counter_val_o = 64'h0000_0000_DEAD_BEEF` (low half preserved by the high-write path; high write has no storage to land in)
- (ref: ibex_counter.sv:38-41 — `counter_load[31:0]` is forced back to `counter[31:0]`; ibex_counter.sv:45 — only `counter_load[CounterWidth-1:0] = counter_load[31:0]` is committed; ibex_counter.sv:87, 98 — bits `[63:CounterWidth]` of `counter_load` are unused)

#### Scenario: Low-half write at CounterWidth = 1 truncates to one bit
- GIVEN `CounterWidth = 1`, `counter_val_o = 64'h0`
- AND `counter_we_i = 1`, `counterh_we_i = 0`, `counter_val_i = 32'hFFFF_FFFE`, `counter_inc_i = 0`
- WHEN a rising edge of `clk_i` occurs
- THEN `counter_val_o = 64'h0` (only `counter_val_i[0]` reaches storage)
- (ref: ibex_counter.sv:45)

#### Scenario: Low-half write at CounterWidth = 1 with odd value
- GIVEN `CounterWidth = 1`, `counter_val_o = 64'h0`
- AND `counter_we_i = 1`, `counterh_we_i = 0`, `counter_val_i = 32'h0000_0001`, `counter_inc_i = 0`
- WHEN a rising edge of `clk_i` occurs
- THEN `counter_val_o = 64'h1`
- (ref: ibex_counter.sv:45)

### Requirement: counter_val_upd_o gating by ProvideValUpd

When `ProvideValUpd = 0`, `counter_val_upd_o` SHALL be hard-wired to
`64'h0000_0000_0000_0000` in every cycle, regardless of `counter_inc_i`,
the write strobes, or the current counter value. When `ProvideValUpd = 1`,
`counter_val_upd_o` SHALL combinationally equal the incremented value of
the current counter, computed as
`((counter_val_o[CounterWidth-1:0] + 1) mod 2^CounterWidth)`,
zero-extended to 64 bits. This output is unconditional on
`counter_inc_i`: it is provided so a same-cycle CSR read can forward
the post-increment value, and the surrounding logic decides whether to
consume it.

#### Scenario: ProvideValUpd = 0, increment in flight
- GIVEN `ProvideValUpd = 0`, `CounterWidth = 64`, `counter_val_o = 64'h0000_0000_0000_0007`
- AND `counter_inc_i = 1`
- WHEN `counter_val_upd_o` is sampled
- THEN `counter_val_upd_o = 64'h0000_0000_0000_0000`
- (ref: ibex_counter.sv:94-95, 104-105)

#### Scenario: ProvideValUpd = 0, idle
- GIVEN `ProvideValUpd = 0`, `CounterWidth = 32`, `counter_val_o = 64'h0000_0000_0000_0000`
- AND all input strobes are low
- WHEN `counter_val_upd_o` is sampled
- THEN `counter_val_upd_o = 64'h0000_0000_0000_0000`
- (ref: ibex_counter.sv:94-95)

#### Scenario: ProvideValUpd = 1, normal forwarding
- GIVEN `ProvideValUpd = 1`, `CounterWidth = 64`, `counter_val_o = 64'h0000_0000_0000_0007`
- WHEN `counter_val_upd_o` is sampled (combinationally, same cycle)
- THEN `counter_val_upd_o = 64'h0000_0000_0000_0008`
- (ref: ibex_counter.sv:30, 102-103)

#### Scenario: ProvideValUpd = 1, wraparound forwarding at CounterWidth = 32
- GIVEN `ProvideValUpd = 1`, `CounterWidth = 32`, `counter_val_o = 64'h0000_0000_FFFF_FFFF`
- WHEN `counter_val_upd_o` is sampled
- THEN `counter_val_upd_o = 64'h0000_0000_0000_0000`
- (ref: ibex_counter.sv:30, 92-93, 97)

#### Scenario: ProvideValUpd = 1, high bits tied to zero
- GIVEN `ProvideValUpd = 1`, `CounterWidth = 32`, `counter_val_o = 64'h0000_0000_1234_5677`
- WHEN `counter_val_upd_o` is sampled
- THEN `counter_val_upd_o = 64'h0000_0000_1234_5678` and `counter_val_upd_o[63:32] = 32'h0`
- (ref: ibex_counter.sv:93, 97)

#### Scenario: ProvideValUpd = 1 is independent of counter_inc_i
- GIVEN `ProvideValUpd = 1`, `CounterWidth = 64`, `counter_val_o = 64'h0000_0000_0000_0010`
- AND `counter_inc_i = 0`
- WHEN `counter_val_upd_o` is sampled
- THEN `counter_val_upd_o = 64'h0000_0000_0000_0011` (the incremented value is published regardless of the increment strobe)
- (ref: ibex_counter.sv:30, 102-103 — `counter_upd` is a continuous combinational adder, not gated by `counter_inc_i`)

#### Scenario: ProvideValUpd = 1 reflects the *current* register, not the next
- GIVEN `ProvideValUpd = 1`, `CounterWidth = 64`, `counter_val_o = 64'h0000_0000_0000_0005`
- AND `counter_we_i = 1`, `counter_val_i = 32'h0000_00FF`
- WHEN `counter_val_upd_o` is sampled in the same cycle (before the rising edge commits the write)
- THEN `counter_val_upd_o = 64'h0000_0000_0000_0006` (incremented value of the *current* `counter_val_o`, not of the post-write value)
- (ref: ibex_counter.sv:30 — `counter_upd` is derived from `counter`, the register output, not from `counter_d`)

## Notes

- **Write priority order, in one sentence:** `counterh_we_i` >
  `counter_we_i` > `counter_inc_i`. `counterh_we_i` and `counter_we_i`
  are not symmetric — when both are asserted, `counterh_we_i` wins on
  both halves (the high half is written from `counter_val_i`, the low
  half is preserved). Either write strobe also suppresses the
  increment for that cycle.
- **`counter_val_i` shared bus:** the same 32-bit input drives both
  half-word writes; the write strobes select which half-word it lands
  in. There is no path for a single cycle to write distinct values to
  the high and low halves.
- **`CounterWidth < 32` corner:** for the in-scope value `CounterWidth
  = 1`, `counter_we_i` writes only `counter_val_i[0]` into storage;
  `counterh_we_i` is silently discarded. This is a direct consequence
  of the storage being only `CounterWidth` bits wide; the spec
  intentionally surfaces this so the implementation cannot widen the
  storage.
- **`ProvideValUpd` rationale (informational, not part of the
  contract):** the upstream comment explains that hard-wiring
  `counter_val_upd_o = 0` lets Xilinx tooling infer DSP blocks for the
  counter's flip-flops; setting `ProvideValUpd = 1` adds a same-cycle
  forwarding adder that prevents DSP inference. The behavioural
  contract is the gating itself; the rationale is captured here for
  context only. (ref: ibex_counter.sv:7-9)
- **Reset semantics:** the upstream RTL has two reset variants behind
  `FPGA_XILINX` — async active-low for the generic flop, sync
  active-low when the DSP path is selected. The behavioural spec
  models the generic (non-FPGA) path: asynchronous, active-low. (ref:
  ibex_counter.sv:53-83)
- **`counter_val_upd_o` is combinational and ungated.** Even when
  `counter_inc_i = 0`, the published value is `counter + 1`. This is
  by design — the consumer (CSR block) muxes between `counter_val_o`
  and `counter_val_upd_o` based on its own logic, not on
  `counter_inc_i`.
- **`counter_val_o` is the registered value**, with bits
  `[63:CounterWidth]` zero-padded combinationally. There is no
  combinational path from any input to `counter_val_o` other than the
  zero-padding of the unused upper bits.
