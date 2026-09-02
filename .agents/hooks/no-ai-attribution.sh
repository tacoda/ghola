#!/usr/bin/env bash
# Rung 2 for `no-ai-attribution`: refuse a git commit whose message names a
# tool, before the commit runs.
#
# Declared in `.agents/settings.json` under `hooks.PreToolUse`. The rule's prose
# is `.agents/rules/no-ai-attribution.md`, and the delivery gate reads the same
# text again at rung 4. Two rungs on one rule is not duplication: this one gives
# the fast, local answer and the gate is the one an agent cannot route around.
#
# Reads the hook payload as JSON on stdin and refuses with exit 2, which is how
# Claude Code's PreToolUse contract blocks a call. Anything it cannot parse is
# allowed: a hook that fails closed on its own bug would block every commit,
# and the gate at rung 4 still reads the message.
set -euo pipefail

payload="$(cat)"

command_line="$(printf '%s' "$payload" \
  | python3 -c 'import json,sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
print((data.get("tool_input") or {}).get("command") or "")' 2>/dev/null || true)"

case "$command_line" in
  *git*commit*) ;;
  *) exit 0 ;;
esac

# The trailers and phrases the rule forbids, matched case-insensitively.
if printf '%s' "$command_line" | grep -qiE \
    'co-authored-by:[[:space:]]*(claude|anthropic)|generated with[[:space:]]+\[?claude|🤖'; then
  echo "no-ai-attribution: this commit message names a tool. The author is the" >&2
  echo "person who ran the job. Remove the trailer and commit again." >&2
  echo "Rule: .agents/rules/no-ai-attribution.md" >&2
  exit 2
fi

exit 0
