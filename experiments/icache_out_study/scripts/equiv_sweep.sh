#!/bin/bash
# equiv_sweep.sh <pair> <cycles> -- run equivalence over flag sets x seeds x err, print summary
D=${STUDY_SCRATCH:?}/cosim
pair="$1"; cyc="$2"
tot=0; eqfail=0; r2fail=0; runs=0
for fl in 0 1 2 9 17 25; do
  for s in 11 12 13 14 15 16 17 18; do
    for em in 0 1; do
      log="$D/b_$pair/sweep_${s}_${em}_${fl}.log"
      "$D/b_$pair/obj_dir/cosim" "$s" "$cyc" 1 "$em" $((s % 4)) "$fl" > "$log"
      e=$(grep -c "EQUIV mismatch" "$log"); r=$(grep -c "DUT R-OUT-2" "$log")
      runs=$((runs+1)); eqfail=$((eqfail+e)); r2fail=$((r2fail+r))
      tot=$((tot + cyc))
      [ "$e" != 0 ] && { echo "flags=$fl seed=$s err=$em EQUIV mismatches (first):"; grep -m2 "EQUIV" "$log"; }
    done
  done
done
echo "pair=$pair runs=$runs cycles_total=$tot equiv_mismatch_lines=$eqfail dut_rout2_lines=$r2fail"
