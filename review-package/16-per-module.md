# 16 — Per-module attribution of the Arch lane's area gap

The study reports the Arch lane's area gap only as whole-design totals
(`15-ecp5.md`, `14-sky130.md`). This file breaks those totals down by
module, from a **hierarchical** (unflattened) synthesis of the *same*
sv2v outputs the flattened runs consumed.

The flattened numbers remain the headline. This is a breakdown, not a
replacement, and §3 explains why the two do not — and cannot — agree.

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

Note also that `15-ecp5.md`'s headline table cites
`reports/arch_ecp5_synth.stat` for "15,751", which is the value in
`reports/arch_ecp5_rvfi_synth.stat`; `arch_ecp5_synth.stat` holds
15,910. The citation and the number disagree in the existing file.

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

| Lane | Unflattened | Flattened | Cost of not flattening |
|---|---|---|--:|
| sv | 14,569 LUT4 / 2,578 FF | 9,963 / 2,534 | +4,606 LUT4 |
| arch | 18,309 LUT4 / 3,498 FF | 15,910 / 3,440 | +2,399 LUT4 |

| | LUT4 | FF |
|---|--:|--:|
| **flattened delta (headline)** | **+5,947** | **+906** |
| unflattened delta (this table) | +3,740 | +920 |

Cross-module optimisation removes 4,606 LUT4 from the sv lane but only
2,399 from the Arch lane. **About 2,207 LUT4 — 37 % of the headline LUT
gap — exists only under flattening** and is attributable to no module:
it is the sv lane optimising across module boundaries more effectively.
The flop gap is stable across both views (+906 vs +920), so the flop
attribution below carries over to the flattened figure; the LUT
attribution accounts for the +3,740, not the +5,947.

## 4. Attribution

Percentages are of that measure's unflattened total delta (LUT4 +3,740,
FF +920, sky130 +94,298 µm²). Sorted by |ΔLUT4|. Modules identical on
all three measures are omitted.

| Module | LUT4 sv | arch | Δ | % | FF sv | arch | Δ | % | sky130 sv | arch | Δ | % |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `ibex_icache` | 1,750 | 7,081 | +5,331 | 142.5% | 579 | 1,496 | +917 | 99.7% | 30,163 | 95,443 | +65,280 | 69.5% |
| `ibex_pmp` | 2,439 | 1,115 | -1,324 | -35.4% | 0 | 0 | +0 | 0.0% | 18,704 | 13,179 | -5,525 | -5.9% |
| `ibex_register_file_ff` | 4,314 | 3,867 | -447 | -12.0% | 992 | 992 | +0 | 0.0% | 47,554 | 52,166 | +4,612 | 4.9% |
| `ibex_multdiv_fast` | 909 | 1,057 | +148 | 4.0% | 81 | 84 | +3 | 0.3% | 20,551 | 49,843 | +29,292 | 31.2% |
| `ibex_decoder` | 291 | 232 | -59 | -1.6% | 0 | 0 | +0 | 0.0% | 1,191 | 1,081 | -110 | -0.1% |
| `ibex_id_stage` | 420 | 467 | +47 | 1.3% | 71 | 71 | +0 | 0.0% | 4,887 | 5,600 | +713 | 0.8% |
| `ibex_compressed_decoder` | 702 | 745 | +43 | 1.1% | 18 | 20 | +2 | 0.2% | 4,030 | 4,621 | +591 | 0.6% |
| `ibex_load_store_unit` | 423 | 465 | +42 | 1.1% | 68 | 67 | -1 | -0.1% | 4,696 | 4,662 | -34 | -0.0% |
| `ibex_alu` | 541 | 515 | -26 | -0.7% | 0 | 0 | +0 | 0.0% | 5,160 | 5,484 | +324 | 0.3% |
| `ibex_if_stage` | 196 | 180 | -16 | -0.4% | 88 | 88 | +0 | 0.0% | 3,719 | 3,711 | -8 | -0.0% |
| `ibex_counter` | 135 | 136 | +1 | 0.0% | 128 | 128 | +0 | 0.0% | 6,984 | 7,490 | +505 | 0.5% |
| `ibex_controller` | 304 | 304 | +0 | 0.0% | 21 | 20 | -1 | -0.1% | 2,390 | 2,342 | -48 | -0.1% |
| `ibex_core` | 10 | 10 | +0 | 0.0% | 0 | 0 | +0 | 0.0% | 482 | 485 | +4 | 0.0% |
| `prim_ram_1p` | 33 | 33 | +0 | 0.0% | 0 | 0 | +0 | 0.0% | 1,629,162 | 1,627,864 | -1,299 | -1.4% |
| **total** | **14,519** | **18,259** | **+3,740** | | **2,232** | **3,152** | **+920** | | **1,809,733** | **1,904,031** | **+94,298** | |

## 5. Findings

**The gap is maximally concentrated, not spread.** On ECP5 one module —
`ibex_icache` — accounts for **142.5 % of the net LUT delta and 99.7 %
of the flop delta**. It exceeds 100 % because two modules move the other
way: `ibex_pmp` is 54 % smaller in the Arch lane (−1,324 LUT4) and
`ibex_register_file_ff` 10 % smaller (−447). Eight of the twelve
non-trivial modules move by less than ±60 LUT4. TASK9's "top 3 ≥ 60 %"
concentration test is met by the top module alone.

Top three by measure:

| Measure | Top 3 | Share |
|---|---|--:|
| ECP5 LUT4 | `ibex_icache`, `ibex_pmp`, `ibex_register_file_ff` | 190 % of net (signs oppose) |
| ECP5 FF | `ibex_icache` (+917), `ibex_multdiv_fast` (+3), `ibex_compressed_decoder` (+2) | 100 % |
| sky130 area | `ibex_icache`, `ibex_multdiv_fast`, `ibex_register_file_ff` | 105.6 % |

**sky130 and ECP5 disagree about second place.** `ibex_multdiv_fast` is
+4.0 % of the LUT delta on ECP5 but **+31.2 % of the area delta on
sky130** (+29,292 µm²). ECP5 absorbs its structure into LUT4s and carry
chains; the standard-cell flow does not. Any single-target reading of
"which module costs most" is therefore target-dependent below the top
entry.

**Modules where the Arch lane is smaller**: `ibex_pmp` (−1,324 LUT4,
−5,525 µm²), `ibex_register_file_ff` (−447 LUT4 on ECP5, though +4,612
µm² on sky130), `ibex_decoder`, `ibex_controller`, `ibex_alu`,
`ibex_if_stage`, `ibex_load_store_unit`. If `ibex_icache` matched its
upstream counterpart, the Arch lane would be **smaller** than the sv
lane on unflattened ECP5 LUT4.

**The RAMs are not implicated.** `prim_ram_1p` is 1,629,162 µm² (sv) vs
1,627,864 (arch), a −1,299 µm² difference on 1.63 M — 86 % of the
sky130 design area, and essentially identical between lanes. Both lanes
carry 6 DP16KD on ECP5. The sky130 ratio of 1.052× is low for this
reason: RAM area dominates the denominator.

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
two emissions of one design. A reader taking "+5,947 LUT4" as ARCH's
emission overhead would be reading it wrongly. Quantifying the two
separately would need an Arch-lane build with the replay buffer
bypassed; that variant was **not** built, because it fails the test the
buffer exists to satisfy and would not be a working design.
