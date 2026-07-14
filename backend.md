# Backend (apps/api)

## 원칙
- 요청된 작업만 한다. 동작 변경과 구조 변경을 섞지 않는다.
- 관련 없는 코드·포맷은 건드리지 않는다. 기존 스타일을 따른다.
- 중복이 2회 생기기 전에는 공통화하지 않는다.
- 내 수정으로 생긴 unused import/변수/orphan 파일은 제거, 기존 dead code는 유지.
- 명시 요청 없이 금지: 새 class/registry/factory/DI container, SQLAlchemy,
  repository 대량 도입, 전면 async 전환, Pydantic model 대량 추가, 폴더 확장.
- 주석은 #으로만 작성

## 계층 책임 (src/)
- `server/` — HTTP 계층: app 생성, router 등록, schema, error 매핑, route handler.
  도메인 flow·provider 호출·복잡한 DB write 금지. 새 endpoint는 `server/routes/`, `app.py`는 얇게.
- `domain/` — 유스케이스, prompt 구성, 도메인 검증. FastAPI import·`HTTPException` 금지.
- `ai/` — provider 연동만, 전부 async. 새 provider는 `AIProvider` 상속 + `name`/`stream()`만 구현.
  `list_models()`은 optional(기본은 NotImplementedError) — 지원하는 provider만 override.
  DB write·HTTP response·저장 정책 금지.
- `core/` — DB connection, schema init, whitelist, low-level query helper.
- `util/` — 도메인 모르는 순수 helper만. DB·table명·FastAPI 금지.
- route handler는 파싱 → domain 호출 → error 매핑 → response만.

## 콘텐츠 파일
- 전부 `data/` 밑(배포 시 코드 위치와 무관한 단일 데이터 디렉토리, `PINBALLCHAT_ROOT`로 이동 가능): `data/preferences/` = `.json`(생성 방식만), `data/characters/`·`data/user_profiles/`·`data/plots/` = `.md`(순수 서술만), `data/rules/`에 시스템/요약 프롬프트 JSON.
- 전역 규칙은 `preferences/global.json`에만 두고 개별 파일에서 반복하지 않는다.
- OOC는 md 본문 `OOC:` 줄 또는 json `ooc[]` 중 한 곳에만.
- scope 우선순위: global → genre → character → plot → conversation (list는 extend, scalar는 덮어씀).
- `kind`는 하드코딩 대신 `domain.catalog.specs.CatalogKind`.

## SQL
- `domain/**`에서 `conn.execute()` 금지 — `core/db/sqlite.py` 함수 + `TableSpec`으로만 쿼리.
- R은 `ReadQuery`, CUD는 `WriteQuery`. PK 단건은 `ReadQuery/WriteQuery.by_id(spec, value)`.
- `where`/`set`/`values`/`params`는 `Bind({...})`로 감싼다 (`by_id`는 자동).
  단, `conn.execute()`에 바로 들어가는 최종 bind dict는 bare `dict` 그대로.
- 비교·subquery·기존 컬럼 참조는 `Eq/Ne/Gt/Lt/In/NotIn/RawSQL` 마커, 손으로 쓴 SQL은 `RawSQL`.
- 커서 페이지네이션 WHERE는 `CursorQuery.clause(column, before, prefix=...)`.
- named binding(`:key`)만 사용, positional `?` 금지. table/column은 whitelist에서만.
- schema 변경은 별도 작업으로 분리.

## 이름
- `helper`/`common`/`misc` 같은 포괄 이름 금지. 파일 내부 전용 helper는 `_prefix`.

## 검증
```bash
python -m compileall -q src
PYTHONPATH=src python -c "from server.app import create_app; print(create_app().title)"
```
테스트가 있으면 전체 실행.
