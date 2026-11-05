#!/usr/bin/env bash
cmd=$(jq -r '.tool_input.command // empty')
if grep -qE '(tests/acceptance|tests/e2e|done\.(sh|txt)|warm\.sh|\.claude/|\.github/|conftest\.py|pytest\.ini|BUILD-PACKET-)' <<<"$cmd" \
 && grep -qE '(>|sed -i|\brm\b|\bmv\b|\bcp\b|\btee\b|truncate|git (checkout|restore|rm)|chmod)' <<<"$cmd"; then
  echo "Blocked: this shell command looks like a write to a protected path. Read-only? Rerun it without redirects. Otherwise write BLOCKED.md and stop." >&2; exit 2
fi
exit 0
