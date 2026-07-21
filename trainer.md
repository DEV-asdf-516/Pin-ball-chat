# Trainer (trainer/)

## 개요
- 대화 데이터를 모아 LoRA 학습을 돌리고 결과를 Ollama에 등록하는 파이프라인.
- 흐름: 데이터셋 준비(import/export) → 학습 큐 등록(API) → worker가 폴링·실행(jobs) → GGUF 변환 → `ollama create`.
- 실행 모드: Linux/GPU PC는 `docker compose --profile trainer up -d`, Apple Silicon은 네이티브 venv(MLX가 Metal 필요). 상세는 [trainer/README.md](trainer/README.md).

## 폴더 역할
- `web/` — 브라우저 UI (localhost:8090). 바닐라 JS 정적 파일.
- `core/`, `domain/`, `util.py` — trainer 서비스 전체(api/jobs/worker)가 공유하는 코드. 특정 실행 모드에 종속되지 않는다:
  - `core/db/` — SQLite 연결·스키마(`connect()`/`initialize()`/`TRAINING_RUNS`), 앱 본체 DB read-only 접근(`app_db.py`).
  - `core/errors.py` — `NotFound`/`Conflict`/`AppDbUnavailable`/`get_or_raise`. apps/api의 `core/errors.py`와 동일한 역할.
  - `domain/` — HTTP를 모르는 검증·저장 로직(`datasets.py`/`importer.py`/`recipes.py`/`runs.py`/`training_runs.py`). api·jobs·worker가 같은 함수를 재사용한다 — 별도 구현 금지.
  - `util.py` — 도메인 모르는 순수 helper만(`trainer_root()`/`utc_now()`). DB·dataset·FastAPI 지식 금지.
- `api/` — FastAPI 계층(apps/api의 `server/`에 대응): `app.py`(엔트리포인트), `errors.py`(예외→HTTP 매핑), `specs.py`(DTO), `dependencies.py`(DI), `routes/`(엔드포인트). 요청 검증 후 큐에 넣기만 하고 학습을 직접 실행하지 않는다.
- `worker/` — 단일 프로세스 폴링 worker. 10초마다 큐를 확인해 QUEUED 작업을 집어 실행.
- `jobs/` — 실제 작업 스크립트(학습·GGUF 변환·Ollama 등록·데이터셋 import/export). worker가 subprocess로 실행하며 단독 CLI 실행도 가능.
- `recipes/` — 학습 설정 YAML(backend, base_model, training/lora 파라미터).
- `datasets/` — 학습용 JSONL 데이터셋 저장소(manifest + rows).
- `runs/` — 학습 산출물(adapters, merged, GGUF, run_meta.json, job-*.log).
- `data/` — `trainer.sqlite` (training_runs 큐 테이블 하나).

## 아키텍처 규칙
- API와 worker의 유일한 연결 고리는 SQLite `training_runs` 테이블. 둘 사이에 직접 호출·공유 메모리·다른 IPC를 추가하지 않는다.
- API route는 검증 → 큐 INSERT → row 반환까지만. 학습·변환·등록 로직을 API 프로세스에서 실행하지 않는다.
- worker(`worker/runner.py`)는 실행 소유자일 뿐 학습 실행 메커니즘(mlx_lm 학습, GGUF 변환, ollama 등록)을 모른다 — 그건 전부 `jobs/` subprocess에 둔다. 단, `domain/`은 trainer 서비스 전체가 공유하는 계층이라 api·jobs·worker 어디서든 재사용해도 된다 — worker가 스케줄링(어떤 backend의 job을 집을지)을 위해 `domain/recipes.py`·`domain/runs.py`의 함수로 recipe/run 메타데이터를 읽는 것은 이 규칙 위반이 아니다.
- 학습·변환 로직 수정은 `jobs/`에서, 큐·상태 관리 수정은 `core/db/`·`worker/runner.py`에서. 섞지 않는다.
- 동시 실행은 1개(RUNNING 존재 시 대기). 상태 전이는 QUEUED → RUNNING → DONE/FAILED만 사용.
- worker 시작 시 남은 RUNNING은 FAILED(`orphaned`) 처리한다 — 이 동작을 제거하지 않는다.
- 앱 본체(apps/api) DB는 `app_db_connection()`(컨텍스트 매니저, 종료 시 반드시 close)으로 읽기만 한다. trainer가 앱 DB에 write 금지. DB를 열 수 없으면 `AppDbUnavailable`(503) — 클라이언트 입력 문제인 `DatasetError`(400)와 구분한다.

## backend (mlx/cuda)
- backend 값은 `domain/specs.py`의 `Backend` StrEnum(MLX/CUDA)으로 표현한다. recipe YAML의 `backend` 필드는 `domain/recipes.py`의 `load_recipe()`/`get_recipe_backend()`로, `run_meta.json`의 backend 필드는 `domain/runs.py`의 `read_run_meta()`/`run_backend()`로 읽고 검증한다. `api/routes/runs.py`·`jobs/train_lora.py`·`jobs/export_gguf.py`·`worker/runner.py`(`backend_for()`) 전부 이 함수들과 `Backend` enum을 재사용한다 — raw string 비교(`== "cuda"` 등)나 YAML/JSON 직접 파싱 금지.
- worker(`worker/runner.py`)의 `RUNNER_BACKENDS`(필수 환경변수) 검증도 `SUPPORTED_BACKENDS`를 따로 하드코딩하지 않고 `Backend` enum에서 유효값을 가져온다.
- cuda 학습은 v0.1 미구현 — API가 큐 등록을 거부한다. 구현 전까지 이 가드를 유지.
- MLX 학습·`mlx_lm.fuse`는 Apple Silicon 네이티브에서만 동작. Docker(Linux VM)에서 mlx 작업을 집게 하지 않는다.

## 데이터셋
- 검증·중복제거·manifest 처리는 전부 `domain/datasets.py`와 `domain/importer.py` 재사용. jobs와 API가 같은 함수를 쓴다 — 별도 구현 금지.
- 이름은 `validate_name()`, 형식은 `validate_format()`(chat/preference)을 통과해야 함. recipe 파일명도 경로 조작 방지 검증(`Path(name).name != name` 거부)을 유지.
- 중복 판정은 `canonical_hash()` 기준. v0.1 학습은 chat 형식만 허용(preference는 큐 등록 거부) — 이 게이트는 `domain/training_runs.py`의 `validate_training_inputs()` 하나로 통일되어 있고, API의 `create_training_run()`과 `jobs/train_lora.py` 둘 다 이걸 호출한다. 둘 다 독립적으로 호출 가능한 진입점이라 재검증 자체는 유지하되, 규칙(chat only, cuda 미구현)은 한 곳에서만 바꾸면 된다.
- 기존 데이터셋 덮어쓰기 금지 — 존재하면 409/에러.
- 앱 DB에서 chat export할 때(`export_application_rows()`)는 generation당 최신 `generation_edits` 1건만 사용한다 — 같은 generation을 여러 번 수정해도 과거 edit이 중복 학습 row로 섞여 들어가지 않는다.

## API / DB
- 에러 응답은 `{"error": "message"}` 단일 형태로 `api/errors.py`의 `register_error_handlers()`가 중앙에서 변환한다. route handler에서 try/except로 HTTPException을 직접 만들지 말고, 도메인 예외(`DatasetError`/`DatasetFormatMismatch`/`NotFound`/`Conflict`/`AppDbUnavailable`)를 그냥 raise한다 — 새 상태코드가 필요하면 `errors.py`의 `_SIMPLE_ERRORS`에 매핑만 추가.
- DB 접근은 `core/db/`의 `connect()`만 사용(WAL + busy_timeout 5s). 스키마 변경은 `SCHEMA`(`core/db/schema.py`)와 `TRAINING_RUNS` TableSpec을 함께 갱신.
- 새 endpoint는 `api/routes/datasets.py`(데이터셋) / `api/routes/runs.py`(큐·로그)에 배치, 응답 DTO는 `api/specs.py`에 추가, `api/app.py`는 얇게.
- route handler는 파싱 → domain 함수 호출 → response만. 도메인/DB 로직을 route에 직접 두지 않는다 — 필요하면 `domain/`에 함수를 추가한다.

## 환경변수
- `TRAINER_ROOT` — trainer 디렉터리 (기본 `./trainer`)
- `TRAINER_DB_PATH` — 큐 SQLite 경로 (기본 `./trainer/data/trainer.sqlite`)
- `RUNNER_BACKENDS` — worker가 집을 backend 목록, 필수 (예: `mlx`)
- `LLAMA_CPP_DIR` — llama.cpp 경로 (GGUF 변환에 필수)
- `APP_DB_PATH` — 앱 본체 DB (app_export 용)
- `OLLAMA_HOST` — Docker에서 호스트 Ollama 접근 시
