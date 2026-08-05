#!/bin/bash

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"

# CORE RULES는 .claude/hooks/core_rules.md가 단일 원본 — 복사본을 두지 않고 직접 읽는다.
CORE_RULES_FILE="$HOOK_DIR/../../.claude/hooks/core_rules.md"

if [ -f "$CORE_RULES_FILE" ]; then
    cat "$CORE_RULES_FILE"
    echo ""
fi

