# Register File (FF) Specification

## Purpose
The flip-flop-based RV32 general-purpose register file for Ibex. It provides
either 32 (RV32I) or 16 (RV32E) architectural registers of `DataWidth` bits
each, with two combinational read ports (R1, R2) and one synchronous write
port (W1). Register `x0` is architecturally hardwired to zero (concretely:
to the parameter `WordZeroVal`, which defaults to all-zeros). The module is
the ID/WB-stage register file for the Ibex core when targeting FPGA or
Verilator (where flop arrays are preferred over latch/SRAM macros). When
the optional `DummyInstructions` feature is enabled, `x0` is backed by a
real flop that is exposed only while the consumer asserts that the read is
for a dummy instruction; for any architectural read, `x0` still appears as
`WordZeroVal`.

## Port contract

### Parameters

| Name | Type | Default | Description |
|---|---|---|---|
| `RV32E` | Bool | `0` | When `1`, only 16 registers (`x0..x15`) exist; address bit 4 is ignored on all ports. (ref: ibex_register_file_ff.sv:14, 42-43) |
| `DataWidth` | Int | `32` | Width of every data port and every stored register. (ref: ibex_register_file_ff.sv:15) |
| `DummyInstructions` | Bool | `0` | When `1`, `x0` is implemented with a real flop used only for dummy-instruction reads; otherwise `x0` has no flop. (ref: ibex_register_file_ff.sv:16, 74-99) |
| `WordZeroVal` | UInt<DataWidth> | `0` | Reset value loaded into every register, and the value returned for `x0` reads under normal (non-dummy) operation. (ref: ibex_register_file_ff.sv:17, 63, 84, 91, 98) |

Derived (not user-visible) constants used in the contract below:
`ADDR_WIDTH = RV32E ? 4 : 5`, `NUM_WORDS = 2**ADDR_WIDTH` (16 or 32).

### Ports

| Direction | Name | Type | Description |
|---|---|---|---|
| in  | `clk_i`            | Bool             | Clock. All flop updates occur on its rising edge. (ref: ibex_register_file_ff.sv:20, 61, 82) |
| in  | `rst_ni`           | Bool             | Asynchronous active-low reset. Falling edge immediately forces every flop to `WordZeroVal`. (ref: ibex_register_file_ff.sv:21, 61-63, 82-84) |
| in  | `test_en_i`        | Bool             | DFT test enable. Functionally unused in this flavor; tied through to a sink. (ref: ibex_register_file_ff.sv:23, 105-106) |
| in  | `dummy_instr_id_i` | Bool             | When `DummyInstructions=1`, asserted by the ID stage to indicate the current cycle's read is for a dummy instruction; selects the dummy `x0` flop on read. Unused when `DummyInstructions=0`. (ref: ibex_register_file_ff.sv:24, 91, 95) |
| in  | `dummy_instr_wb_i` | Bool             | When `DummyInstructions=1`, asserted by the WB stage to qualify a write to `x0` as a dummy-instruction write. Unused when `DummyInstructions=0`. (ref: ibex_register_file_ff.sv:25, 80, 95) |
| in  | `raddr_a_i`        | UInt<5>          | Read-port-A address. Bit 4 is ignored when `RV32E=1`. (ref: ibex_register_file_ff.sv:28, 101) |
| out | `rdata_a_o`        | UInt<DataWidth>  | Combinational read-port-A data. (ref: ibex_register_file_ff.sv:29, 101) |
| in  | `raddr_b_i`        | UInt<5>          | Read-port-B address. Bit 4 is ignored when `RV32E=1`. (ref: ibex_register_file_ff.sv:32, 102) |
| out | `rdata_b_o`        | UInt<DataWidth>  | Combinational read-port-B data. (ref: ibex_register_file_ff.sv:33, 102) |
| in  | `waddr_a_i`        | UInt<5>          | Write-port-A address. The decoder compares the full 5-bit value against each implemented register index; with `RV32E=1` an address whose high bit is set will not match any decoded register and therefore drops the write. (ref: ibex_register_file_ff.sv:37, 48-52) |
| in  | `wdata_a_i`        | UInt<DataWidth>  | Write-port-A data. (ref: ibex_register_file_ff.sv:38, 65, 86) |
| in  | `we_a_i`           | Bool             | Write-port-A enable. When `1` and the address decodes to an implemented register, that register captures `wdata_a_i` on the next rising clock edge. (ref: ibex_register_file_ff.sv:39, 50, 64-66, 80) |

## Requirements

### Requirement: Asynchronous reset clears all registers
The register file MUST drive every implemented register flop to
`WordZeroVal` while `rst_ni` is low, and that load MUST take effect
asynchronously (independent of `clk_i`).

#### Scenario: Reset asserted from arbitrary state
- GIVEN `RV32E=0`, `DataWidth=32`, `WordZeroVal=32'h0000_0000`, registers `x1..x31` previously written to non-zero values
- WHEN `rst_ni` falls to `0`
- THEN within the same delta (without waiting for a `clk_i` edge), reading any address `0..31` on either read port yields `32'h0000_0000`
- (ref: ibex_register_file_ff.sv:61-63)

#### Scenario: Non-zero reset value
- GIVEN `RV32E=0`, `DataWidth=32`, `WordZeroVal=32'hDEAD_BEEF`
- WHEN `rst_ni` is held low for at least one event
- THEN reading any address `1..31` on either port yields `32'hDEAD_BEEF`
- AND reading address `0` yields `32'hDEAD_BEEF` (because `WordZeroVal` is also the constant returned for `x0` reads — see "x0 reads as WordZeroVal under normal operation")
- (ref: ibex_register_file_ff.sv:63, 91, 98)

### Requirement: Synchronous write on write-enable
When `we_a_i` is asserted and `waddr_a_i` decodes to an implemented
non-zero register index `i` (for `1 <= i < NUM_WORDS`), the register file
MUST capture `wdata_a_i` into register `i` on the next rising edge of
`clk_i`. When `we_a_i` is deasserted, or `waddr_a_i` does not match `i`,
register `i` MUST hold its previous value across that edge.

#### Scenario: Write-then-read round trip
- GIVEN `RV32E=0`, `DataWidth=32`, registers cleared by reset
- WHEN at cycle N: `we_a_i=1`, `waddr_a_i=5'd7`, `wdata_a_i=32'hCAFE_F00D`
- AND at cycle N+1 onward: `we_a_i=0`
- THEN starting cycle N+1 (after the rising edge of cycle N), with `raddr_a_i=5'd7`, `rdata_a_o = 32'hCAFE_F00D`
- AND with `raddr_b_i=5'd7`, `rdata_b_o = 32'hCAFE_F00D`
- (ref: ibex_register_file_ff.sv:48-52, 61-67, 101-102)

#### Scenario: Write enable low holds value
- GIVEN register `x12` currently holds `32'h1111_2222`
- WHEN `we_a_i=0`, `waddr_a_i=5'd12`, `wdata_a_i=32'hFFFF_FFFF` for one cycle
- THEN after the rising edge, reading `x12` still yields `32'h1111_2222`
- (ref: ibex_register_file_ff.sv:50, 64-66)

#### Scenario: Per-register decode isolates the addressed flop
- GIVEN registers `x3 = 32'hAAAA_AAAA` and `x4 = 32'hBBBB_BBBB`
- WHEN `we_a_i=1`, `waddr_a_i=5'd3`, `wdata_a_i=32'h1234_5678` for one cycle
- THEN after the rising edge, `x3 = 32'h1234_5678` and `x4 = 32'hBBBB_BBBB` (unchanged)
- (ref: ibex_register_file_ff.sv:48-52, 64-66)

### Requirement: Combinational read ports
Both read ports MUST be purely combinational from address to data. With no
intervening clock edge, changing `raddr_a_i` MUST update `rdata_a_o` to the
current value of the addressed register, and likewise for
`raddr_b_i`/`rdata_b_o`. The two read ports MUST be independent and able
to address different registers in the same cycle.

#### Scenario: Two simultaneous reads of distinct registers
- GIVEN `x5 = 32'h0000_0005`, `x9 = 32'h0000_0009`
- WHEN `raddr_a_i = 5'd5` and `raddr_b_i = 5'd9` (no clock edge required)
- THEN `rdata_a_o = 32'h0000_0005` and `rdata_b_o = 32'h0000_0009`
- (ref: ibex_register_file_ff.sv:101-102)

#### Scenario: Two simultaneous reads of the same register
- GIVEN `x10 = 32'hA5A5_A5A5`
- WHEN `raddr_a_i = 5'd10` and `raddr_b_i = 5'd10`
- THEN `rdata_a_o = rdata_b_o = 32'hA5A5_A5A5`
- (ref: ibex_register_file_ff.sv:101-102)

### Requirement: Concurrent read-while-write returns old value
When the write port and a read port reference the same register index in
the same cycle (`we_a_i=1`, `waddr_a_i = i`, and a read address equal to
`i`), the read port MUST return the *pre-write* (old) value of register
`i` for that cycle. The new value becomes visible on read ports only
starting the cycle after the rising edge.

#### Scenario: Read-during-write same address
- GIVEN `x6 = 32'h0000_0006` at start of cycle N
- WHEN at cycle N: `we_a_i=1`, `waddr_a_i=5'd6`, `wdata_a_i=32'hDEAD_BEEF`, `raddr_a_i=5'd6`
- THEN during cycle N: `rdata_a_o = 32'h0000_0006` (old value)
- AND in cycle N+1 (after the rising edge): `rdata_a_o = 32'hDEAD_BEEF` if `raddr_a_i` is still `5'd6`
- (ref: ibex_register_file_ff.sv:61-67, 101)

### Requirement: x0 reads as WordZeroVal under normal operation
When `DummyInstructions=0`, register `x0` MUST NOT be backed by storage:
any read of address `0` MUST return `WordZeroVal`, regardless of any
prior or current write activity targeting address `0`.

#### Scenario: x0 reads zero after reset
- GIVEN `DummyInstructions=0`, `WordZeroVal=32'h0000_0000`, after reset
- WHEN `raddr_a_i = 5'd0`
- THEN `rdata_a_o = 32'h0000_0000`
- (ref: ibex_register_file_ff.sv:98, 101)

#### Scenario: x0 reads WordZeroVal regardless of attempted writes
- GIVEN `DummyInstructions=0`, `WordZeroVal=32'h0000_0000`
- WHEN `we_a_i=1`, `waddr_a_i=5'd0`, `wdata_a_i=32'hFFFF_FFFF` for one cycle
- THEN both during that cycle and in all subsequent cycles, `raddr_a_i=5'd0` yields `rdata_a_o = 32'h0000_0000`
- (ref: ibex_register_file_ff.sv:54-55, 98, 101)

### Requirement: Writes targeting x0 are dropped (DummyInstructions=0)
When `DummyInstructions=0`, a write whose `waddr_a_i = 5'd0` MUST NOT
modify any architectural state observable through the read ports. The
internal decode line for index 0 has no consumer.

#### Scenario: Write to x0 leaves all other registers unchanged
- GIVEN `DummyInstructions=0`, `x1..x31` cleared by reset
- WHEN `we_a_i=1`, `waddr_a_i=5'd0`, `wdata_a_i=32'h1234_5678` for one cycle
- THEN after the rising edge, every register `x0..x31` reads as `WordZeroVal` (i.e., zero by default)
- (ref: ibex_register_file_ff.sv:54-55, 58, 98)

### Requirement: x0 dummy-flop write (DummyInstructions=1)
When `DummyInstructions=1`, the register file MUST maintain an internal
dummy `x0` flop that captures `wdata_a_i` on the next rising clock edge
when, and only when, `we_a_i=1` AND `dummy_instr_wb_i=1`. The dummy flop
MUST reset to `WordZeroVal` on `!rst_ni`.

#### Scenario: Dummy x0 captures only when dummy_instr_wb_i is set
- GIVEN `DummyInstructions=1`, after reset
- WHEN at cycle N: `we_a_i=1`, `waddr_a_i=5'd0`, `wdata_a_i=32'h1111_2222`, `dummy_instr_wb_i=1`
- AND at cycle N+1: `dummy_instr_id_i=1`, `raddr_a_i=5'd0`
- THEN at cycle N+1, `rdata_a_o = 32'h1111_2222`
- (ref: ibex_register_file_ff.sv:80-88, 91)

#### Scenario: Write to x0 with dummy_instr_wb_i deasserted does not capture
- GIVEN `DummyInstructions=1`, dummy `x0` flop currently holds `32'hAAAA_BBBB`
- WHEN at cycle N: `we_a_i=1`, `waddr_a_i=5'd0`, `wdata_a_i=32'hDEAD_BEEF`, `dummy_instr_wb_i=0`
- AND at cycle N+1: `dummy_instr_id_i=1`, `raddr_a_i=5'd0`
- THEN at cycle N+1, `rdata_a_o = 32'hAAAA_BBBB` (dummy flop unchanged)
- (ref: ibex_register_file_ff.sv:80, 85-87, 91)

### Requirement: x0 read multiplex (DummyInstructions=1)
When `DummyInstructions=1`, a read of address `0` MUST return the
dummy-`x0` flop value when `dummy_instr_id_i=1`, and MUST return
`WordZeroVal` otherwise. The selection is combinational on
`dummy_instr_id_i`.

#### Scenario: Read x0 as dummy then as architectural in successive cycles
- GIVEN `DummyInstructions=1`, dummy `x0` flop holds `32'hC0DE_C0DE`, `WordZeroVal=32'h0`
- WHEN at cycle N: `dummy_instr_id_i=1`, `raddr_a_i=5'd0`
- AND at cycle N+1: `dummy_instr_id_i=0`, `raddr_a_i=5'd0` (no other inputs change relevantly)
- THEN at cycle N: `rdata_a_o = 32'hC0DE_C0DE`
- AND at cycle N+1: `rdata_a_o = 32'h0000_0000`
- (ref: ibex_register_file_ff.sv:91)

#### Scenario: Read port B follows the same x0 multiplex
- GIVEN `DummyInstructions=1`, dummy `x0` holds `32'h1357_9BDF`, `WordZeroVal=32'h0`
- WHEN `raddr_b_i=5'd0` and `dummy_instr_id_i=1`
- THEN `rdata_b_o = 32'h1357_9BDF`
- WHEN `raddr_b_i=5'd0` and `dummy_instr_id_i=0`
- THEN `rdata_b_o = 32'h0000_0000`
- (ref: ibex_register_file_ff.sv:91, 102)

### Requirement: RV32E shrinks the register set to 16
When `RV32E=1`, the register file MUST implement only `NUM_WORDS = 16`
flops (one per index `0..15`, subject to the `x0` rules above). The
write-port decoder MUST compare `waddr_a_i` to each implemented index
`i` as a 5-bit value, so any `waddr_a_i` whose bit 4 is set fails to
match any implemented register and silently drops the write. Read
ports indexing addresses `16..31` are out-of-range for `RV32E=1`; the
contract for those addresses is left to the caller (Ibex's decode never
produces them in RV32E mode).

#### Scenario: RV32E write decode ignores out-of-range addresses
- GIVEN `RV32E=1`, registers `x0..x15` cleared
- WHEN `we_a_i=1`, `waddr_a_i=5'd17`, `wdata_a_i=32'hFFFF_FFFF` for one cycle
- THEN after the rising edge, every implemented register `x0..x15` still reads as `WordZeroVal`
- (ref: ibex_register_file_ff.sv:42-43, 48-52)

#### Scenario: RV32E in-range write succeeds
- GIVEN `RV32E=1`, after reset
- WHEN `we_a_i=1`, `waddr_a_i=5'd14`, `wdata_a_i=32'h0000_2026` for one cycle
- THEN after the rising edge, `raddr_a_i=5'd14` yields `rdata_a_o = 32'h0000_2026`
- (ref: ibex_register_file_ff.sv:42-43, 48-52, 64-66, 101)

### Requirement: DataWidth parameterizes all data signals
Every data port (`wdata_a_i`, `rdata_a_o`, `rdata_b_o`) and every stored
register MUST be `DataWidth` bits wide. Reset, write, and read behavior
MUST be bit-true at any supported `DataWidth`.

#### Scenario: Non-32 data width round trip
- GIVEN `DataWidth=64`, `WordZeroVal=64'h0`, after reset
- WHEN `we_a_i=1`, `waddr_a_i=5'd2`, `wdata_a_i=64'hFEED_FACE_CAFE_BABE` for one cycle
- THEN `raddr_a_i=5'd2` yields `rdata_a_o = 64'hFEED_FACE_CAFE_BABE`
- (ref: ibex_register_file_ff.sv:15, 45, 65)

## Notes
- `test_en_i` is functionally unused in this FF flavor — the SV ties it
  to an `unused_test_en` sink (ref: ibex_register_file_ff.sv:104-106).
  An ARCH port for `test_en_i` MAY exist for interface compatibility but
  the implementation MUST NOT let it influence any output.
- The per-register write-enable decoder produces a `we_a_dec[0]` line for
  index 0 even though, when `DummyInstructions=0`, no flop consumes it.
  The SV explicitly sinks it via `unused_strobe = we_a_dec[0]` to silence
  lint (ref: ibex_register_file_ff.sv:54-55). The ARCH port MUST treat a
  write to address 0 as architecturally a no-op when `DummyInstructions=0`
  regardless of how the decoder is structured internally.
- When `DummyInstructions=0`, both `dummy_instr_id_i` and `dummy_instr_wb_i`
  are functionally ignored. The SV sinks them via
  `unused_dummy_instr = dummy_instr_id_i ^ dummy_instr_wb_i`
  (ref: ibex_register_file_ff.sv:93-95).
- Read-during-write returning the *old* value is a defining property of
  this FF-based register file (in contrast to RAM-based variants where
  the behavior depends on the macro). Tests of the ARCH port SHOULD
  assert this explicitly.
- `WordZeroVal` serves two roles: (1) reset value for every register flop
  (and the dummy `x0` flop when present), and (2) the constant returned
  for architectural reads of `x0`. A non-zero `WordZeroVal` therefore
  shifts both the reset state and the apparent value of `x0`.
- All read ports are unconditionally combinational; there is no read
  enable or read clock-gating.
