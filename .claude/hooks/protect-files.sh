#!/usr/bin/env bash
file="/$(jq -r '.tool_input.file_path // .tool_input.notebook_path // empty' | tr '\\' '/')"
block() { echo "Blocked: $file is protected by the build packet. Fix the implementation; if the protected file is wrong, write specs/<slug>/BLOCKED.md with the exact proposed diff and stop." >&2; exit 2; }
ALWAYS=("/scripts/done.sh" "/scripts/warm.sh" "/.claude/" "/.github/" "/specs/BUILD-PACKET-" "/tests/e2e/" "conftest.py" "pytest.ini" "/pyproject.toml" "/.gitlab-ci")
for p in "${ALWAYS[@]}"; do [[ "$file" == *"$p"* ]] && block; done
slug=""
case "$file" in
  */tests/acceptance/*) slug=$(sed -E 's#.*/tests/acceptance/([^/]+)/.*#\1#' <<<"$file");;
  */specs/*/done.txt)   slug=$(sed -E 's#.*/specs/([^/]+)/done\.txt#\1#' <<<"$file");;
esac
if [ -n "$slug" ]; then
  phase=$(jq -r .phase "$CLAUDE_PROJECT_DIR/specs/$slug/STATUS.json" 2>/dev/null)
  [ "$phase" = plan ] || block
fi
exit 0
