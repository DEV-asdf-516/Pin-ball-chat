---
name: feature
description: 복잡한 피처를 다중 에이전트 합의 파이프라인으로 처리한다. Fable이 설계 문서와 구현 문서를 작성하고 Sol(Codex)이 각각 검증해 수렴할 때까지 반복한 뒤, Luna가 구현을 완수하면 Sonnet이 리뷰하며 필요한 수정·리팩터링을 직접 수행하고, Fable이 최종 전체 테스트로 마감한다. 사용자가 "feature" 또는 "피처"를 명시하며 기능 구현을 요청할 때 사용한다. 사소한 수정·단일 파일 변경에는 사용하지 않는다.
---

# feature

복잡한 피처 하나를 "설계 합의 → 구현 문서 합의 → 구현 → 리뷰 수렴 → 최종 테스트"로 끝까지 처리하는 파이프라인. 제어권은 항상 이 세션(Fable, 오케스트레이터) 하나에만 있다. 다른 에이전트는 전부 비대화형 하위 실행이다.

문서는 2단 구조다:

| 문서 | 내용 | 검증 |
|---|---|---|
| `design.md` | 목표, API/데이터 계약, 에러·동시성 처리, 테스트 기준, 비범위(non-goals) | Phase 1: `consensus-loop.sh design` |
| `implementation.md` | 파일 목록·수정 순서, 클래스/함수 수준 계획, 테스트 목록, 완료 기준 | Phase 1.5: `consensus-loop.sh impl` |

역할 분리: 판정 스키마 = `schemas/`, 페르소나 프롬프트 = `prompts/`(envsubst 렌더링), 흐름 제어 = `scripts/`.

## 사전 조건

1. `config.sh` 의 모델 ID가 실제 환경과 일치해야 한다. reasoning effort 는 Claude(Fable/Sonnet) `medium`, Sol `high`, Luna `max`로 고정되며, 다른 값이면 config.sh 가드가 실행을 거부한다.
2. `claude`, `codex`, `jq`, `python3`, `envsubst` 가 설치·로그인되어 있어야 한다.
3. 저장소 루트에서 실행한다. `.agent-work/` 는 `.gitignore` 에 등록되어 있다.
4. Phase 0·4를 직접 수행하는 오케스트레이터 Fable 세션도 `medium` effort로 시작되어 있어야 한다. 스크립트가 생성하는 모든 Claude 하위 실행은 `--effort medium`을 명시한다.

## Phase 0 — 초기화 + 요구 확정 (Fable 직접 수행)

0. 새 피처 시작이면 `.agent-work/` 안의 이전 산출물 **전부**(`request.md`, `design.md`, `implementation.md`, `decisions.md`, `.session-*`, `reviews/`, `state.json`, `usage.jsonl` 등 — `archive/` 자신만 제외)를 **삭제하지 말고** `.agent-work/archive/<이전-피처명-또는-날짜>/` 로 `mv` 해서 치운다 (rm 금지 — 삭제는 사용자에게 요청). `.session-*` 가 작업 디렉터리에 남으면 이전 피처의 대화 문맥이 섞이고, 문서·결정 기록이 남으면 덮어써져 유실된다. 단 Phase 4 재진입 등 같은 피처의 계속이면 그대로 둔다 — 세션 이어가기가 캐시 절감의 핵심이다.
1. 사용자의 요구를 `.agent-work/request.md` 에 기록한다 (원문 + 해석한 범위 + 명시적 제외 사항).
2. **요구에 모호한 부분이 있으면 추측으로 메우지 말고 사용자에게 질문해 해소한다.** 설계에 영향을 주는 모호성이 남은 채로 다음 단계로 넘어가지 않는다.
3. `.agent-work/design.md` 초안을 작성한다. 포함: 목표, API/데이터 계약, 에러·동시성 처리, 테스트 기준(어떤 테스트가 통과해야 완료인지), 비범위(non-goals). `implementation.md` 는 아직 쓰지 않는다 — 설계 합의(Phase 1) 이후에 작성한다.
4. 빈 `.agent-work/decisions.md` 를 만든다.

## Phase 1 — 설계 합의 (스크립트가 수렴 강제)

```bash
bash <skill_dir>/scripts/consensus-loop.sh design
```

- Sol(Codex, read-only)이 설계를 검토해 `reviews/sol-design-round-NN.json` 에 BLOCK/PASS 판정을 남기고, Fable(비대화형 하위 실행, `fable-doc` 세션)이 각 이슈를 ACCEPT/REJECT 하며 `design.md` 를 갱신한다. PASS + blocking 0건이 될 때까지 반복.
- 루프 종료 후 `decisions.md` 에 `[USER-QUESTION]` 항목이 있으면 사용자에게 질문하고, 답을 설계에 반영한 뒤 루프를 재실행한다.
- 종료 코드 2(교착 또는 라운드 초과)면 **다음 단계로 넘어가지 말고** 남은 쟁점만 정리해 사용자에게 보고하고 멈춘다.

## Phase 1.5 — 구현 문서 합의

합의된 설계를 바탕으로 Fable(오케스트레이터)이 `.agent-work/implementation.md` 를 작성한다. 포함: 파일 목록·수정 순서, 클래스/함수 수준 계획, 테스트 목록, 완료 기준.

**작성 원칙 — 독자는 Luna(codex, 저장소 사전 문맥 없음)와 Sonnet이다. 항상 이 둘이 제일 잘 이해할 수 있는 구조로 쓴다**: 추가 탐색 없이 그대로 실행 가능하게 파일 경로·함수명·호출부를 전부 명시하고, 코드 스니펫은 복붙 가능한 수준으로, 따라야 할 기존 컨벤션은 대상 파일명으로 지목한다. '적절히', '기존 방식대로' 같은 모호한 지시어 금지. 그 후:

```bash
bash <skill_dir>/scripts/consensus-loop.sh impl
```

- Sol이 구현 문서가 설계를 정확하고 완전하게 실행하는지 검증한다 (`design.md` 존재가 선행 조건으로 강제됨). **설계에서 합의된 결정의 재론은 금지된다.**
- Fable(같은 `fable-doc` 세션)이 이슈를 반영한다. 이슈 해결이 설계 변경을 요구하면 문서를 고치지 않고 REJECT + '설계 재합의 필요' 를 명시한다 — 이 경우 사용자에게 보고하고 Phase 1 부터 다시 합의한다. 설계가 뒤에서 조용히 뒤집히는 것을 막기 위함이다.
- 라운드 한도(`MAX_SPEC_ROUNDS`)는 문서별로 각각 적용되므로 최악 라운드 수는 단일 문서 대비 2배다.
- 종료 코드 2면 구현으로 넘어가지 말고 사용자에게 보고하고 멈춘다.

## Phase 2 — 구현 (Luna, 메인 작성자)

합의된 구현 문서로 Luna에게 구현을 위임한다. 가능하면 전용 브랜치에서:

```bash
source .claude/skills/feature/config.sh   # LUNA_EFFORT=max 가드 포함
git checkout -b feature/<이름>
export CORE_RULES="$(cat "$CORE_RULES_FILE")" WORK_DIR TEST_CMD
codex exec -m "$LUNA_MODEL" -c "model_reasoning_effort=\"$LUNA_EFFORT\"" --sandbox workspace-write \
  "$(render_prompt luna-implement.md '${CORE_RULES} ${WORK_DIR} ${TEST_CMD}')"
```

Luna 가 1차 구현을 완수할 때까지 다른 에이전트는 코드를 만지지 않는다. Sonnet 은 Luna 완료 이후(Phase 3)에만 진입한다.

## Phase 3 — 구현 리뷰 수렴

```bash
bash <skill_dir>/scripts/impl-review-loop.sh
```

- 각 라운드: Sonnet 이 읽기 전용 실행으로 diff 를 리뷰해 JSON 판정을 남기고, 이슈가 있으면 별도 실행에서 직접 수정·리팩터링한다. **리뷰 기준은 `implementation.md`(구현 문서)가 1차이고 `design.md` 는 참고다.** 수정분은 다음 라운드 리뷰로 재검증되며, APPROVE + 이슈 0건까지 반복(수정 최대 `MAX_IMPL_ROUNDS`회, 리뷰는 +1회).
- 종료 코드 2면 남은 이슈를 사용자에게 보고하고 멈춘다.

## Phase 4 — 최종 테스트 (Fable 직접 수행)

1. `TEST_CMD` 와 `LINT_CMD` 를 전체 실행한다.
2. 실패 시: 실패 로그를 붙여 Luna에게 재수정을 맡긴다(Phase 2와 같은 호출, 프롬프트 뒤에 실패 로그 첨부). Luna 수정 후에는 기존 Sonnet 승인이 최신 코드에 대한 승인이 아니므로 **반드시 Phase 3 을 재실행해 재승인을 받은 뒤** 1번부터 다시 수행한다. 이 재진입은 최대 `MAX_TEST_RETRIES` 회. 그래도 실패하면 실패 내역을 정리해 사용자에게 보고하고 멈춘다. (리뷰 지적 손질은 리뷰어인 Sonnet 책임, 전체 테스트가 깨지는 기능 결함은 메인 작성자인 Luna 책임 — 작성자/승인자 독립성을 유지한다.)
3. 통과 시: 변경 요약, 라운드 수, decisions.md 의 주요 결정을 한 번에 보고한다. 커밋은 사용자가 요청했을 때만, **Sonnet 에게 위임해** 수행한다 — `sonnet-fix` 세션을 이어서(변경 문맥 보유) 커밋 메시지 작성과 `git commit` 을 시킨다. push 는 별도 요청 없이는 하지 않는다.

## 강제 규칙 (어길 수 없음)

- 각 하위 실행은 반드시 `--model` / `-m` 으로 모델을 명시한다. CLI가 실패하면 다음 단계로 넘어가지 않는다.
- reasoning effort 는 Claude(Fable/Sonnet) `medium`, Sol `high`, Luna `max`만 허용한다 (config.sh 가드 + 모든 하위 호출에 명시). Phase 0·4의 Fable 직접 실행도 `medium` 세션이어야 한다. 규칙 주입: Sonnet 은 `--append-system-prompt`, Luna(codex)는 프롬프트 선두의 `[반드시 지킬 규칙]` 블록으로 `core_rules.md` 를 매 실행 주입하고, 프로젝트 codex 훅(`.codex/config.toml` 의 PreToolUse → `luna_guard.sh`)이 매 툴 호출마다 워커의 git commit/push 를 차단한다.
- **설계 단계의 모호성은 추측으로 메우지 않는다.** 사용자 질문으로 해소한다 (Phase 0 직접 질문, 합의 루프 중에는 `[USER-QUESTION]` 기록 후 에스컬레이션).
- 구현 문서 합의에서 설계 합의 결정을 재론하지 않는다. 설계 변경이 필요하면 REJECT + '설계 재합의 필요' 로 표면화하고 Phase 1 로 되돌아간다.
- 파이프라인 진행 중에는 누구도 커밋·푸시하지 않는다. 커밋은 사용자가 요청했을 때만 하며, Fable 이 Sonnet(`sonnet-fix` 세션)에 위임해 수행한다. Luna 는 어떤 경우에도 커밋하지 않는다 — codex 가드(`luna_guard.sh`)가 차단한다.
- Sonnet 의 마지막 APPROVE 이후 코드가 조금이라도 바뀌면(누가 바꿨든) Phase 3 재리뷰 없이 파이프라인을 끝내지 않는다.
- 어떤 단계도 "대충 통과한 것으로 간주"하지 않는다. PASS/APPROVE 판정은 반드시 스키마 검증된 JSON 파일에 남아야 하며, 이슈 0건과 동시일 때만 통과로 인정한다 (모순 응답은 스크립트가 거부).
- 라운드 한도 초과·교착은 실패가 아니라 **사용자 에스컬레이션**이다. 쟁점 요약만 올리고 멈춘다.

## 토큰 절약 구조 (스크립트에 내장)

- Claude 하위 실행은 역할별 세션을 이어간다: `fable-doc`(설계·구현 문서 소유자 — 두 문서를 한 세션이 담당해 설계 라운드의 결정 문맥을 구현 문서 수정에서 재활용), `sonnet-review`(리뷰), `sonnet-fix`(수정). 첫 호출이 `--session-id` 로 UUID를 만들고 이후 `--resume` 한다 (`$WORK_DIR/.session-<역할>`). 라운드 간 저장소 재탐색이 사라지고 동일 프리픽스는 프롬프트 캐시로 처리된다.
- `sonnet-review` 와 `sonnet-fix` 는 절대 같은 세션으로 합치지 않는다 — 리뷰가 자기 수정 문맥에 오염되면 승인 독립성이 깨진다. (설계/구현 문서는 둘 다 Fable 소유 + Sol 견제 구조라 이 독립성 요구가 없어 단일 세션이다.)
- Claude 하위 실행의 사용량은 `$WORK_DIR/usage.jsonl` 에 라운드별로 누적된다 (비용·캐시 적중 확인용). codex(Sol/Luna) 사용량은 codex 출력의 "tokens used" 라인 참고.
