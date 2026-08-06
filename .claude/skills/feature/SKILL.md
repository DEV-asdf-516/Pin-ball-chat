---
name: feature
description: 복잡한 피처를 다중 에이전트 합의 파이프라인으로 처리한다. Fable이 설계 문서와 구현 문서를 작성하고 Sol(Codex)이 각각 검증해 수렴할 때까지 반복한 뒤, Luna가 구현을 완수하면 Sonnet이 리뷰하며 필요한 수정·리팩터링을 직접 수행하고, Fable이 최종 전체 테스트로 마감한다. 사용자가 "feature" 또는 "피처"를 명시하며 기능 구현을 요청할 때 사용한다. 사소한 수정·단일 파일 변경에는 사용하지 않는다.
---

# feature

피처 하나를 "설계 합의 → 구현 문서 합의 → 구현 → 리뷰 수렴 → 최종 테스트"로 끝까지 처리하는 파이프라인. 제어권은 항상 이 세션(Fable, 오케스트레이터)에만 있고, 나머지는 전부 비대화형 하위 실행이다. 역할 분리: 판정 스키마 `schemas/`, 페르소나 프롬프트 `prompts/`(envsubst 렌더링), 흐름 제어 `scripts/`.

| 문서 | 내용 | 검증 |
|---|---|---|
| `design.md` | 목표, API/데이터 계약, 에러·동시성 처리, 테스트 기준, 비범위 | Phase 1: `consensus-loop.sh design` |
| `implementation.md` | 파일 목록·수정 순서, 클래스/함수 수준 계획, 테스트 목록, 완료 기준 | Phase 1.5: `consensus-loop.sh impl` |

## 사전 조건

1. `config.sh` 모델 ID가 실제 환경과 일치. reasoning effort 고정: Claude(Fable/Sonnet) `medium`, Sol `high`, Luna `max` — 다르면 config.sh 가드가 거부. Phase 0·4를 직접 수행하는 Fable 세션도 `medium`, 스크립트의 Claude 하위 실행도 전부 `--effort medium` 명시.
2. `claude`, `codex`, `jq`, `python3`, `envsubst` 설치·로그인. 저장소 루트에서 실행 (`.agent-work/` 는 `.gitignore` 등록됨).
3. `config.sh` 는 bash 전용(`BASH_SOURCE` 경로 해석 + effort 가드) — 오케스트레이터 셸이 zsh 등이면 **반드시 `bash -c` 로 감싸** 실행한다. zsh에서 직접 `source` 하면 `CORE_RULES_FILE` 경로가 깨져 즉시 실패한다.

## 관전 (사용자 라이브 뷰 — 자동)

사용자가 아무것도 치지 않아도 전 단계를 실시간 관전할 수 있어야 한다.

- 모든 하위 실행 출력은 `$WORK_DIR/live.log` 한 파일로 모은다: 단계 시작마다 `=== [Phase N] <설명> ===` 구분선을 append 하고, 백그라운드 하위 실행은 출력 파일을 `tail -f <출력파일> >> $WORK_DIR/live.log &` 로 미러링, 직접 실행은 `2>&1 | tee -a $WORK_DIR/live.log`.
- **Phase 0 시작 시 뷰어 터미널을 자동으로 띄운다** (macOS):

```bash
touch "$WORK_DIR/live.log"
osascript -e 'tell app "Terminal" to do script "tail -f '"$PWD"'/.agent-work/live.log"' -e 'tell app "Terminal" to activate'
```

  이미 뷰어 창이 떠 있으면(같은 피처 재진입) 다시 띄우지 않는다.
- 정제된 판정은 `reviews/*.json`, 결정 기록은 `decisions.md` 로도 관전 가능.
- SKILL.md·스킬 스크립트 등 파이프라인 메타 파일을 세션 중 수정한 경우, Phase 3 리뷰 대상 diff와 섞이지 않게 피처 커밋에서 분리한다 (Sonnet 은 implementation.md 파일 목록 밖 변경을 out-of-scope 로 지적한다).

## Phase 0 — 초기화 + 요구 확정 (Fable 직접)

0. 새 피처면 `.agent-work/` 의 이전 산출물 전부(`request.md`, `design.md`, `implementation.md`, `decisions.md`, `.session-*`, `reviews/`, `state.json`, `usage.jsonl` 등 — `archive/` 만 제외)를 **삭제 말고** `.agent-work/archive/<이전-피처명-또는-날짜>/` 로 `mv` (rm 금지 — 삭제는 사용자에게 요청). `.session-*` 잔존 = 이전 피처 문맥 오염, 문서 잔존 = 덮어쓰기 유실. 같은 피처의 계속(Phase 4 재진입 등)이면 그대로 둔다 — 세션 이어가기가 캐시 절감의 핵심.
1. 관전 뷰어를 띄운다 (위 "관전" 절).
2. 요구를 `request.md` 에 기록 (원문 + 해석한 범위 + 명시적 제외).
3. **모호하면 추측 금지, 사용자에게 질문해 해소.** 설계에 영향 주는 모호성을 남긴 채 진행하지 않는다.
4. `design.md` 초안 작성 (표의 내용 요건). `implementation.md` 는 설계 합의 후에만 쓴다.
5. 빈 `decisions.md` 생성.

## Phase 1 — 설계 합의

```bash
bash <skill_dir>/scripts/consensus-loop.sh design
```

Sol(read-only)이 `reviews/sol-design-round-NN.json` 에 BLOCK/PASS 판정, Fable(`fable-doc` 세션)이 이슈별 ACCEPT/REJECT 하며 `design.md` 갱신 — PASS + blocking 0건까지 반복. 종료 후 `decisions.md` 에 `[USER-QUESTION]` 이 있으면 사용자에게 질문 → 반영 → 루프 재실행. 종료 코드 2(교착/라운드 초과)면 **진행 금지**, 쟁점 정리해 사용자 보고 후 정지.

## Phase 1.5 — 구현 문서 합의

합의된 설계로 Fable(오케스트레이터)이 `implementation.md` 작성. **작성 원칙 — 독자는 Luna(codex, 저장소 사전 문맥 없음)와 Sonnet. 항상 이 둘이 제일 잘 이해할 수 있는 구조로**: 추가 탐색 없이 실행 가능하게 파일 경로·함수명·호출부 전부 명시, 코드 스니펫은 복붙 가능 수준, 따를 컨벤션은 대상 파일명으로 지목. '적절히'/'기존 방식대로' 같은 모호어 금지. 그 후:

```bash
bash <skill_dir>/scripts/consensus-loop.sh impl
```

Sol이 구현 문서가 설계를 정확·완전하게 실행하는지 검증(`design.md` 존재가 선행 조건). **설계 합의 결정의 재론 금지.** Fable(같은 `fable-doc` 세션)이 반영하되, 이슈 해결이 설계 변경을 요구하면 문서를 고치지 않고 REJECT + '설계 재합의 필요' 명시 → 사용자 보고 후 Phase 1 재합의 (설계가 조용히 뒤집히는 것 방지). 라운드 한도 `MAX_SPEC_ROUNDS` 는 문서별 각각 적용(최악 2배). 종료 코드 2면 구현 진행 금지, 사용자 보고 후 정지.

## Phase 2 — 구현 (Luna, 메인 작성자)

가능하면 전용 브랜치에서:

```bash
git checkout -b feature/<이름>
bash -c 'source .claude/skills/feature/config.sh \
  && export CORE_RULES="$(cat "$CORE_RULES_FILE")" WORK_DIR TEST_CMD \
  && codex exec -m "$LUNA_MODEL" -c "model_reasoning_effort=\"$LUNA_EFFORT\"" --sandbox workspace-write \
       "$(render_prompt luna-implement.md "\${CORE_RULES} \${WORK_DIR} \${TEST_CMD}")"'
```

Luna가 1차 구현을 완수할 때까지 다른 에이전트는 코드를 만지지 않는다. Sonnet 은 Phase 3에만 진입.

## Phase 3 — 구현 리뷰 수렴

```bash
bash <skill_dir>/scripts/impl-review-loop.sh
```

각 라운드: Sonnet 이 읽기 전용 실행으로 diff 리뷰 → JSON 판정, 이슈가 있으면 별도 실행에서 직접 수정·리팩터링. **리뷰 기준은 `implementation.md` 가 1차, `design.md` 는 참고.** 수정분은 다음 라운드에서 재검증, APPROVE + 이슈 0건까지 반복(수정 최대 `MAX_IMPL_ROUNDS`회, 리뷰 +1회). 종료 코드 2면 남은 이슈 보고 후 정지.

## Phase 4 — 최종 테스트 (Fable 직접)

1. `TEST_CMD` 와 `LINT_CMD` 전체 실행 (출력은 live.log 에도 tee).
2. 실패 시: 실패 로그를 붙여 Luna에게 재수정(Phase 2와 같은 호출 + 로그 첨부). Luna 수정 후엔 기존 승인이 무효이므로 **Phase 3 재실행으로 재승인 후** 1번부터 재수행. 재진입 최대 `MAX_TEST_RETRIES` 회, 그래도 실패면 내역 정리해 사용자 보고 후 정지. (리뷰 지적 손질 = Sonnet 책임, 전체 테스트를 깨는 기능 결함 = Luna 책임 — 작성자/승인자 독립성 유지.)
3. 통과 시: 변경 요약 + 라운드 수 + decisions.md 주요 결정을 한 번에 보고. 커밋은 사용자 요청 시에만 **Sonnet(`sonnet-fix` 세션 이어서)에 위임** — 변경 문맥을 보유한 채 커밋 메시지 작성과 `git commit` 수행. push 는 별도 요청 없이는 금지.

## 강제 규칙 (어길 수 없음)

- 하위 실행마다 `--model`/`-m` 명시. CLI 실패 시 다음 단계 진행 금지.
- effort 는 Claude `medium` / Sol `high` / Luna `max` 만 허용 (가드 + 호출마다 명시). 규칙 주입: Sonnet 은 `--append-system-prompt`, Luna 는 프롬프트 선두 `[반드시 지킬 규칙]` 블록으로 `core_rules.md` 매 실행 주입 + 프로젝트 codex 훅(`.codex/config.toml` PreToolUse → `luna_guard.sh`)이 워커의 git commit/push 를 매 툴 호출마다 차단.
- **설계 모호성은 추측으로 메우지 않는다** — Phase 0 직접 질문, 루프 중엔 `[USER-QUESTION]` 기록 후 에스컬레이션.
- 구현 문서 합의에서 설계 결정 재론 금지. 설계 변경 필요 시 REJECT + '설계 재합의 필요' → Phase 1 복귀.
- 파이프라인 중 누구도 커밋·푸시 금지. 커밋은 사용자 요청 시 Sonnet 위임만. Luna 는 어떤 경우에도 커밋 불가(`luna_guard.sh` 차단).
- Sonnet 의 마지막 APPROVE 이후 코드가 조금이라도 바뀌면(누가 바꿨든) Phase 3 재리뷰 없이 종료 금지.
- "대충 통과 간주" 금지. PASS/APPROVE 는 스키마 검증된 JSON 파일 + 이슈 0건 동시일 때만 인정 (모순 응답은 스크립트가 거부).
- 라운드 초과·교착은 실패가 아니라 **사용자 에스컬레이션** — 쟁점 요약만 올리고 정지.

## 토큰 절약 구조 (스크립트에 내장)

- Claude 하위 실행은 역할별 세션 재사용: `fable-doc`(설계·구현 문서 소유 — 한 세션이 두 문서를 맡아 설계 결정 문맥을 재활용), `sonnet-review`, `sonnet-fix`. 첫 호출 `--session-id`, 이후 `--resume` (`$WORK_DIR/.session-<역할>`) — 라운드 간 재탐색 제거 + 프롬프트 캐시 적중.
- `sonnet-review` 와 `sonnet-fix` 는 절대 한 세션으로 합치지 않는다 — 리뷰가 자기 수정 문맥에 오염되면 승인 독립성이 깨진다 (문서 쪽은 Fable 소유 + Sol 견제 구조라 단일 세션 허용).
- Claude 사용량은 `$WORK_DIR/usage.jsonl` 에 라운드별 누적, codex(Sol/Luna)는 출력의 "tokens used" 라인 참고.
