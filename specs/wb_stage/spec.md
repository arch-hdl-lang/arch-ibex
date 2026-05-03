# Spec: IbexWbStage (ibex_wb_stage, WritebackStage=0)

## Scope

This spec covers only the `WritebackStage == 0` path (passthrough mode).
`WritebackStage == 1`, `DummyInstructions == 1`, and `ResetAll == 1` are out of scope.

The module is purely combinational in this mode. `clk_i` and `rst_ni` are
present for interface compatibility but are unused.

## Parameters (in-scope values)

| Parameter           | In-scope value | Effect                              |
|---------------------|----------------|-------------------------------------|
| `WritebackStage`    | `0`            | Passthrough mode — no flops         |
| `DummyInstructions` | `0`            | Dummy-instruction path unused       |
| `ResetAll`          | `0`            | No unconditional reset (irrelevant) |

## Ports

### Inputs

| Port                       | Width | Description                                          |
|----------------------------|-------|------------------------------------------------------|
| `clk_i`                    | 1     | Clock (unused in WS=0; required for port compat)     |
| `rst_ni`                   | 1     | Active-low reset (unused in WS=0; required for compat) |
| `en_wb_i`                  | 1     | Enable writeback; pulse from ID/EX when instruction done |
| `instr_type_wb_i`          | 2     | `wb_instr_type_e` enum (unused in WS=0; must be declared) |
| `pc_id_i`                  | 32    | PC of instruction in ID/EX (unused in WS=0)          |
| `instr_is_compressed_id_i` | 1     | Instruction is 16-bit compressed                     |
| `instr_perf_count_id_i`    | 1     | Instruction should be counted for perf counters       |
| `rf_waddr_id_i`            | 5     | Register-file write address from ID/EX               |
| `rf_wdata_id_i`            | 32    | Register-file write data from ID/EX (ALU result)     |
| `rf_we_id_i`               | 1     | Register-file write enable from ID/EX                |
| `dummy_instr_id_i`         | 1     | Dummy-instruction flag from ID/EX (wire-through)     |
| `rf_wdata_lsu_i`           | 32    | Register-file write data from LSU (load data)        |
| `rf_we_lsu_i`              | 1     | Register-file write enable from LSU                  |
| `lsu_resp_valid_i`         | 1     | LSU response valid (load/store complete)             |
| `lsu_resp_err_i`           | 1     | LSU response error (suppresses perf counter)         |

### Outputs

| Port                                | Width | Description                                      |
|-------------------------------------|-------|--------------------------------------------------|
| `ready_wb_o`                        | 1     | Writeback stage ready (constant 1 in WS=0)       |
| `rf_write_wb_o`                     | 1     | Writeback writing to RF (tied 0 in WS=0)         |
| `outstanding_load_wb_o`             | 1     | Load outstanding in WB (tied 0 in WS=0)          |
| `outstanding_store_wb_o`            | 1     | Store outstanding in WB (tied 0 in WS=0)         |
| `pc_wb_o`                           | 32    | PC of instruction in WB (tied 0 in WS=0)         |
| `perf_instr_ret_wb_o`               | 1     | Instruction retired (non-speculative)            |
| `perf_instr_ret_compressed_wb_o`    | 1     | Compressed instruction retired                   |
| `perf_instr_ret_wb_spec_o`          | 1     | Speculative retire (tied 0 in WS=0)              |
| `perf_instr_ret_compressed_wb_spec_o` | 1   | Speculative compressed retire (tied 0 in WS=0)  |
| `rf_waddr_wb_o`                     | 5     | Register-file write address to RF                |
| `rf_wdata_wb_o`                     | 32    | Register-file write data to RF                   |
| `rf_we_wb_o`                        | 1     | Register-file write enable to RF                 |
| `dummy_instr_wb_o`                  | 1     | Dummy-instruction flag to RF                     |
| `rf_wdata_fwd_wb_o`                 | 32    | Forwarded WB data to ID/EX (tied 0 in WS=0)     |
| `instr_done_wb_o`                   | 1     | Instruction done in WB (tied 0 in WS=0)         |

## Requirements

### REQ-1: Address passthrough

**Given** `WritebackStage == 0` (passthrough mode),
**when** the module is operating,
**then** `rf_waddr_wb_o` shall equal `rf_waddr_id_i` combinatorially at all times.

*Source: ibex_wb_stage.sv:199 (`assign rf_waddr_wb_o = rf_waddr_id_i`)*

---

### REQ-2: Write-enable OR combination

**Given** `WritebackStage == 0`,
**when** the module is operating,
**then** `rf_we_wb_o` shall equal `rf_we_id_i | rf_we_lsu_i` combinatorially.

*Source: ibex_wb_stage.sv:247 (`assign rf_we_wb_o = |rf_wdata_wb_mux_we`),
where `mux_we[0] = rf_we_id_i` (line 201) and `mux_we[1] = rf_we_lsu_i` (line 202).*

---

### REQ-3: Write-data masked-OR combiner

**Given** `WritebackStage == 0`,
**when** the module is operating,
**then** `rf_wdata_wb_o` shall equal:

```
({32{rf_we_id_i}}  & rf_wdata_id_i) |
({32{rf_we_lsu_i}} & rf_wdata_lsu_i)
```

i.e., a bit-masked OR combiner where each source is gated by its own write-enable.
When exactly one enable is high, `rf_wdata_wb_o` is that source's data.
When neither enable is high, `rf_wdata_wb_o` is `0`.

*Source: ibex_wb_stage.sv:245-246 (masked-OR combiner using `rf_wdata_wb_mux` and `rf_wdata_wb_mux_we`).
The upstream assertion `RFWriteFromOneSourceOnly` (line 251) guarantees `$onehot0(rf_wdata_wb_mux_we)`,
so both enables are never high simultaneously.*

---

### REQ-4: Ready always asserted

**Given** `WritebackStage == 0`,
**when** the module is operating,
**then** `ready_wb_o` shall be constant `1`.

*Source: ibex_wb_stage.sv:216 (`assign ready_wb_o = 1'b1`).*
*Rationale: Without a pipeline stage there is nothing to stall on; ID/EX must never stall waiting for WB.*

---

### REQ-5: Performance counter — instruction retired

**Given** `WritebackStage == 0`,
**when** the module is operating,
**then** `perf_instr_ret_wb_o` shall equal:

```
instr_perf_count_id_i & en_wb_i & ~(lsu_resp_valid_i & lsu_resp_err_i)
```

i.e., an instruction is counted as retired when:
- `instr_perf_count_id_i` is set (instruction should be counted), AND
- `en_wb_i` is asserted (instruction reached writeback), AND
- the LSU response is not an error (`~(lsu_resp_valid_i & lsu_resp_err_i)`).

*Source: ibex_wb_stage.sv:211-212.*

---

### REQ-6: Performance counter — compressed instruction retired

**Given** `WritebackStage == 0`,
**when** the module is operating,
**then** `perf_instr_ret_compressed_wb_o` shall equal:

```
perf_instr_ret_wb_o & instr_is_compressed_id_i
```

i.e., the compressed-instruction retire counter is asserted only when REQ-5
is satisfied AND the instruction is compressed.

*Source: ibex_wb_stage.sv:213.*

---

### REQ-7: Speculative performance counters tied zero

**Given** `WritebackStage == 0`,
**when** the module is operating,
**then** `perf_instr_ret_wb_spec_o` shall be constant `0` and
`perf_instr_ret_compressed_wb_spec_o` shall be constant `0`.

*Rationale: Speculative signals are only meaningful in the flopped WB stage (WS=1);
in passthrough mode (WS=0) the raw counter values from the non-speculative path
are always correct.*

*Source: ibex_wb_stage.sv:209-210.*

---

### REQ-8: Dummy-instruction flag passthrough

**Given** `WritebackStage == 0` and `DummyInstructions == 0` (in-scope),
**when** the module is operating,
**then** `dummy_instr_wb_o` shall equal `dummy_instr_id_i` combinatorially.

*Source: ibex_wb_stage.sv:204 (`assign dummy_instr_wb_o = dummy_instr_id_i`).
Note: even when `DummyInstructions == 0`, the wire-through is preserved for
port-interface compatibility.*

---

### REQ-9: WS=1-only outputs tied zero

**Given** `WritebackStage == 0`,
**when** the module is operating,
**then** the following outputs shall be constant zero/false:
- `outstanding_load_wb_o = 0`
- `outstanding_store_wb_o = 0`
- `pc_wb_o = 32'h0`
- `rf_write_wb_o = 0`
- `rf_wdata_fwd_wb_o = 32'h0`
- `instr_done_wb_o = 0`

*Source: ibex_wb_stage.sv:233-238.*

---

## Integration Constraints

### IC-1: Mutual exclusion of write enables

`rf_we_id_i` and `rf_we_lsu_i` are **mutually exclusive** — they are never
both high at the same time. This is guaranteed by the upstream assertion
`RFWriteFromOneSourceOnly` (`$onehot0(rf_wdata_wb_mux_we)`) at
ibex_wb_stage.sv:251.

The decoder (`ibex_id_stage.sv:421`) clears `rf_we_id_i` for LOAD instructions
(`rf_we_id_o = rf_we_raw & instr_executing & ~illegal_csr_insn_i`), while
the LSU drives `rf_we_lsu_i` (`ibex_core.sv:883: rf_we_lsu = lsu_rdata_valid`).
The masked-OR combiner in REQ-3 relies on this invariant; if both are asserted
simultaneously the result is corrupted.

### IC-2: rf_wdata_wb_o driven at RF write port

The RF producer (`ibex_register_file_ff.sv`) receives:
- `waddr_a_i` ← `rf_waddr_wb_o`
- `wdata_a_i` ← `rf_wdata_wb_o`
- `we_a_i`    ← `rf_we_wb_o`

The register-file write happens on the **rising edge** of `clk_i` when
`we_a_i` is high and `waddr_a_i != 0` (x0 is read-only).

### IC-3: en_wb_i is a single-cycle pulse

`en_wb_i` is driven by `ibex_id_stage.sv:1085` as `en_wb_o = instr_done`.
In the WS=0 path, `instr_done` is asserted for exactly one cycle when the
instruction completes. The perf-counter logic in REQ-5 samples it
combinatorially with `instr_perf_count_id_i`.

### IC-4: lsu_resp_err_i derivation

`lsu_resp_err_i` is driven from `ibex_core.sv:773`:
```
assign lsu_resp_err = lsu_load_err | lsu_store_err;
```
where `lsu_load_err` and `lsu_store_err` are themselves qualified by
`lsu_resp_valid_o`. Thus `lsu_resp_valid_i & lsu_resp_err_i` correctly
identifies the cycle in which a bad LSU response arrives.

### IC-5: clk_i and rst_ni unused in WS=0

In the `g_bypass_wb` generate block (WS=0), `clk_i` and `rst_ni` are
explicitly assigned to `unused_clk`/`unused_rst` locals to satisfy lint.
In the ARCH implementation these ports must be declared (domain compatibility)
but need not drive any logic.

### IC-6: rf_wdata_lsu_i assignment

`rf_wdata_wb_mux[1] = rf_wdata_lsu_i` (ibex_wb_stage.sv:241) is assigned
**outside** the generate block, shared by both WS=0 and WS=1 paths. In WS=0,
the combiner therefore uses `rf_wdata_lsu_i` directly.

## Notes

- `wb_instr_type_e` is a 2-bit enum: `WB_INSTR_LOAD=0`, `WB_INSTR_STORE=1`,
  `WB_INSTR_OTHER=2`. It is passed in as `instr_type_wb_i` but unused in WS=0.
- No registers, no state machines, no clock edges are used in WS=0.
  All outputs are purely combinational.
