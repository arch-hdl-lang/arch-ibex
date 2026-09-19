#!/usr/bin/env bash
# Refuse to publish commits whose blobs carry identifying strings.
#
# The working tree being clean says nothing about history: a scrub commit
# leaves every earlier commit dirty. This scans the *commits being pushed*,
# so the gate fires on the range, not the tip.
#
# Usage:
#   scripts/sanitize_check.sh <rev-range>...     # e.g. origin/main..HEAD
#   scripts/sanitize_check.sh --pre-push         # reads git's pre-push stdin
#
# Exit 0 = clean, 1 = something identifying is in the range, 2 = usage error.
#
# Patterns are derived from the environment, never written out, so this file
# does not itself contain the strings it exists to block.

set -uo pipefail

ZERO=0000000000000000000000000000000000000000

# 1. username by 5-char PREFIX — a whole-login grep cannot match a truncation
#    of that login, which is exactly how 38 occurrences once survived.
# 2. macOS per-user temp ids.
# 3. $HOME-style absolute paths.
USER_PREFIX=$(id -un | cut -c1-5)
PATTERNS=(
  "$USER_PREFIX"
  '/var/folders/[a-z0-9]{2}/[a-z0-9_]{30,}'
  '/(Users|home)/[a-z]'
)
LABELS=(
  "username prefix ('$USER_PREFIX')"
  "macOS per-user temp id"
  "\$HOME-style absolute path"
)

collect_ranges() {
  if [ "${1:-}" = "--pre-push" ]; then
    while read -r _local_ref local_sha _remote_ref remote_sha; do
      [ "$local_sha" = "$ZERO" ] && continue          # branch deletion
      if [ "$remote_sha" = "$ZERO" ]; then
        printf '%s --not --remotes\n' "$local_sha"    # new branch
      else
        printf '%s..%s\n' "$remote_sha" "$local_sha"
      fi
    done
  else
    printf '%s\n' "$@"
  fi
}

mapfile -t RANGES < <(collect_ranges "$@") 2>/dev/null || {
  # bash 3.2 (macOS default) has no mapfile
  RANGES=(); while IFS= read -r l; do RANGES+=("$l"); done < <(collect_ranges "$@")
}

[ ${#RANGES[@]} -eq 0 ] && { echo "sanitize-check: nothing to scan"; exit 0; }

# Scan only blobs this push would ADD — objects in the range that are not
# already reachable from a remote ref. Scanning whole trees instead would
# re-flag content the remote already has (this repo inherits 7 such files
# from origin/main), so the gate would refuse every push forever and be
# bypassed with --no-verify on reflex. A gate that always fires is a gate
# nobody reads.
FAILED=0
for range in "${RANGES[@]}"; do
  # shellcheck disable=SC2086
  NEW_OBJS=$(git rev-list --objects $range --not --remotes 2>/dev/null)
  [ -z "$NEW_OBJS" ] && continue

  # keep blobs only, carrying their path along
  BLOBS=$(printf '%s\n' "$NEW_OBJS" \
    | awk 'NF>1 {print $1, $2}' \
    | while read -r sha path; do
        [ "$(git cat-file -t "$sha" 2>/dev/null)" = blob ] && printf '%s %s\n' "$sha" "$path"
      done)
  [ -z "$BLOBS" ] && continue
  n=$(printf '%s\n' "$BLOBS" | wc -l | tr -d ' ')
  echo "sanitize-check: scanning $n new blob(s) in '$range'"

  for i in 0 1 2; do
    # `tr -d '\000'` makes binary blobs safe to grep as text. Do NOT try to
    # detect binaries with grep -q $'\0': the shell expands $'\0' to the empty
    # string, grep then matches every blob, and the scan silently passes
    # everything. That false negative was caught by testing the gate against a
    # range known to be dirty -- keep doing that after any edit here.
    HITS=$(printf '%s\n' "$BLOBS" | while read -r sha path; do
      git cat-file blob "$sha" 2>/dev/null \
        | LC_ALL=C tr -d '\000' \
        | LC_ALL=C grep -Eq -e "${PATTERNS[$i]}" && printf '%s\n' "$path"
    done | sort -u)
    if [ -n "$HITS" ]; then
      FAILED=1
      c=$(printf '%s\n' "$HITS" | wc -l | tr -d ' ')
      echo
      echo "  BLOCKED: ${LABELS[$i]} - $c newly added file(s)"
      printf '%s\n' "$HITS" | head -20 | sed 's/^/    /'
      [ "$c" -gt 20 ] && echo "    ... and $((c - 20)) more"
    fi
  done
done

if [ "$FAILED" -ne 0 ]; then
  cat <<'MSG'

sanitize-check: REFUSING THE PUSH.

The working tree may be clean; these hits are in the COMMITS being
pushed. Scrubbing the tip does not fix them — the history has to be
rewritten before this range is published. See review-package/06-sanitize.md
("History: not rewritten, with a trigger") for the scoped filter-repo
command, then re-run this check.

To push anyway (you are publishing the strings above): git push --no-verify
MSG
  exit 1
fi

echo "sanitize-check: clean"
exit 0
