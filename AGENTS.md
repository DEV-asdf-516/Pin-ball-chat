# AGENTS.md

## 목표
작고 명확한 FastAPI 백엔드 구조를 유지한다.
AI는 요청된 작업만 수행한다. 구조 개선은 동작 변경과 분리한다.

## 기본 원칙
- 관련 없는 코드는 건드리지 않는다.
- 동작 변경과 구조 변경을 섞지 않는다.
- 큰 추상화보다 작은 함수와 명확한 파일명을 우선한다.
- 명시 요청 없이 새 class, registry, factory, DI container를 만들지 않는다.
- 실제 중복이 두 번 이상 생기기 전에는 공통화하지 않는다.
- 기존 스타일을 따른다.
- 수정으로 새로 생긴 unused import, unused variable, orphan file은 제거한다.
- 기존 dead code는 요청 없이는 삭제하지 않는다.

## 권장 구조
```text
src/
  main.py
  server/
    app.py
    router.py
    dependencies.py
    errors.py
    schemas.py
    routes/
  domain/
  ai/
  core/
  util/
```

## 계층 책임

### `server/`
HTTP 계층이다.
담당:
- FastAPI app 생성
- router 등록
- request/response schema
- dependency wiring
- HTTP error mapping
- route handler
금지:
- 긴 도메인 flow 구현
- provider 직접 호출
- 복잡한 DB write 직접 구현

### `domain/`
유스케이스와 도메인 규칙을 담당한다.
담당:
- application use case
- prompt/context 구성
- 도메인 검증
- import orchestration
금지:
- FastAPI import
- `HTTPException` raise
- request/response schema 의존

### `ai/`
AI provider 연동만 담당한다.
금지:
- DB write
- HTTP response 생성
- 저장 정책 결정

### `core/`
low-level infrastructure를 담당한다.
담당:
- DB connection
- schema init
- table/column whitelist
- low-level query helper
금지:
- FastAPI route 처리
- prompt 생성
- application use case 구현

### `util/`
도메인을 모르는 순수 helper만 둔다.
허용:
- 문자열 처리
- 시간 포맷
- 파일 포맷 판별
- Markdown frontmatter parser
- JSON/Markdown 파일 하나를 읽는 loader
금지:
- DB connection 받기
- DB write
- table/column 이름 알기
- 도메인 타입 검증
- FastAPI import

## `app.py` 규칙
`server/app.py`는 얇게 유지한다.
허용:
- `FastAPI()` 생성
- middleware 등록
- exception handler 등록
- lifespan 등록
- router 등록 호출
금지:
- feature endpoint 추가
- route handler 대량 작성
- DB query 작성
- provider 호출
새 endpoint는 `server/routes/`에 둔다.

## router / route 규칙
- `server/router.py`는 router 등록만 담당한다.
- route handler는 request 파싱, dependency 수신, domain 함수 호출, domain error 매핑, response 반환만 담당한다.
- route handler에 긴 flow, SQL 세부 구현, provider 호출을 넣지 않는다.

## 파일 기반 콘텐츠 import 규칙
파일 기반 콘텐츠 import는 다음 기준을 따른다.
```text
domain/
  content/
    specs.py
    importer.py
    reader.py
    writer.py
  characters.py
  user_profiles.py
  plots.py
util/
  frontmatter.py
  content_file_util.py
  time_util.py
```
- `specs.py`: `ContentKind` enum, dirname/table/kind/columns 매핑 (`CONTENT_SPECS`, `KIND_DIR`, `KIND_TABLE`, `TABLE_COLUMNS`), `ContentPayload` 및 하위 dataclass, `parse_content_data` — 콘텐츠 스키마의 단일 소스
- `reader.py`: 조회 전용 (`find_content_by_id`, `content_exists`, `find_all_content`) — `core.db`의 `find_by_id`/`exists`/`find_all`을 `KIND_TABLE` 기준으로 감싼다
- `writer.py`: 콘텐츠 항목 쓰기 전담. `upsert_content_item`(단일 항목 DB upsert, `importer.py`와 공유하는 저수준 프리미티브)과 `create_content_item`/`update_content_item`/`delete_content_item`(파일 쓰기 + DB upsert, id/참조 검증)을 모두 포함한다
- `importer.py`: 대량 import 흐름, type 검증, 참조 검증, error 수집 — 실제 upsert는 `writer.py`의 `upsert_content_item`에 위임
- `domain/characters.py`, `domain/user_profiles.py`, `domain/plots.py`: 각 리소스의 단건 조회(`get_character`/`get_user_profile`/`get_plot`, 없으면 `NotFound`) — 실제 사용처(해당 `server/routes/*.py`)와 1:1로 대응하는 도메인 파일
- `frontmatter.py`: Markdown frontmatter parser/renderer
- `content_file_util.py`: 파일 하나를 읽고/쓰며 표준 tuple로 변환
- `time_util.py`: 범용 시간 helper
- DB table/column을 아는 코드는 `util/`에 두지 않는다.
- `kind` 값은 문자열 하드코딩 대신 `domain.content.specs.ContentKind`를 쓴다.

## 콘텐츠 파일 포맷 계약

### 포맷 규칙
- `preferences/` — 무조건 `.json`
- `characters/`, `user_profiles/`, `plots/` — 무조건 `.md` (YAML frontmatter + 본문)

### 각 타입이 담는 것
| 타입 | 담는 것 | 담지 않는 것 |
|---|---|---|
| `characters/*.md` | 성격, 말투, 예시 대사 (순수 서술) | 생성 규칙, 전역 금지 |
| `user_profiles/*.md` | 역할, 외모, 소지품, 조직도 (순수 서술) | assistant 행동 규칙 |
| `plots/*.md` | 관계, 세계관, 등장인물 (순수 서술) | 생성 선호, 응답 형식 |
| `preferences/*.json` | 생성 방식만 | 서술, 묘사 |

### preference 필드 → 프롬프트 섹션 매핑
| 필드 | 프롬프트 섹션 | 비고 |
|---|---|---|
| `profile.generationRules[]` | `[생성 규칙]` | 직접 bullet |
| `profile.preferredNotes[]` | `[생성 규칙]` | "선호: " 접두사 |
| `profile.dislikedPatterns[]` | `[생성 규칙]` | "금지: " 접두사 |
| `profile.inputMarkup[]` | `[입력 표기]` | 직접 bullet |
| `ooc[]` | `[생성 규칙]` | 직접 bullet |

### preference scope 우선순위
`global` → `genre` → `character` → `plot` → `conversation`
같은 scope가 충돌하면 나중에 합산된다 (list 필드는 extend, scalar 필드는 덮어쓴다).

### 전역 규칙 관리
"AI라고 말하지 않는다", "사용자의 행동을 대신 확정하지 않는다" 같은 전역 규칙은
`preferences/global.json`에만 둔다. 개별 콘텐츠 파일에서 반복하지 않는다.

### OOC 작성 위치
- 콘텐츠 파일(`.md`) 본문: `OOC: ...` 줄로 작성 가능
- preference 파일(`.json`): `ooc[]` 배열로 작성
- 같은 내용을 두 곳에 동시에 쓰지 않는다.

## 이름 짓기
- `helper`, `common`, `misc`, `resource` 같은 포괄 이름을 피한다.
- 파일명은 책임이 드러나게 짓는다.
- DB에 데이터를 반영하면 `importer`, `upsert`, `loader`, `sync` 중 실제 책임에 맞게 쓴다.
- 단일 파일 안에서만 쓰는 helper는 `_private_function`으로 둔다.

## 금지되는 과잉 설계
명시 요청 없이는 다음을 하지 않는다.
- SQLAlchemy 도입
- repository class 대량 도입
- DI container 도입
- Clean Architecture식 과분한 폴더 확장
- provider abstraction 재설계
- 전면 async 전환
- Pydantic model 대량 추가
- unrelated formatting 변경

## SQL 규칙
- value는 parameter binding을 사용한다.
- table/column 이름은 whitelist에서만 가져온다.
- 사용자 입력을 SQL identifier로 직접 넣지 않는다.
- schema 변경은 별도 작업으로 분리한다.

## 검증
구조 변경 후 최소 검증:
```bash
python -m compileall -q src
PYTHONPATH=src python -c "from server.app import create_app; print(create_app().title)"
```
테스트가 있으면 전체 테스트를 실행한다.
