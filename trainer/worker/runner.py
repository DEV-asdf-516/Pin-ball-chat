# Single-process polling worker that owns execution, not training logic.

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator

ROOT: Path = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LIBS: Path = ROOT / "libs"
if str(LIBS) not in sys.path:
    sys.path.insert(0, str(LIBS))

from dbkit import Bind, OrderBy, ReadQuery, WriteQuery, exists, find_all, find_one, update

from trainer.core.db import TRAINING_RUNS, connect, initialize
from trainer.domain.recipes import get_recipe_backend
from trainer.domain.runs import read_run_meta, run_backend
from trainer.domain.specs import Backend
from trainer.util import trainer_root, utc_now


log = logging.getLogger(__name__)


def backends_from_env() -> set[str]:
    value: str | None = os.environ.get("RUNNER_BACKENDS")
    if value is None:
        raise RuntimeError("RUNNER_BACKENDS is required")

    backends: set[str] = {item.strip() for item in value.split(",") if item.strip()}

    if not backends:
        raise RuntimeError("RUNNER_BACKENDS must include at least one backend")

    unknown: set[str] = backends - {b.value for b in Backend}

    if unknown:
        raise RuntimeError(f"RUNNER_BACKENDS has unsupported backend(s): {', '.join(sorted(unknown))}")

    return backends


def backend_for(run: dict[str, object], conn: sqlite3.Connection) -> Backend:
    # Read a queued or running job's backend without depending on its execution mode.
    if run["type"] == "TRAIN":
        recipe_name: object = run.get("recipe")
        
        if not isinstance(recipe_name, str):
            raise ValueError("training run recipe is invalid")
        
        return get_recipe_backend(recipe_name)

    if run["type"] == "REGISTER":
        parent_run_id: object = run.get("parent_run_id")
        
        if not isinstance(parent_run_id, int):
            raise ValueError("register run parent is invalid")
        
        parent: dict[str, object] | None = find_one(conn, ReadQuery.by_id(TRAINING_RUNS, parent_run_id))
        
        if parent is None:
            raise ValueError("register run parent is unavailable")
        
        run_dir: Path = trainer_root() / "runs" / str(parent["output_name"])
        
        return run_backend(read_run_meta(run_dir))

    raise ValueError("training run type is invalid")


def finish_run(conn: sqlite3.Connection, run_id: object, status: str, error: str | None) -> None:
    # run을 종료 상태로 기록하는 유일한 경로.
    update(conn, WriteQuery(
        TRAINING_RUNS,
        set=Bind({
            "status": status, 
            "error": error, 
            "finished_at": utc_now()
        }),
        where=Bind({"id": run_id}),
    ))


def eligible_runs(conn: sqlite3.Connection, status: str, backends: set[str], skip_verb: str) -> Iterator[dict[str, object]]:
    # RUNNER_BACKENDS로 처리 가능한 run만 통과시키는 공통 필터.
    runs: list[dict[str, object]] = find_all(
        conn, 
        ReadQuery(TRAINING_RUNS, where=Bind({"status": status}), 
        order_by=(OrderBy("id"),))
    )
    for run in runs:
        try:
            backend: Backend = backend_for(run, conn)
        except ValueError as exc:
            log.info("%s run %s: %s", skip_verb, run["id"], exc)
            continue
        if backend not in backends:
            log.info("%s run %s: backend %s is not in RUNNER_BACKENDS", skip_verb, run["id"], backend)
            continue
        yield run


def next_run(backends: set[str]) -> dict[str, object] | None:
    with connect() as conn:
        if exists(conn, ReadQuery(TRAINING_RUNS, where=Bind({"status": "RUNNING"}))):
            return None
        for run in eligible_runs(conn, "QUEUED", backends, "skipping queued"):
            cursor: sqlite3.Cursor = update(conn, WriteQuery(
                TRAINING_RUNS,
                set=Bind({"status": "RUNNING", "started_at": utc_now()}),
                where=Bind({"id": run["id"], "status": "QUEUED"}),
            ))
            if cursor.rowcount:
                return run
    return None


def run_job(run: dict[str, object]) -> None:
    run_root: Path = trainer_root() / "runs"
    run_root.mkdir(parents=True, exist_ok=True)
    log_path: Path = run_root / f"job-{run['id']}.log"

    with connect() as conn:
        update(conn, WriteQuery(TRAINING_RUNS, set=Bind({"log_path": str(log_path)}), where=Bind({"id": run["id"]})))

    status: str = "DONE"
    error: str | None = None

    jobs: Path = trainer_root() / "jobs"
    if run["type"] == "TRAIN":
        commands: list[list[str]] = [[
            sys.executable,
            str(jobs / "train_lora.py"),
            "--datasets",
            *json.loads(run["datasets"]),
            "--recipe",
            str(run["recipe"]),
            "--output-name",
            str(run["output_name"]),
        ]]
    else:
        run_dir: Path = trainer_root() / "runs" / str(run["output_name"])
        commands = [
            [sys.executable, str(jobs / "export_gguf.py"), "--run-dir", str(run_dir)],
            [sys.executable, str(jobs / "register_model.py"), "--run-dir", str(run_dir)],
        ]

    with log_path.open("w", encoding="utf-8") as log_file:
        for command in commands:
            log_file.write("$ " + " ".join(command) + "\n")
            log_file.flush()
            try:
                result: subprocess.CompletedProcess[str] = subprocess.run(
                    command, 
                    stdout=log_file, 
                    stderr=subprocess.PIPE, 
                    text=True
                )
            except OSError as exc:
                status = "FAILED"
                error = str(exc)
                log_file.write(error + "\n")
                break

            if result.stderr:
                log_file.write(result.stderr)
            
                if not result.stderr.endswith("\n"):
                    log_file.write("\n")
            
            if result.returncode:
                status = "FAILED"
                error = result.stderr[-2000:].strip() or f"command exited {result.returncode}"
                break
            
    with connect() as conn:
        finish_run(conn, run["id"], status, error)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    
    try:
        backends: set[str] = backends_from_env()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    
    initialize()
    with connect() as conn:
        for run in eligible_runs(conn, "RUNNING", backends, "leaving RUNNING"):
            finish_run(conn, run["id"], "FAILED", "orphaned")

    log.info("trainer worker polling for backends: %s", ", ".join(sorted(backends)))
    
    while True:
        run: dict[str, object] | None = next_run(backends)
        if run is None:
            time.sleep(10)
            continue
        try:
            run_job(run)
        except Exception as exc:
            log.exception("run %s crashed", run["id"])
            with connect() as conn:
                finish_run(conn, run["id"], "FAILED", str(exc))
        time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
