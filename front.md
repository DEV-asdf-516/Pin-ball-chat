# Frontend (apps/web)

## 개요
- 모바일 앱형 로컬 채팅 클라이언트, 바닐라 JS. 라우터 없음 — `showScreen(name)`으로 화면 교체.
- 실행: `docker compose up` → 웹 3000, API 8080. 정적 root는 `apps/web/src`.
- 화면 6개: plots / plotCreate / plotManage / conversations / detail / chat.
- 공통 헤더는 목록·제작·관리·상세 전용, 채팅방은 자체 헤더 사용 (유저 프로필·모델 설정 버튼은 채팅 헤더에만).

## 렌더링 / XSS (최우선)
- `innerHTML`/`insertAdjacentHTML`/`outerHTML`/HTML 문자열 조립 금지.
- DOM은 `dom.js`의 `el()` + `textContent`, 자식 교체는 `setChildren()`.
- 검증: `rg "innerHTML|insertAdjacentHTML|outerHTML|escapeHtml" apps/web/src/js` → 결과 없어야 함.

## 새 기능 규칙
- 기존 `pages/`/`components/`/도메인 JS 파일에 배치.
- 전역 상태는 `state.js` 최소 추가, API 호출은 `api.js`의 `api()`/`streamSse()`만.
- cursor pagination은 `paging.js`의 `loadCursorPage()` 재사용, 화면 전환은 `showScreen()` 유지.

## 플롯
- 제작: 사용자는 기존 character/user를 선택하지 않음. 프론트가 ID 자동 생성 →
  `POST /api/characters` 후 그 `characterId`로 `POST /api/plots`.
- 프사는 파일 입력 → 캐릭터 생성/수정 후 `POST /api/uploads/character/{id}` multipart 업로드.
  URL 직접 입력 노출 금지, FormData `Content-Type` 수동 설정 금지.
- 장르는 8개 고정 버튼(로맨스/힐링/드라마/얀데레/판타지/액션/미스터리/호러), 최대 2개.
- 관리는 리스트 → 편집 폼, `PUT`/`DELETE /api/plots/{id}`.

## 대화 / 채팅
- 생성: `POST /api/conversations`에 `{ plotId, title }`만 → 바로 진입.
  `userProfileId` 없으면 profile sheet, 없이 전송 시도 시 재표시.
- 메시지: user 우측 / assistant 좌측. 줄 시작 `@이름:`은 speaker bubble 분리,
  단 `@관찰자:`는 내레이션 텍스트로 렌더 (prefix 제거, label에 `@` 미표기).
- markdown preview는 DOM 기반만. HTML 문자열 렌더 금지.
- regenerate는 기존 bubble 자리에서 스트리밍, 완료 후 `‹`/`›`로 후보 전환.
  스트리밍 중 같은 node 갱신, `done`에서 node 교체 금지.
- 스트리밍 중 입력칸 disabled. 빈 입력 전송 시 마지막이 user면 재전송, assistant면 추천 답변 요청.
- composer: 드래그 확장(최대 55vh), 더블클릭 복귀. 상태는 `state.composerHeight`.

## CSS
- shell 최대 430px 고정, 스크롤은 screen 내부만.
- 색상은 `theme.css` 토큰만, decorative gradient 금지. toast는 화면 중앙.
- select류는 native `<select>` 대신 hidden input + 공통 `.dropdown`(`position: fixed`).

## 설정
- localStorage는 `pinballchat.{theme,apiBase,recentPlots}`만. 모델/생성 설정은 저장 금지
  (구 `generationSettings`는 `loadSettings()`에서 제거).
- 모델 설정은 대화별: `GET`/`PUT /api/conversations/{id}/settings`만 사용.
- 모델 목록은 `GET /api/models?provider=...`, 직접 입력 필드 없음.
- 라벨: `AI 제공자`/`모델`/`답변 길이`(기본 1500)/`맥락 길이`(기본 8192)/`프롬프트 압축`.

## 검증
```bash
for f in apps/web/src/js/*.js apps/web/src/js/components/*.js apps/web/src/js/pages/*.js; do node --check "$f" || exit 1; done
rg "innerHTML|insertAdjacentHTML|outerHTML|escapeHtml" apps/web/src/js
```
