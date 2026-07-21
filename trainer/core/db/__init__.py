# SQLite access for trainer-only job state.

from __future__ import annotations

from dbkit import TableSpec

from .sqlite import TABLE_NAMES, connect, initialize, trainer_db_path

# dbkit.insert()는 values(Bind)의 키로 컬럼 목록을 만들어서 TRAIN/REGISTER가 서로 다른 컬럼
# subset을 넣어도 그대로 동작한다 — 아래 columns는 문서화용이고 insert()에서는 실제로 안 쓰인다.
TRAINING_RUNS: TableSpec = TableSpec(
    table="training_runs",
    columns=(
        "type",
        "status",
        "datasets",
        "recipe",
        "output_name",
        "parent_run_id",
        "log_path",
        "error",
        "created_at",
        "started_at",
        "finished_at",
    ),
)

__all__ = [
    "TABLE_NAMES",
    "TRAINING_RUNS",
    "connect",
    "initialize",
    "trainer_db_path",
]
