"""Single-process polling worker that owns execution, not training logic."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LIBS = ROOT / "libs"
if str(LIBS) not in sys.path:
    sys.path.insert(0, str(LIBS))

from dbkit import Bind, OrderBy, ReadQuery, WriteQuery, exists, find_all, find_one, update

from trainer.api.dataset_io import trainer_root, utc_now
from trainer.api.db import TRAINING_RUNS, connect, initialize


SUPPORTED_BACKENDS = {"mlx", "cuda"}


def runner_backends() -> set[str]:
    value = os.environ.get("RUNNER_BACKENDS")
    if value is None:
        raise RuntimeError("RUNNER_BACKENDS is required")
    backends = {item.strip() for item in value.split(",") if item.strip()}
    if not backends:
        raise RuntimeError("RUNNER_BACKENDS must include at least one backend")
    unknown = backends - SUPPORTED_BACKENDS
    if unknown:
        raise RuntimeError(f"RUNNER_BACKENDS has unsupported backend(s): {', '.join(sorted(unknown))}")
    return backends


def backend_for(run: dict[str, object], connection: sqlite3.Connection) -> str:
    """Read a queued or running job's backend without depending on its execution mode."""
    if run["type"] == "TRAIN":
        recipe_name = run.get("recipe")
        if not isinstance(recipe_name, str) or Path(recipe_name).name != recipe_name:
            raise ValueError("training run recipe is invalid")
        recipe_path = trainer_root() / "recipes" / recipe_name
        try:
            recipe = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError("training run recipe is unavailable") from exc
        backend = recipe.get("backend") if isinstance(recipe, dict) else None
    elif run["type"] == "REGISTER":
        try:
            parent_run_id = run.get("parent_run_id")
            if not isinstance(parent_run_id, int):
                raise ValueError("register run parent is invalid")
            parent = find_one(connection, ReadQuery.by_id(TRAINING_RUNS, parent_run_id))
            if parent is None:
                raise ValueError("register run parent is unavailable")
            meta_path = trainer_root() / "runs" / str(parent["output_name"]) / "run_meta.json"
            backend = json.loads(meta_path.read_text(encoding="utf-8")).get("backend")
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("register run metadata is unavailable") from exc
    else:
        raise ValueError("training run type is invalid")
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError("training run backend is invalid")
    return backend


def mark_orphans(backends: set[str]) -> None:
    with connect() as connection:
        running = find_all(connection, ReadQuery(TRAINING_RUNS, where=Bind({"status": "RUNNING"}), order_by=(OrderBy("id"),)))
        for run in running:
            try:
                backend = backend_for(run, connection)
            except ValueError as exc:
                print(f"leaving RUNNING run {run['id']}: {exc}", flush=True)
                continue
            if backend not in backends:
                print(f"leaving RUNNING run {run['id']}: backend {backend} is not in RUNNER_BACKENDS", flush=True)
                continue
            update(connection, WriteQuery(
                TRAINING_RUNS,
                set=Bind({"status": "FAILED", "error": "orphaned", "finished_at": utc_now()}),
                where=Bind({"id": run["id"]}),
            ))


def next_run(backends: set[str]):
    with connect() as connection:
        if exists(connection, ReadQuery(TRAINING_RUNS, where=Bind({"status": "RUNNING"}))):
            return None
        queued = find_all(connection, ReadQuery(TRAINING_RUNS, where=Bind({"status": "QUEUED"}), order_by=(OrderBy("id"),)))
        for run in queued:
            try:
                backend = backend_for(run, connection)
            except ValueError as exc:
                print(f"skipping queued run {run['id']}: {exc}", flush=True)
                continue
            if backend not in backends:
                print(f"skipping queued run {run['id']}: backend {backend} is not in RUNNER_BACKENDS", flush=True)
                continue
            cursor = connection.execute(
                "UPDATE training_runs SET status = 'RUNNING', started_at = ? WHERE id = ? AND status = 'QUEUED'",
                (utc_now(), run["id"]),
            )
            if cursor.rowcount:
                return run
    return None


def command_for(run: dict[str, object]) -> list[list[str]]:
    jobs = trainer_root() / "jobs"
    if run["type"] == "TRAIN":
        return [[
            sys.executable,
            str(jobs / "train_lora.py"),
            "--datasets",
            *json.loads(run["datasets"]),
            "--recipe",
            str(run["recipe"]),
            "--output-name",
            str(run["output_name"]),
        ]]
    run_dir = trainer_root() / "runs" / str(run["output_name"])
    return [
        [sys.executable, str(jobs / "export_gguf.py"), "--run-dir", str(run_dir)],
        [sys.executable, str(jobs / "register_model.py"), "--run-dir", str(run_dir)],
    ]


def run_job(run: dict[str, object]) -> None:
    run_root = trainer_root() / "runs"
    run_root.mkdir(parents=True, exist_ok=True)
    log_path = run_root / f"job-{run['id']}.log"
    with connect() as connection:
        update(connection, WriteQuery(TRAINING_RUNS, set=Bind({"log_path": str(log_path)}), where=Bind({"id": run["id"]})))
    status = "DONE"
    error = None
    with log_path.open("w", encoding="utf-8") as log:
        for command in command_for(run):
            log.write("$ " + " ".join(command) + "\n")
            log.flush()
            try:
                result = subprocess.run(command, stdout=log, stderr=subprocess.PIPE, text=True)
            except OSError as exc:
                status = "FAILED"
                error = str(exc)
                log.write(error + "\n")
                break
            if result.stderr:
                log.write(result.stderr)
                if not result.stderr.endswith("\n"):
                    log.write("\n")
            if result.returncode:
                status = "FAILED"
                error = result.stderr[-2000:].strip() or f"command exited {result.returncode}"
                break
    with connect() as connection:
        update(connection, WriteQuery(
            TRAINING_RUNS,
            set=Bind({"status": status, "error": error, "finished_at": utc_now()}),
            where=Bind({"id": run["id"]}),
        ))


def main() -> int:
    try:
        backends = runner_backends()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    initialize()
    mark_orphans(backends)
    print(f"trainer worker polling for backends: {', '.join(sorted(backends))}", flush=True)
    while True:
        run = next_run(backends)
        if run is None:
            time.sleep(10)
            continue
        run_job(run)
        time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
