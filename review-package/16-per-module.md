# 16 — Per-module attribution of the Arch lane's area gap

The study reports the Arch lane's area gap only as whole-design totals
(`15-ecp5.md`, `14-sky130.md`). This file breaks those totals down by
module, from a **hierarchical** (unflattened) synthesis of the *same*
sv2v outputs the flattened runs consumed.

The flattened numbers remain the headline. This is a breakdown, not a
replacement, and §3 explains why the two do not — and cannot — agree.

> **Regenerated on arch 0.72.4** (2026-09-20). The first pass of this
> file was measured on 0.72.2 and reported `ibex_multdiv_fast` at
> +29,292 µm² (31.2 % of the sky130 delta). That was an arch-com defect,
> not a port cost: see §6a. On 0.72.4 the multdiv is +1,570 µm² (2.4 %)
> and the gap is the icache alone.

## 1. Inputs

Not regenerated. The same two files the flattened runs read, named by
`reports/<lane>_{ecp5,sky130}_synth.ys` as
`${REPO_ROOT}/flow/out/<lane>/ibex_top.v`:

| File | Lines | SHA-256 |
|---|--:|---|
| `flow/out/sv/ibex_top.v` | 17,373 | `b4bf28813ac6ed5320a5338850678c3e5d879c1b27b02601e20112622d05e3ed` |
| `flow/out/arch/ibex_top.v` | 16,346 | `9999d13627204a4df57adb8a172d4b20d4c9618fce85a6f6f1b3e74f593c2e6c` |

No hash of these files was recorded when the flattened runs were made,
so identity could not be confirmed by comparison. It was confirmed a
stronger way instead: **re-running the committed flattened scripts on
them reproduces the committed results exactly** — sv LUT4 9,963 /
TRELLIS_FF 2,534 (`reports/sv_ecp5_synth.stat`) and arch 15,910 / 3,440
(`reports/arch_ecp5_synth.stat`). Identical outputs from identical
scripts identify the inputs.

**Correction to the task brief.** TASK9 quotes the ECP5 gap as "+5,971
LUT4 and +906 FFs". The committed pair gives **+5,947 / +906**. The FF
figure matches exactly; the LUT figure matches no committed pair
(`arch_ecp5_rvfi_synth.stat` gives +5,788, `arch_ecp5_v0720_synth.stat`
+5,890, after-packing figures +5,812 and +5,914), and the string
"5,971" appears in no file in this package. Read as +5,947 throughout.

`15-ecp5.md` §5.1 previously cited `reports/arch_ecp5_synth.stat` for
"15,751". Its numbers are right for what §5.1 measures — the Arch top
*with* RVFI ports — but §5.4 later removed those ports and kept the
old reports as `reports/arch_ecp5_rvfi_*`, leaving the citation
pointing at a file that had moved on. Corrected in the same change as
this file: §5.1 now cites `reports/arch_ecp5_rvfi_synth.stat`, with a
note that the unsuffixed `arch_ecp5_synth.stat` holds the RVFI-off
figures. At the 0.72.4 pin that file holds 16,142 / 3,440, which is
what this breakdown uses; the 15,910 / 3,440 above is the 0.72.2 value
the input check reproduced.

## 2. Method

`flow/ecp5_hier_stat.sh` and `flow/sky130_hier_stat.sh` mirror the
committed flattened scripts exactly except that the flatten step is
omitted. They keep the full `-chparam` list and the ECP5 clock-gating
overwrite; without those the design elaborates differently and the
numbers would describe a different core. TASK9's one-line form omits
both.

Reports: `reports/{sv,arch}_ecp5_hier.stat`,
`reports/{sv,arch}_sky130_hier_area.rpt`.

Per-module figures are **local** counts (excluding submodules)
multiplied by each module's instance multiplicity, walked from
`ibex_top`. The method is self-checking: the per-module contributions
sum to the whole-design total to the last unit (sky130 sv
1,809,779.5 µm² and arch 1,903,684.5 µm², both exact).

Four Arch-lane modules have no upstream counterpart and are folded into
the upstream module they came from, as `01-inventory.md` documents:
`IbexIcacheOutputStage`, `InvalCtrl` and `FbAgeArb` ×2 into
`ibex_icache`; `_ibex_multdiv_fast_threads` into `ibex_multdiv_fast`.
Unfolded, one ported module appears as several rows and the table
misreads as "a large new module appeared".

## 3. Flattened vs unflattened — read this before the table

All figures arch **0.72.4** (the pinned release), matching §4.

| Lane | Unflattened | Flattened | Cost of not flattening |
|---|---|---|--:|
| sv | 14,569 LUT4 / 2,578 FF | 9,963 / 2,534 | +4,606 LUT4 |
| arch | 18,171 LUT4 / 3,498 FF | 16,142 / 3,440 | +2,029 LUT4 |

| | LUT4 | FF |
|---|--:|--:|
| **flattened delta (headline)** | **+6,179** | **+906** |
| unflattened delta (this table) | +3,602 | +920 |

Cross-module optimisation removes 4,606 LUT4 from the sv lane but only
2,029 from the Arch lane. **About 2,577 LUT4 — 42 % of the headline LUT
gap — exists only under flattening** and is attributable to no module:
it is the sv lane optimising across module boundaries more effectively.
The flop gap is stable across both views (+906 vs +920), so the flop
attribution below carries over to the flattened figure; the LUT
attribution accounts for the +3,602, not the +6,179.

(At 0.72.2 these were +5,947 flattened / +3,740 unflattened, 37 %. The
flattened Arch LUT4 rose 15,910 → 16,142 with PR #1028 because ECP5
folds multiplies into its one hard `MULT18X18D`, so the shared-MAC
harness costs LUT4 on this target while saving 28,491 µm² on sky130 —
see §6a and `15-ecp5.md` §5.6.)

## 4. Attribution

Percentages are of that measure's unflattened total delta at 0.72.4
(LUT4 +3,602, FF +920, sky130 +66,183 µm²). Sorted by |Δ sky130|.
Modules identical on all three measures are omitted.

| Module | LUT4 sv | arch | Δ | FF sv | arch | Δ | sky130 sv | arch | Δ | % sky |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `ibex_icache` | 1,750 | 7,081 | +5,331 | 579 | 1,496 | +917 | 30,163 | 95,443 | +65,280 | 98.6% |
| `ibex_pmp` | 2,439 | 1,115 | -1,324 | 0 | 0 | +0 | 18,704 | 13,179 | -5,525 | -8.3% |
| `ibex_register_file_ff` | 4,314 | 3,867 | -447 | 992 | 992 | +0 | 47,554 | 52,166 | +4,612 | 7.0% |
| `ibex_multdiv_fast` | 909 | 919 | +10 | 81 | 84 | +3 | 20,551 | 22,121 | +1,570 | 2.4% |
| `prim_ram_1p` | 33 | 33 | +0 | 0 | 0 | +0 | 1,629,162 | 1,627,864 | -1,299 | -2.0% |
| `ibex_id_stage` | 420 | 467 | +47 | 71 | 71 | +0 | 4,887 | 5,600 | +713 | 1.1% |
| `ibex_compressed_decoder` | 702 | 745 | +43 | 18 | 20 | +2 | 4,030 | 4,621 | +591 | 0.9% |
| `ibex_counter` | 135 | 136 | +1 | 128 | 128 | +0 | 6,984 | 7,490 | +505 | 0.8% |
| `ibex_alu` | 541 | 515 | -26 | 0 | 0 | +0 | 5,160 | 5,484 | +324 | 0.5% |
| `ibex_decoder` | 291 | 232 | -59 | 0 | 0 | +0 | 1,191 | 1,081 | -110 | -0.2% |
| `ibex_controller` | 304 | 304 | +0 | 21 | 20 | -1 | 2,390 | 2,342 | -48 | -0.1% |
| `ibex_load_store_unit` | 423 | 465 | +42 | 68 | 67 | -1 | 4,696 | 4,662 | -34 | -0.1% |
| `ibex_if_stage` | 196 | 180 | -16 | 88 | 88 | +0 | 3,719 | 3,711 | -8 | -0.0% |
| `ibex_core` | 10 | 10 | +0 | 0 | 0 | +0 | 482 | 485 | +4 | 0.0% |
| **total** | **14,519** | **18,121** | **+3,602** | **2,232** | **3,152** | **+920** | **1,809,733** | **1,876,310** | **+66,183** | |

## 5. Findings

**The gap is one module.** `ibex_icache` is **98.6 % of the sky130 area
delta, 99.7 % of the flop delta**, and on ECP5 it exceeds the net LUT
delta outright (+5,331 against a net +3,602) because two modules move
the other way: `ibex_pmp` is 54 % smaller in the Arch lane (−1,324 LUT4,
−5,525 µm²) and `ibex_register_file_ff` 10 % smaller on LUT4 (−447).
Every other module is within ±713 µm² and ±59 LUT4.

Top three by measure:

| Measure | Top 3 | Share |
|---|---|--:|
| sky130 area | `ibex_icache`, `ibex_pmp`, `ibex_register_file_ff` | 98.6 % / −8.3 % / 7.0 % |
| ECP5 FF | `ibex_icache` (+917), `ibex_multdiv_fast` (+3), `ibex_compressed_decoder` (+2) | 100 % |
| ECP5 LUT4 | `ibex_icache`, `ibex_pmp`, `ibex_register_file_ff` | signs oppose |

**`ibex_multdiv_fast` is no longer a contributor.** On 0.72.2 it was
+29,292 µm² (31.2 % of the sky130 delta) and the one result that did not
fit the pattern — large on sky130, negligible on ECP5. That was an
arch-com defect (§6a). On 0.72.4 it is **+1,570 µm² (2.4 %)** and
**+10 LUT4**, i.e. within noise of upstream.

**Modules where the Arch lane is smaller**: `ibex_pmp` (−1,324 LUT4,
−5,525 µm²), `ibex_decoder`, `ibex_controller`, `ibex_alu`,
`ibex_if_stage`, `ibex_load_store_unit`, and `ibex_register_file_ff` on
ECP5 LUT4 (though +4,612 µm² on sky130). **If `ibex_icache` matched its
upstream counterpart, the Arch lane would be smaller than the sv lane**
on both measures.

**The RAMs are not implicated.** `prim_ram_1p` differs by −1,299 µm² on
1.63 M — 86 % of the sky130 design area, essentially identical between
lanes. Both lanes carry 6 DP16KD on ECP5. The sky130 ratio is low for
this reason: RAM area dominates the denominator.

**Do not scale this to the routed design.** These are unflattened
synthesis figures. Post-P&R the whole-design gap is 1.075×
(2,449,039 vs 2,277,607 µm², `14-sky130.md` Table 10) — the multdiv fix
that removes 28,491 µm² at synthesis removes only 8,986 µm² after P&R,
because the core is 78 % sequential and the flow re-spends part of the
saving on timing-repair buffering. This table says *where* the logic
difference sits, not what it costs on silicon.

### Top contributor: cell-type breakdown

`ibex_icache`, recursive, ECP5:

| Cell | sv | arch | Δ | ratio |
|---|--:|--:|--:|--:|
| LUT4 | 1,750 | 7,081 | +5,331 | 4.0× |
| PFUMX (mux) | 296 | 1,582 | +1,286 | 5.3× |
| TRELLIS_FF | 579 | 1,496 | +917 | 2.6× |
| L6MUX21 (mux) | 61 | 353 | +292 | 5.8× |
| CCU2C (carry) | 35 | 118 | +83 | 3.4× |

The two mux primitives grow fastest (5.3× and 5.8×) and carry slowest
(3.4×); flops grow least of all (2.6×). The expanded structure is
selection logic, not arithmetic.

As TASK9 directs: this is the **RVFI-off** configuration, and
`IbexIcache.arch` was the most-revised file in the port.

## 6a. The multdiv difference was a compiler defect (fixed in 0.72.4)

The first pass of this file, on arch 0.72.2, reported
`ibex_multdiv_fast` at **+29,292 µm² (31.2 % of the sky130 delta)** and
**+148 LUT4 (4.0 %)** on ECP5 — the one row whose two targets
disagreed. That signature was the clue: the module emitted **four
multipliers where one was intended**, and ECP5 folds multiplies into its
one hard `MULT18X18D`, so duplication was nearly free there and glaring
on standard cells.

`src/IbexMultdivFast.arch` declares `shared function MacRes`, which
exists so an operator called from several thread states emits as ONE
instance fed by state-selected operand muxes. arch-com's collector binds
a call site by reading the state value out of the enclosing
`_tN_state == <value>` comparison, and matched only a bare numeric
literal. arch-com #247 (`65e5e89d`, 2026-05-11) rewrote those
comparisons to reference a per-state localparam (`_t0_S1_action`), so
the collector could no longer recover the value, bound no call sites,
emitted no harness, and every call inlined its own copy of the MAC.

Nothing failed: the SV stayed correct and simply got bigger. The feature
had shipped four days earlier across 562 lines and five source files
**with no tests at all**, so nothing caught it. It was found here by
per-module attribution, bisected to `65e5e89d`, and confirmed against a
preserved May build artifact that still contained the working harness
(56 `__shared_` references; 20,420 µm² synthesised today).

Fixed in **arch-com PR #1028**, released in **v0.72.4**, with the
regression test the feature should have had:

| `ibex_multdiv_fast` | `$mul` | sky130 area |
|---|--:|--:|
| 0.72.2 | 4 | 50,595 µm² |
| **0.72.4** | **1** | **22,104 µm²** (−56 %) |
| upstream `ibex_multdiv_fast` | 1 | ~21,100 µm² |

Note the fix is **not** a uniform improvement: ECP5 synthesis LUT4 rises
by 232 (16,142 vs 15,910) because the harness's operand muxes are real
LUTs while the duplicated MACs were absorbed by the single hard DSP.
fmax after P&R is unchanged within seed noise. The win is a
standard-cell effect.

## 6. The icache difference is a design difference

Per TASK9 §5 (one module ≥ 40 % of the delta), the structural counts,
with no causal claim beyond them.

The Arch icache's **own** logic holds *fewer* flops than upstream's:
549 vs 579. The entire +917 is in `IbexIcacheOutputStage`, a module
with no upstream counterpart, whose declared registers total 943 bits
against 934 synthesised flops:

| Bits | Register |
|--:|---|
| 512 | `recent_line_q` |
| 232 | `recent_addr_q` |
| 8 | `recent_valid_q` |
| 64 | `ic1_hold_line_q` |
| 32 | `hold_rdata_q`, 32 `addr_out_q`, 29 `ic1_hold_addr_q`, 16 `skid_data_q` |
| 15 | assorted flags and `_*_written` markers |

The three `recent_*` arrays are one structure — 8 entries × (29-bit
address + 64-bit line + 1 valid) = 752 bits, **82 % of the +917 flop
delta**. The upstream icache contains no reference to `recent`; it has
no equivalent. Upstream's `skid_data_q` does have an Arch counterpart,
so the skid buffer was carried over; the replay arrays were added.

Declaration counts are **not** comparable across lanes and are not
presented side by side: sv2v expands upstream's fill-buffer arrays and
generate loops into forms a declaration scan under-counts (157 declared
bits against 579 synthesised flops), whereas the Arch output stage maps
almost 1:1 (943 against 934). Only synthesised counts are used above.

### Provenance

The buffer was added deliberately, as icache performance work, and its
area was already reduced once. From the history, all 2026-05-10:

| Commit | |
|---|---|
| `9da7204` | Add opt-in CoreMark comparison harness |
| `631ed75` | Fix icache CoreMark stalls |
| `8cb5fa8` | **Add icache output replay buffer** — introduces `recent_*` |
| `eb90507` | Bias icache bus arbitration toward demand fills |
| `7ea4a49` | **Trim icache output replay area** — 16 entries → 8 |

`8cb5fa8` tightened `s4_branch_into_inflight_line_cam_target` from
`new_line_reqs <= 1` to `== 0`, i.e. no redundant bus request for a
line already in flight. `7ea4a49` halved the arrays
(`Vec<_, 16>` → `Vec<_, 8>`) and removed 86 lines from
`IbexIcache.arch`. The recorded CoreMark result for the lane is a ratio
of **1.0134** (113,150 vs 111,651 ticks), later **1.0108**
(`02-functional.md`, `changes/2026-05-11-multdiv-activity-gate/results.md`).

**Consequence for the headline.** The dominant term in the area gap is
a structure the Arch port has and upstream Ibex does not, added to close
a cycle-count gap and already halved on area grounds. The comparison is
therefore between two icaches that differ architecturally, not between
two emissions of one design. A reader taking "+6,179 LUT4" as ARCH's
emission overhead would be reading it wrongly. Quantifying the two
separately would need an Arch-lane build with the replay buffer
bypassed; that variant was **not** built, because it fails the test the
buffer exists to satisfy and would not be a working design.
