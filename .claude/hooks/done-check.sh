#!/usr/bin/env bash
cat >/dev/null
cd "$CLAUDE_PROJECT_DIR" || exit 0
active=""
for s in specs/*/STATUS.json; do
  [ "$(jq -r .phase "$s" 2>/dev/null)" = building ] && active="$active $(dirname "$s")"
done
[ -z "$active" ] && exit 0
for d in $active; do [ -f "$d/BLOCKED.md" ] && exit 0; done
out=$(bash scripts/done.sh 2>&1) && exit 0
jq -n --arg r "Done-conditions failing. Fix the implementation, not the tests or checks. If a check is wrong, write BLOCKED.md and stop.
$out" '{decision:"block", reason:$r}'
