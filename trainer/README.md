# PinballChat Trainer

PinballChat Trainer collects conversation datasets, runs LoRA training, and registers exported models with Ollama. Linux GPU PCs use Docker Compose by default; Apple Silicon uses a native virtual environment so MLX can access Metal reliably.

## Docker 실행 (기본, Linux/GPU PC)

저장소 루트에서 trainer 프로필을 시작합니다.

```sh
docker compose --profile trainer up -d
```

웹 UI는 http://localhost:8090 에서 엽니다. 서비스 로그는 다음 명령으로 확인합니다.

```sh
docker compose --profile trainer logs -f trainer-api trainer-worker
```

## Apple Silicon 실행 (네이티브)

Docker의 Linux VM은 Metal에 접근할 수 없어 MLX 학습을 실행할 수 없습니다. 또한 VM 파일 공유 경로에서 API와 worker가 trainer SQLite를 함께 열면 잠금이 불안정할 수 있으므로 네이티브 실행을 사용합니다.

저장소 루트에서 다음을 실행합니다.

```sh
python3 -m venv trainer/.venv
source trainer/.venv/bin/activate
pip install -r trainer/requirements.txt
brew install llama.cpp
export LLAMA_CPP_DIR="$(brew --prefix llama.cpp)"
```

첫 번째 터미널에서 API를 실행합니다. `trainer.api`/`trainer.worker`가 공용으로 쓰는 쿼리 빌더(`libs/dbkit`)는 저장소 루트 기준 별도 디렉터리라 `PYTHONPATH`에 추가해야 합니다.

```sh
source trainer/.venv/bin/activate
PYTHONPATH=libs uvicorn trainer.api.main:app --port 8090
```

두 번째 터미널에서 MLX worker를 실행합니다.

```sh
source trainer/.venv/bin/activate
RUNNER_BACKENDS=mlx python trainer/worker/runner.py
```

## 모드 매트릭스

| | Docker (Linux/GPU PC) | 네이티브 (Apple Silicon) |
| --- | --- | --- |
| api | O (trainer-api 컨테이너) | O (uvicorn) |
| worker: backend=mlx | X — 집지 않음 | O (`RUNNER_BACKENDS=mlx`) |
| worker: backend=cuda | O (`RUNNER_BACKENDS=cuda`) — 학습 구현은 아직 준비 단계 | X — 집지 않음 |
| register (ollama create) | O (`OLLAMA_HOST`로 호스트 Ollama 접근) | O |

## 자주 겪는 문제

- 8090에 연결할 수 없으면 `docker compose --profile trainer up -d`로 trainer 프로필이 기동됐는지 확인합니다.
- `datasets directory not found`는 `TRAINER_ROOT`가 trainer 디렉터리를 가리키는지 확인합니다.
- MLX 잡이 실행되지 않으면 worker의 `RUNNER_BACKENDS`에 `mlx`가 포함됐는지 확인합니다.
- Docker에서 Ollama 연결에 실패하면 Compose의 `extra_hosts`에 `host.docker.internal:host-gateway`가 있는지 확인합니다.
