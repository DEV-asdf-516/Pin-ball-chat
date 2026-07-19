# Trainer (trainer/)

## 개요
- 대화 데이터를 모아 LoRA 학습을 돌리고 결과를 Ollama에 등록하는 파이프라인.
- 흐름: 데이터셋 준비(import/export) → 학습 큐 등록(API) → worker가 폴링·실행(jobs) → GGUF 변환 → `ollama create`.
- 실행 모드: Linux/GPU PC는 `docker compose --profile trainer up -d`, Apple Silicon은 네이티브 venv(MLX가 Metal 필요). 상세는 [trainer/README.md](trainer/README.md).

## 폴더 역할
- `web/` — 브라우저 UI (localhost:8090). 바닐라 JS 정적 파일.
- `api/` — FastAPI 서버. 요청 검증 후 큐에 넣기만 하고 학습을 직접 실행하지 않는다.
- `worker/` — 단일 프로세스 폴링 worker. 10초마다 큐를 확인해 QUEUED 작업을 집어 실행.
- `jobs/` — 실제 작업 스크립트(학습·GGUF 변환·Ollama 등록·데이터셋 import/export). worker가 subprocess로 실행하며 단독 CLI 실행도 가능.
- `recipes/` — 학습 설정 YAML(backend, base_model, training/lora 파라미터).
- `datasets/` — 학습용 JSONL 데이터셋 저장소(manifest + rows).
- `runs/` — 학습 산출물(adapters, merged, GGUF, run_meta.json, job-*.log).
- `data/` — `trainer.sqlite` (training_runs 큐 테이블 하나).

## 아키텍처 규칙
- API와 worker의 유일한 연결 고리는 SQLite `training_runs` 테이블. 둘 사이에 직접 호출·공유 메모리·다른 IPC를 추가하지 않는다.
- API route는 검증 → 큐 INSERT → row 반환까지만. 학습·변환·등록 로직을 API 프로세스에서 실행하지 않는다.
- worker(`worker/runner.py`)는 실행 소유자일 뿐 학습 로직을 모른다 — 작업 로직은 전부 `jobs/` subprocess에 둔다.
- 학습·변환 로직 수정은 `jobs/`에서, 큐·상태 관리 수정은 `api/db.py`·`worker/runner.py`에서. 섞지 않는다.
- 동시 실행은 1개(RUNNING 존재 시 대기). 상태 전이는 QUEUED → RUNNING → DONE/FAILED만 사용.
- worker 시작 시 남은 RUNNING은 FAILED(`orphaned`) 처리한다 — 이 동작을 제거하지 않는다.
- 앱 본체(apps/api) DB는 `app_db_connection()`으로 읽기만 한다. trainer가 앱 DB에 write 금지.

## backend (mlx/cuda)
- backend는 recipe YAML의 `backend` 필드로 결정, `SUPPORTED_BACKENDS = {mlx, cuda}` 외 금지.
- worker는 `RUNNER_BACKENDS` 환경변수(필수)에 포함된 backend 작업만 집는다.
- cuda 학습은 v0.1 미구현 — API가 큐 등록을 거부한다. 구현 전까지 이 가드를 유지.
- MLX 학습·`mlx_lm.fuse`는 Apple Silicon 네이티브에서만 동작. Docker(Linux VM)에서 mlx 작업을 집게 하지 않는다.

## 데이터셋
- 검증·중복제거·manifest 처리는 전부 `api/dataset_io.py`와 `api/importer.py` 재사용. jobs와 API가 같은 함수를 쓴다 — 별도 구현 금지.
- 이름은 `validate_name()`, 형식은 `validate_format()`(chat/preference)을 통과해야 함. recipe 파일명도 경로 조작 방지 검증(`Path(name).name != name` 거부)을 유지.
- 중복 판정은 `canonical_hash()` 기준. v0.1 학습은 chat 형식만 허용(preference는 큐 등록 거부).
- 기존 데이터셋 덮어쓰기 금지 — 존재하면 409/에러.

## API / DB
- 에러 응답은 `{"error": "message"}` 단일 형태(main.py의 exception handler 경유). 새 route도 `HTTPException(detail={"error": ...})` 패턴 유지.
- DB 접근은 `api/db.py`의 `connect()`만 사용(WAL + busy_timeout 5s). 스키마 변경은 `SCHEMA`와 `TRAINING_RUNS` TableSpec을 함께 갱신.
- 새 endpoint는 `routes_datasets.py`(데이터셋) / `routes_runs.py`(큐·로그)에 배치, `main.py`는 얇게.

## 환경변수
- `TRAINER_ROOT` — trainer 디렉터리 (기본 `./trainer`)
- `TRAINER_DB_PATH` — 큐 SQLite 경로 (기본 `./trainer/data/trainer.sqlite`)
- `RUNNER_BACKENDS` — worker가 집을 backend 목록, 필수 (예: `mlx`)
- `LLAMA_CPP_DIR` — llama.cpp 경로 (GGUF 변환에 필수)
- `APP_DB_PATH` — 앱 본체 DB (app_export 용)
- `OLLAMA_HOST` — Docker에서 호스트 Ollama 접근 시
