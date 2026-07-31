# Backend (apps/api)

## 원칙
- 동작 변경과 구조 변경 분리.
- 명시 요청 없이 금지: 새 class/registry/factory/DI, SQLAlchemy, repository 대량 도입,
  전면 async 전환, Pydantic 대량 추가, 폴더 확장.
- 주석은 `#`만.

## 계층 (src/)
- `server/` — HTTP만: router 등록, schema, error 매핑, handler. 도메인 flow·provider 호출·복잡한 write 금지.
  새 endpoint는 `server/routes/`, `app.py`는 얇게. handler는 파싱 → domain 호출 → error 매핑 → response만.
- `domain/` — 유스케이스, prompt 구성, 검증. FastAPI·`HTTPException` 금지.
- `ai/` — provider 연동만, 전부 async. 새 provider는 `AIProvider` 상속 + `name`/`stream()`.
  `list_models()`은 지원 provider만 override. DB write·HTTP response·저장 정책 금지.
- `core/` — DB connection, schema init, whitelist, low-level helper.
- `util/` — 도메인 모르는 순수 helper. DB·table명·FastAPI 금지.

## 콘텐츠 파일
- 전부 `data/`(`PINBALLCHAT_ROOT`로 이동 가능): `preferences/`=json(생성 방식만),
  `characters/`·`user_profiles/`·`plots/`=md(순수 서술만), `rules/`=프롬프트 JSON.
- 전역 규칙은 `preferences/global.json`에만, 개별 파일 반복 금지.
- OOC는 md `OOC:` 줄 또는 json `ooc[]` 중 한 곳에만.
- scope: global → genre → character → plot → conversation (list extend, scalar 덮어씀).
- `kind`는 `domain.catalog.specs.CatalogKind`만.

## SQL
- `domain/**`에서 `conn.execute()` 금지 — `core/db/sqlite.py` 함수 + `TableSpec`만.
- R=`ReadQuery`, CUD=`WriteQuery`, PK 단건=`.by_id(spec, value)`.
- `where/set/values/params`는 `Bind({...})` (by_id 자동). `conn.execute()` 직전 최종 dict만 bare.
- 비교·subquery·컬럼 참조는 `Eq/Ne/Gt/Lt/In/NotIn/RawSQL`, 수기 SQL은 `RawSQL`.
- 커서 WHERE는 `CursorQuery.clause(column, before, prefix=...)`.
- named binding(`:key`)만, positional `?` 금지. table/column은 whitelist만.
- schema 변경은 별도 작업.
- api 컨테이너 가동 중 호스트 sqlite3로 실 DB 직접 write 금지(WAL 충돌 → disk I/O error).
  `docker compose exec api python -c "..."` 또는 컨테이너 내리고 작업.

## 이름
- `helper/common/misc` 금지. 파일 내부 전용은 `_prefix`.
- 도메인 public CUD는 `create_/update_/delete_`. DB 동사(select/insert/upsert/save)는 `core/db`·내부 helper만.
- 유스케이스: 선택=`choose_`, 준비=`prepare_`, 시작=`start_`, 기록=`record_`.
- 콜백은 `on_<이벤트>`(슬롯·bind 파라미터·등록 메서드), 타입 별칭은 `<이벤트>Handler`. `handle_` 금지.
  콜백으로도 등록되는 동작 메서드는 동사 이름 유지(예: `_abort_connection`).

## core/db ↔ libs/dbkit
- 쿼리 빌더 전체(`TableSpec`/`Bind`/쿼리 클래스/마커/`find_one` 등)는 `libs/dbkit`,
  `core.db`가 재노출 — `domain/**`의 `from core.db import ...`는 불변.
- `core/db/sqlite.py`에는 pinballchat 전용만: `TABLE_NAMES`, `SCHEMA_DDL`, 경로 계산.
- dbkit은 스키마·경로를 모르는 순수 엔진(타 서비스 재사용 가능).

## 검증
python -m compileall -q src
PYTHONPATH=src:../../libs python -c "from server.app import create_app; print(create_app().title)"
테스트 있으면 전체 실행.