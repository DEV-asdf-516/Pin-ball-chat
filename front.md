# Frontend (apps/web)

바닐라 JS 모바일형 셸(최대 430px). 라우터 없음 — `showScreen(name)` 교체.
`docker compose up` → 웹 3000 / API 8080. root는 `apps/web/src`.

## 최우선: XSS
- `innerHTML`/`insertAdjacentHTML`/`outerHTML`/HTML 문자열 조립 금지.
- DOM은 `el()` + `textContent`, 자식 교체는 `setChildren()`. markdown preview도 DOM 기반만.
- 검증: `rg "innerHTML|insertAdjacentHTML|outerHTML|escapeHtml" apps/web/src/js` → 결과 없어야 함.

## 공통 경로 (우회 금지)
- API: `api.js`의 `api()`/`streamSse()`만. pagination: `loadCursorPage()`. 상태: `state.js` 최소 추가.
- 드롭다운: native `<select>` 금지 → hidden input + 공통 `.dropdown`(fixed).
- 색상은 `theme.css` 토큰만. decorative gradient 금지.

## 도메인 규칙
- 플롯 제작: character/user 선택 UI 없음. ID 프론트 생성 → 플롯+캐릭터 배열 복합 요청 `POST /api/plots` 1번.
- 프사: 파일 입력 → `POST /api/uploads/character/{id}` multipart. URL 입력 노출 금지, FormData `Content-Type` 수동 설정 금지.
- 장르 8개 고정, 최대 2개 선택.
- 대화 생성: `{ plotId, title }`만 → 즉시 진입. profile 없이 전송 시 sheet 재표시.
- `@이름:` → speaker bubble, `@관찰자:` → 내레이션(prefix 제거, label에 `@` 없음).
- regenerate/스트리밍: 기존 node 자리에서 갱신, node 교체 금지. 스트리밍 중 입력 disabled.
- 빈 입력 전송: 마지막이 user면 재전송, assistant면 추천 답변 요청.

## 설정
- localStorage는 `pinballchat.{theme,apiBase,recentPlots,route}`만. 모델/생성 설정 저장 금지.
- 모델 설정은 대화별 API(`/api/conversations/{id}/settings`)만. 저장값이 provider 기본값보다 우선.
- 모델 목록은 `GET /api/models?provider=...`. 직접 입력 필드 없음.

## 검증
for f in apps/web/src/js/*.js apps/web/src/js/components/*.js apps/web/src/js/pages/*.js; do node --check "$f" || exit 1; done
rg "innerHTML|insertAdjacentHTML|outerHTML|escapeHtml" apps/web/src/js