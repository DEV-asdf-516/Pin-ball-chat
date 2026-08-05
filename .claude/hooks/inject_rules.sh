#!/bin/bash
# UserPromptSubmit hook: 세션 모델이 sonnet/luna(워커)일 때만 core_rules.md를 주입
RULES_FILE="$(dirname "$0")/core_rules.md"
if [ ! -f "$RULES_FILE" ]; then
  exit 0
fi

HOOK_INPUT="$(cat)"

MODEL="$(printf '%s' "$HOOK_INPUT" | jq -r '.model // empty' 2>/dev/null)"
if [ -z "$MODEL" ]; then
  # 입력에 모델 필드가 없으면 transcript의 마지막 assistant 메시지에서 추출
  TRANSCRIPT_PATH="$(printf '%s' "$HOOK_INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)"
  if [ -f "$TRANSCRIPT_PATH" ]; then
    MODEL="$(tail -c 200000 "$TRANSCRIPT_PATH" | grep -o '"model":"[^"]*"' | tail -1)"
  fi
fi

case "$MODEL" in
  *sonnet*|*luna*)
    cat "$RULES_FILE"
    ;;
  "")
    # 모델 확인 불가(세션 첫 프롬프트 등) — 규칙 적용 쪽이 안전
    cat "$RULES_FILE"
    ;;
  *)
    exit 0
    ;;
esac
