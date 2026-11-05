#!/usr/bin/env bash
cd "$(git rev-parse --show-toplevel)" || exit 1
log=$(mktemp)
[ -x scripts/warm.sh ] && scripts/warm.sh >/dev/null 2>&1
for f in specs/*/done.txt; do
  [ -f "$f" ] || continue
  while IFS= read -r cmd; do
    [ -z "$cmd" ] && continue
    if ! bash -c "$cmd" >"$log" 2>&1; then echo "FAIL ($f): $cmd"; tail -n 40 "$log"; exit 1; fi
    echo "PASS: $cmd"
  done < "$f"
done
echo "ALL PASS"
