# TODO

## UI
- [x] 대화 목록 카드 제목과 채팅방 헤더 제목을 길게 누르면 메뉴 없이 바로 긴 둥근 인라인 편집칸 표시 (바깥 클릭 저장, Enter 저장, Esc 또는 뒤로가기 취소)
- [x] 대화 목록도 `nextCursor`/`hasMore`를 사용해 추가 페이지 로드
- [x] 플롯 제작 화면 추가 (`+` 원 버튼 → 제작 화면 전환 → 저장 후 상세 이동)
- [x] 플롯 관리 화면 추가 (플롯 수정·삭제)
- [x] 플롯 관리 편집 화면에서는 검색/더보기 toolbar 숨김
- [x] 플롯 관리 본문 입력칸은 남는 높이를 채우고, 내용 초과 시 textarea 내부 스크롤
- [x] 플롯 수정 화면을 플롯 제작 화면과 동일한 UI/흐름으로 정리 (제목/장르/본문/캐릭터 섹션/하단 저장 영역)
- [x] 새로고침해도 현재 화면/선택 상태 유지 (예: 플롯 상세, 플롯 관리 편집, 대화방)
- [ ] 프로필 이미지 업로드 (캐릭터 프사)
  - BUG: 캐릭터 프사 파일 선택 후 저장해도 나갔다 들어오면 이미지가 사라지는 케이스 재현.
    확인 필요: `POST /api/uploads/character/{id}` 요청이 실제로 나가는지, 실패 토스트가 가려지는지, `data/uploads/characters/*` 파일과 캐릭터 `avatarUrl`이 저장되는지.
    프론트 현재 의도: base64는 미리보기 전용, 캐릭터 생성/수정 후 multipart 업로드, 수정 저장 시 기존 서버 `avatarUrl`은 보존해서 `PUT` body에 포함.
- [x] 마지막 assistant의 턴에서만 메시지 재생성 가능한 refresh icon 표시 (현재는 assistant 턴마다 표시됨)
- [x] 메시지 후보 < > 화살표 버튼의 크기 refresh icon과 동일하게 맞출 것(얘만 좀더 큼)

## API 있음 / UI 없음
- [x] 유저 프로필 생성/수정/삭제 UI (`POST/PUT/DELETE /api/user-profiles`)
- [x] 플롯 관리 화면에서 해당 플롯의 캐릭터 정보도 함께 수정 (`PUT /api/characters/{id}`; 캐릭터명/설명/프사, 제작 화면의 캐릭터 섹션과 동일한 UI)
- [x] 메시지 삭제 UI (`DELETE /api/messages/{messageId}`)
- [x] 메시지 일괄 삭제 UI (`POST /api/messages/batch-delete`)
- [x] 턴 후보 목록 조회 UI (`GET /api/turns/{turnId}/generations`; 새로고침 후 후보 전환 복원 등)
- [ ] 콘텐츠 동적 관리 UI (캐릭터/선호 CRUD API는 이미 있음 — `POST/PUT/DELETE /api/characters`, `/api/preference-profiles`; UI만 없음)

## API
- [x] 카탈로그 목록 API 페이징 추가 (`/api/plots`, `/api/characters`, `/api/user-profiles`, `/api/preference-profiles`)
- [x] 대화 롤링 요약 (5턴마다 오래된 메시지를 요약으로 압축해 `<summary>`로 프롬프트에 주입, 채팅 응답 전송 후 백그라운드로 갱신)
- [x] 빈 입력 전개 요청(`message: ""`)을 user message로 저장하지 않고 전개 요청으로 처리 (row 자체는 turns FK 때문에 남지만, 대화 이력·요약 대상에서는 제외)
- [x] 플롯 인트로(시작 장면) — `plot_json.intro.blocks`(assistant/user 2타입)를 유저 프로필 확정 시점에 실제 messages row로 materialize (`docs/intro-final.md`). 별도 introMessages API 없이 기존 메시지 목록/프롬프트 히스토리/롤링 요약이 그대로 처리
- [x] 이미지 업로드 엔드포인트 (`POST /api/uploads/{kind}/{item_id}`, multipart, `data/uploads/{kind}/{id}.{ext}`에 저장 후 `avatarUrl`을 catalog item에 반영, `/uploads`로 정적 서빙). 프론트는 아직 base64 인라인 방식 — 이 엔드포인트로 전환 필요 (프론트 작업)
- [ ] 대화 내보내기 기능

## README
- [ ] UI 스크린샷 추가
