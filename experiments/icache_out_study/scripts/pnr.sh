#!/bin/bash
# pnr.sh <cfg> <par> [seeds...] -- run nextpnr seeds for a tagged ECP5 synth, <par> at a time.
source ${STUDY_SCRATCH:?}/env.sh
cfg="$1"; par="$2"; shift 2
seeds="${*:-1 2 3 4 5 6 7 8 9 10}"
cd "$W" || exit 1
n=0
for s in $seeds; do
  SEEDS="$s" ECP5_TAG="$cfg" bash flow/ecp5_pnr.sh pnr arch > "$S/res/$cfg/pnr_seed$s.out" 2>&1 &
  n=$((n+1))
  if [ $n -ge $par ]; then wait -n 2>/dev/null || wait; n=$((n-1)); fi
done
wait
echo "pnr $cfg done $(date +%T)"
