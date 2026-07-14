# TODO

## UI
- [x] 대화 목록 카드 제목과 채팅방 헤더 제목을 길게 누르면 메뉴 없이 바로 긴 둥근 인라인 편집칸 표시 (바깥 클릭 저장, Enter 저장, Esc 또는 뒤로가기 취소)
- [x] 대화 목록도 `nextCursor`/`hasMore`를 사용해 추가 페이지 로드
- [x] 플롯 제작 화면 추가 (`+` 원 버튼 → 제작 화면 전환 → 저장 후 상세 이동)
- [x] 플롯 관리 화면 추가 (플롯 수정·삭제)
- [ ] 프로필 이미지 업로드 (캐릭터 프사)

## API 있음 / UI 없음
- [x] 유저 프로필 생성/수정/삭제 UI (`POST/PUT/DELETE /api/user-profiles`)
- [ ] 독립 캐릭터 관리 UI (`PUT/DELETE /api/characters/{id}`; 생성은 현재 플롯 생성 흐름에만 붙어 있음)
- [x] 메시지 삭제 UI (`DELETE /api/messages/{messageId}`)
- [ ] 메시지 일괄 삭제 UI (`POST /api/messages/batch-delete`)
- [ ] 턴 후보 목록 조회 UI (`GET /api/turns/{turnId}/generations`; 새로고침 후 후보 전환 복원 등)

## API
- [x] 카탈로그 목록 API 페이징 추가 (`/api/plots`, `/api/characters`, `/api/user-profiles`, `/api/preference-profiles`)
- [x] 대화 롤링 요약 (5턴마다 오래된 메시지를 요약으로 압축해 `<summary>`로 프롬프트에 주입, 채팅 응답 전송 후 백그라운드로 갱신)
- [x] 빈 입력 전개 요청(`message: ""`)을 user message로 저장하지 않고 전개 요청으로 처리 (row 자체는 turns FK 때문에 남지만, 대화 이력·요약 대상에서는 제외)
- [ ] 이미지 업로드 엔드포인트
- [ ] 콘텐츠 동적 관리 (캐릭터/선호 파일 UI 추가·수정·삭제)

## README
- [ ] UI 스크린샷 추가
