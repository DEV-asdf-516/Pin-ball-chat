#!/usr/bin/env bash
# =============================================================
# 명세 합의 루프: Fable(작성) ↔ Sol(검증) 수렴 강제
# 파일 경로: .claude/skills/feature/scripts/consensus-loop.sh
# 사용법: consensus-loop.sh  (저장소 루트에서 실행,
#         $WORK_DIR/specification.md 초안이 이미 있어야 함)
# 종료 코드: 0=PASS 수렴, 2=라운드 초과/교착, 1=환경 오류
# 리뷰는 MAX_SPEC_ROUNDS+1 회 — 마지막 수정도 반드시 재검증한다.
# =============================================================
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$SKILL_DIR/config.sh"

# ---------- 사전 점검 (환경이 틀리면 진행 금지) ----------
for bin in "$CLAUDE_BIN" "$CODEX_BIN" jq uuidgen; do
  command -v "$bin" >/dev/null 2>&1 || { echo "[FAIL] '$bin' 미설치. 중단." >&2; exit 1; }
done
[ -f "$WORK_DIR/specification.md" ] || { echo "[FAIL] $WORK_DIR/specification.md 없음. Fable이 초안을 먼저 작성해야 함." >&2; exit 1; }
mkdir -p "$WORK_DIR/reviews"
touch "$WORK_DIR/decisions.md"

SCHEMA_FILE="$SKILL_DIR/schemas/spec-review.schema.json"
[ -f "$SCHEMA_FILE" ] || { echo "[FAIL] 스키마 없음: $SCHEMA_FILE" >&2; exit 1; }
prev_fingerprint=""
prev_review=""

for round in $(seq 1 $((MAX_SPEC_ROUNDS + 1))); do
  tag=$(printf '%02d' "$round")
  review="$WORK_DIR/reviews/sol-round-$tag.json"
  echo "=== Round $round/$((MAX_SPEC_ROUNDS + 1)) : Sol 검토 ==="

  prev_context=""
  if [ -n "$prev_review" ]; then
    prev_context="직전 라운드 리뷰는 $prev_review 에 있다. 같은 문제를 다시 지적할 때는 반드시 같은 id를 재사용하고, 새 문제에만 새 id를 붙여라. $WORK_DIR/decisions.md 에서 REJECT 된 이슈는 새로운 논거가 없으면 재제기하지 마라."
  fi

  # ---------- Sol (Codex) 검토: 읽기 전용, 스키마 강제 JSON ----------
  "$CODEX_BIN" exec -m "$SOL_MODEL" -c "model_reasoning_effort=\"$SOL_EFFORT\"" --sandbox read-only \
    --output-schema "$SCHEMA_FILE" -o "$review" \
    "당신은 명세 검증자다. $WORK_DIR/specification.md 와 $WORK_DIR/request.md, $WORK_DIR/decisions.md 를 읽고 신랄하게 검토하라. $prev_context 구현을 막아야 할 결함만 blocking_issues 에 넣고, 취향 문제는 non_blocking_notes 에 넣어라." \
    > "$review.log" 2>&1 || { echo "[FAIL] codex 실행 실패 (모델 '$SOL_MODEL' 확인)"; tail -20 "$review.log" >&2; exit 1; }

  verdict=$(jq -er '.verdict' "$review") || { echo "[FAIL] 리뷰 JSON이 스키마와 다름: $review" >&2; exit 1; }
  ids=$(jq -r '[.blocking_issues[].id] | sort | join(",")' "$review")
  fingerprint=$(jq -Sc '[.blocking_issues[] | {id, problem, required_change}] | sort_by(.id)' "$review")
  echo "Sol verdict: $verdict / blocking: ${ids:-없음}"

  if [ "$verdict" = "PASS" ] && [ -z "$ids" ]; then
    echo "=== 명세 합의 완료 (round $round) ==="
    jq -n --arg r "$round" '{phase:"spec", status:"PASS", rounds:($r|tonumber)}' > "$WORK_DIR/state.json"
    exit 0
  fi

  # 교착 감지: 이슈 '내용'까지 동일한 집합이 2라운드 연속이면 사람에게 에스컬레이션
  # (같은 id라도 problem/required_change가 달라지면 진전 중으로 본다)
  if [ -n "$ids" ] && [ "$fingerprint" = "$prev_fingerprint" ]; then
    echo "[STOP] 동일 이슈($ids)가 내용 변화 없이 2라운드 연속 반복됨. 사용자 판단 필요." >&2
    jq -n --arg i "$ids" '{phase:"spec", status:"DEADLOCK", issues:$i}' > "$WORK_DIR/state.json"
    exit 2
  fi
  prev_fingerprint="$fingerprint"
  prev_review="$review"

  # 마지막 검증 라운드였다면 수정 없이 종료 (수정은 항상 재검증 대상이어야 함)
  [ "$round" -le "$MAX_SPEC_ROUNDS" ] || break

  # ---------- Fable 응답: 각 이슈 ACCEPT/REJECT + 명세 갱신 ----------
  # 라운드 간 같은 세션을 이어가 저장소 재탐색 없이 프롬프트 캐시를 활용
  echo "--- Fable 이 리뷰를 반영/반박합니다 ---"
  fable_result="$WORK_DIR/reviews/fable-round-$tag.raw"
  session_args=$(claude_session_args fable-spec)
  "$CLAUDE_BIN" -p $session_args --model "$FABLE_MODEL" --effort "$CLAUDE_EFFORT" \
    --permission-mode acceptEdits --output-format json \
    "당신은 명세 작성자다. $review 의 blocking_issues 각각에 대해 ACCEPT 또는 REJECT 를 이유와 함께 $WORK_DIR/decisions.md 에 '- [round $round] <이슈ID> <ACCEPT|REJECT>: <이유>' 형식으로 추가하라. ACCEPT 한 이슈는 $WORK_DIR/specification.md 를 실제로 수정해 반영하라. REJECT 는 명세를 바꾸지 말고 이유만 남겨라. 명세의 기존 결정 사항을 임의로 삭제하지 마라." \
    > "$fable_result" || { echo "[FAIL] claude 실행 실패 (모델 '$FABLE_MODEL' 확인)"; exit 1; }
  claude_session_commit fable-spec
  log_claude_usage "spec-fable-round-$tag" "$fable_result"
done

echo "[STOP] $MAX_SPEC_ROUNDS 라운드 내 수렴 실패. 쟁점을 사용자에게 보고하고 중단." >&2
jq -n '{phase:"spec", status:"MAX_ROUNDS_EXCEEDED"}' > "$WORK_DIR/state.json"
exit 2
