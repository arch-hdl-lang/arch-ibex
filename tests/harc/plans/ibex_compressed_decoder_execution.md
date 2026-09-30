# Compressed-decoder executable coverage

Plan independently reviewed by `/root/review_844` in this session before
implementation. The archived suite at arch-ibex.archive commit 38719a7 was
subsequently found, but review identified counterfactual output-bin credit and
unchecked advance transactions. Its closure claims are not imported.

The replacement uses upstream Ibex RTL at
`eede2fbbef007d53cafbd85d937b897751c40a54`, RV32ZC=3, ResetAll=0.
The generator drives inputs at clock-low, evaluates, raises clock, evaluates,
and records settled outputs. HARC drives the same row then waits one cycle
before monitoring. Reset rows are checked but excluded from functional bins.
Unmasked phase is obtained by probing reference valid=ready=1 without a clock edge.
Only the reference illegal flag masks instruction comparison; all flags remain
checked. Coverage sampling follows comparison. Valid-low ready-high advances
non-idle states; valid-low is not a universal freeze condition.

The corpus exhausts low16 with upper halves 0/ffff and valid 0/1, checks
additional full32 pass-through words, walks every legal multi-cycle encoding
with ready stalls and invalid advancement, and interrupts every sequence
position with reset. A bounded watchdog rejects missing termination. Corpus
reader rejects empty/truncated/extra/out-of-range data and requires full ordered
consumption. The manifest records source/generator/corpus hashes and tool version;
source modifications and a different reference revision are rejected.

Default TBIR is mandatory. Source coverage merges the default configuration
with a separately checked RV32ZC=1 output-gating probe; functional coverage
belongs exclusively to RV32ZC=3. Unknown X/Z values are not representable by
the native two-state backend. That specification bin requires an explicitly
reviewed scope exclusion, not a fabricated hit. No cocotb retirement is implied.

Run with HARC_BIN, ARCH_BIN (pinned .arch-version), and IBEX_REFERENCE_ROOT:

```
python -m pytest -q tests/test_harc_compressed_decoder.py
```

Independent code review by `/root/review_844` completed before first execution.
Findings addressed: the contradictory valid-low freeze specification is corrected
to ready-low, with consecutive checked non-first push stores proving the hold;
the selected ARCH version is checked against .arch-version and tool versions
are recorded. Reset tests check recovery at every sequence position after an
edge; they do not establish asynchronous reset latency between edges. The X/Z
row is explicitly outside the native gate, as already permitted by the spec.

## Measured result

The final native run passed 47 pytest tests (7 decoder/oracle-reader tests plus
40 shared-runner tests). It checked 682,537 cycles against the pinned upstream
RTL, hit 85/85 in-scope bins and 36/36 declared cross combinations, and reached
3/3 source line records and 110/110 branch/control records after the parameter
merge. These are the compiler's instrumented source records, not a claim that
it instruments every textual line. No source or cross waivers were required.
Machine-readable totals and provenance are in
[ibex_compressed_decoder_results.json](ibex_compressed_decoder_results.json).

The same HARC checker/corpus also passed against ARCH-emitted SystemVerilog.
Flipping one expected compressed flag made the compiled checker fail; malformed,
truncated, extra-data, empty, out-of-range and unconsumed corpora are rejected by
the reader tests. Full 32-bit input space, X/Z propagation and between-edge
asynchronous reset latency are not claimed. Existing cocotb tests remain active.

The red native run exposed 5,708 output mismatches before the fixes: c.sh
encoded its halfword offset at bit 0 instead of bit 1; large pop-frame word
offsets were sign-extended; final Zcmp flags ignored ready stalls; reserved
rlist flags diverged. A defensive invalid move-selector sequence also exposed
incorrect expansion/state behavior outside the stable-instruction producer
contract. The implementation now matches upstream on those cases.

This suite needs the native reference-linking fix in
[HARC #849](https://github.com/arch-hdl-lang/harc-com/pull/849), commit
5af1b6b1. Its multiple-relative-source regression failed before the fix and
passed afterward, together with 17 adjacent CLI tests. No v1 backend is used.
Independent plan, implementation, DUT-fix and final reviews were performed by
`/root/review_844`; their findings were addressed before the relevant reruns.
