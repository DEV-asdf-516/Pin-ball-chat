#!/usr/bin/env bash
# =============================================================
# 문서 합의 루프: Fable(문서 소유자) ↔ Sol(검증자) 수렴 강제
# 파일 경로: .claude/skills/feature/scripts/consensus-loop.sh
# 사용법: consensus-loop.sh design|impl  (저장소 루트에서 실행)
#   design: $WORK_DIR/design.md 합의 (초안이 이미 있어야 함)
#   impl:   $WORK_DIR/implementation.md 합의 (design.md 합의가 선행 조건)
# 종료 코드: 0=PASS 수렴, 2=라운드 초과/교착, 1=환경 오류
# 리뷰는 MAX_SPEC_ROUNDS+1 회 — 마지막 수정도 반드시 재검증한다.
# 라운드 한도는 문서별로 각각 적용된다.
# =============================================================
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$SKILL_DIR/config.sh"

DOC_MODE="${1:-}"
case "$DOC_MODE" in
  design)
    DOC_FILE="$WORK_DIR/design.md"
    SOL_TEMPLATE="sol-review-design.md"
    FABLE_TEMPLATE="fable-revise-design.md"
    ;;
  impl)
    DOC_FILE="$WORK_DIR/implementation.md"
    SOL_TEMPLATE="sol-review-impl.md"
    FABLE_TEMPLATE="fable-revise-impl.md"
    ;;
  *)
    echo "[FAIL] 사용법: consensus-loop.sh design|impl" >&2; exit 1;;
esac

# ---------- 사전 점검 (환경이 틀리면 진행 금지) ----------
for bin in "$CLAUDE_BIN" "$CODEX_BIN" jq uuidgen envsubst; do
  command -v "$bin" >/dev/null 2>&1 || { echo "[FAIL] '$bin' 미설치. 중단." >&2; exit 1; }
done
[ -f "$DOC_FILE" ] || { echo "[FAIL] $DOC_FILE 없음. Fable이 초안을 먼저 작성해야 함." >&2; exit 1; }
if [ "$DOC_MODE" = "impl" ]; then
  [ -f "$WORK_DIR/design.md" ] || { echo "[FAIL] $WORK_DIR/design.md 없음. 설계 합의(design 모드)가 선행되어야 함." >&2; exit 1; }
fi
mkdir -p "$WORK_DIR/reviews"
touch "$WORK_DIR/decisions.md"

SCHEMA_FILE="$SKILL_DIR/schemas/spec-review.schema.json"
[ -f "$SCHEMA_FILE" ] || { echo "[FAIL] 스키마 없음: $SCHEMA_FILE" >&2; exit 1; }
prev_fingerprint=""
prev_review=""

for round in $(seq 1 $((MAX_SPEC_ROUNDS + 1))); do
  tag=$(printf '%02d' "$round")
  review="$WORK_DIR/reviews/sol-$DOC_MODE-round-$tag.json"
  echo "=== [$DOC_MODE] Round $round/$((MAX_SPEC_ROUNDS + 1)) : Sol 검토 ==="

  prev_context=""
  if [ -n "$prev_review" ]; then
    prev_context="직전 라운드 리뷰는 $prev_review 에 있다. 같은 문제를 다시 지적할 때는 반드시 같은 id를 재사용하고, 새 문제에만 새 id를 붙여라. $WORK_DIR/decisions.md 에서 REJECT 된 이슈는 새로운 논거가 없으면 재제기하지 마라."
  fi

  # ---------- Sol (Codex) 검토: 읽기 전용, 스키마 강제 JSON ----------
  export WORK_DIR PREV_CONTEXT="$prev_context"
  sol_prompt="$(render_prompt "$SOL_TEMPLATE" '${WORK_DIR} ${PREV_CONTEXT}')"
  "$CODEX_BIN" exec -m "$SOL_MODEL" -c "model_reasoning_effort=\"$SOL_EFFORT\"" --sandbox read-only \
    --output-schema "$SCHEMA_FILE" -o "$review" \
    "$sol_prompt" \
    > "$review.log" 2>&1 || { echo "[FAIL] codex 실행 실패 (모델 '$SOL_MODEL' 확인)"; tail -20 "$review.log" >&2; exit 1; }

  verdict=$(jq -er '.verdict' "$review") || { echo "[FAIL] 리뷰 JSON이 스키마와 다름: $review" >&2; exit 1; }
  ids=$(jq -r '[.blocking_issues[].id] | sort | join(",")' "$review")
  fingerprint=$(jq -Sc '[.blocking_issues[] | {id, problem, required_change}] | sort_by(.id)' "$review")
  echo "Sol verdict: $verdict / blocking: ${ids:-없음}"

  if [ "$verdict" = "PASS" ] && [ -z "$ids" ]; then
    echo "=== [$DOC_MODE] 문서 합의 완료 (round $round) ==="
    jq -n --arg p "$DOC_MODE" --arg r "$round" '{phase:$p, status:"PASS", rounds:($r|tonumber)}' > "$WORK_DIR/state.json"
    exit 0
  fi

  # 교착 감지: 이슈 '내용'까지 동일한 집합이 2라운드 연속이면 사람에게 에스컬레이션
  # (같은 id라도 problem/required_change가 달라지면 진전 중으로 본다)
  if [ -n "$ids" ] && [ "$fingerprint" = "$prev_fingerprint" ]; then
    echo "[STOP] 동일 이슈($ids)가 내용 변화 없이 2라운드 연속 반복됨. 사용자 판단 필요." >&2
    jq -n --arg p "$DOC_MODE" --arg i "$ids" '{phase:$p, status:"DEADLOCK", issues:$i}' > "$WORK_DIR/state.json"
    exit 2
  fi
  prev_fingerprint="$fingerprint"
  prev_review="$review"

  # 마지막 검증 라운드였다면 수정 없이 종료 (수정은 항상 재검증 대상이어야 함)
  [ "$round" -le "$MAX_SPEC_ROUNDS" ] || break

  # ---------- Fable 응답: 각 이슈 ACCEPT/REJECT + 문서 갱신 ----------
  # design/impl 두 문서 모두 fable-doc 단일 세션을 이어간다 — 설계 라운드의
  # 결정 문맥(왜 그 결정을 했는지, 뭐가 REJECT됐는지)을 구현 문서 수정에서
  # 그대로 활용하고 프롬프트 캐시를 살리기 위함
  echo "--- Fable 이 리뷰를 반영/반박합니다 ---"
  fable_result="$WORK_DIR/reviews/fable-$DOC_MODE-round-$tag.raw"
  export REVIEW_FILE="$review" ROUND="$round"
  fable_prompt="$(render_prompt "$FABLE_TEMPLATE" '${WORK_DIR} ${REVIEW_FILE} ${ROUND}')"
  session_args=$(claude_session_args fable-doc)
  "$CLAUDE_BIN" -p $session_args --model "$FABLE_MODEL" --effort "$CLAUDE_EFFORT" \
    --permission-mode acceptEdits --output-format json \
    "$fable_prompt" \
    > "$fable_result" || { echo "[FAIL] claude 실행 실패 (모델 '$FABLE_MODEL' 확인)"; exit 1; }
  claude_session_commit fable-doc
  log_claude_usage "$DOC_MODE-fable-round-$tag" "$fable_result"
done

echo "[STOP] [$DOC_MODE] $MAX_SPEC_ROUNDS 라운드 내 수렴 실패. 쟁점을 사용자에게 보고하고 중단." >&2
jq -n --arg p "$DOC_MODE" '{phase:$p, status:"MAX_ROUNDS_EXCEEDED"}' > "$WORK_DIR/state.json"
exit 2
