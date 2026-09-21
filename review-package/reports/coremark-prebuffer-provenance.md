# Historical CoreMark result before the icache replay buffer

Recovered from the archived development session for `/private/tmp/arch-ibex-ifgap`.
These are historical test-output excerpts, not a new measurement. Both tests
reported `validated=True`. The baseline already includes the earlier icache
stall and mult/div fixes; it precedes the output replay buffer.

| Variant | DUT ticks | Upstream ticks | DUT CoreMark/MHz | Upstream CoreMark/MHz |
|---|---:|---:|---:|---:|
| Before replay buffer | 113701 | 111651 | 8.794997 | 8.956480 |
| With 16-entry replay buffer | 113234 | 111651 | 8.831270 | 8.956480 |

The buffer saved 467 ticks (0.4107% of baseline ticks). The subsequent
8-entry buffer and bus-arbitration changes are separate measurements.

## Source provenance

- Session: `rollout-2026-05-01T19-53-52-019de69b-52a5-7621-952e-25c0f95e570a.jsonl`.
- Original session SHA-256: `f615659119de3756235e69165b6d395915ef6cfb471771be3931cde51a6ff295`.
- Pre-buffer tool output: line 15477, timestamp `2026-05-11T00:57:09.924Z`.
- Post-buffer tool output: line 15938, timestamp `2026-05-11T01:27:55.798Z`.
- Session summary at line 16025 explicitly identifies these as the baseline
  and new 16-entry replay-buffer results, with 467 cycles recovered.
- Dates above are UTC (both measurements occurred May 10 in America/Los_Angeles).
- The full session is not distributed; the relevant verbatim test outputs
  are preserved below so verification does not depend on private logs.
  This excerpt does not independently establish the exact source/binary
  hashes of those historical runs.

## Pre-buffer test output (verbatim)

```text
Chunk ID: 8fb277
Wall time: 9.2682 seconds
Process exited with code 0
Original token count: 41
Output:
CoreMark compare: dut_ticks=113701 upstream_ticks=111651 ratio=1.0184 dut_cm_mhz=8.794997 upstream_cm_mhz=8.956480 validated=True
.
1 passed in 124.29s (0:02:04)
```

## Post-buffer test output (verbatim)

```text
Chunk ID: a9b670
Wall time: 33.9613 seconds
Process exited with code 0
Original token count: 41
Output:
CoreMark compare: dut_ticks=113234 upstream_ticks=111651 ratio=1.0142 dut_cm_mhz=8.831270 upstream_cm_mhz=8.956480 validated=True
.
1 passed in 125.31s (0:02:05)
```
