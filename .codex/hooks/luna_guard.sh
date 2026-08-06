#!/bin/bash
# codex 워커(Luna) PreToolUse 가드 — exit 2 + stderr = 차단, exit 0 = 허용
# stdin 으로 {tool_name, tool_input, cwd} JSON 페이로드를 받는다.

payload="$(cat)"

command_text="$(printf '%s' "$payload" | jq -r '
  .tool_input as $input
  | if ($input | type) != "object" then ($input // "" | tostring)
    elif ($input.command | type) == "array" then ($input.command | join(" "))
    else ($input.command // "" | tostring)
    end' 2>/dev/null)"

if [ -z "$command_text" ]; then
    exit 0
fi

case "$command_text" in
  *"git commit"*|*"git push"*)
    echo "[BLOCK] Luna 는 git commit/push 를 할 수 없다. 커밋은 사용자가 요청했을 때 Sonnet 에게 위임된다." >&2
    exit 2
    ;;
esac

exit 0
