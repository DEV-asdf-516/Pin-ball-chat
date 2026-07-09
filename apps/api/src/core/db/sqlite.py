import os
import sqlite3
import uuid
from pathlib import Path

from core.db.specs import Not, RawSQL, TableSpec
from core.schema import SCHEMA_DDL
from util.string_util import join_columns


# core/db/sqlite.py는 항상 <repo>/apps/api/src/core/db/sqlite.py에 위치한다 (repo root까지 5단계).
# Docker는 PINBALLCHAT_ROOT=/app을 항상 명시적으로 주입하므로 이 fallback은 로컬 실행 전용이다.
_HERE: Path = Path(__file__).resolve()
ROOT: Path = Path(os.environ.get("PINBALLCHAT_ROOT") or _HERE.parents[5])
DB_PATH: Path = Path(os.environ.get("DB_PATH", ROOT / "data" / "pinballchat.sqlite"))

TABLE_NAMES: list[str] = [
    "characters",
    "user_profiles",
    "plots",
    "preference_profiles",
    "conversations",
    "conversation_settings",
    "messages",
    "turns",
    "generations",
]

_column_cache: dict[str, str] = {}


def select_cols(table: str) -> str:
    return _column_cache[table]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def connect(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # async 라우트 핸들러는 event loop 스레드에서 실행되지만, 이 connection은
    # FastAPI가 sync dependency(get_db_conn)를 위해 별도로 띄운 threadpool 스레드에서 생성된다.
    # 요청 하나당 connection 하나를 순차적으로만 쓰므로(진짜 동시 접근 없음) check_same_thread=False로 안전하다.
    conn: sqlite3.Connection = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_DDL)
    conn.commit()
    for table in TABLE_NAMES:
        _column_cache[table] = join_columns(tuple(row["name"] for row in conn.execute(f"PRAGMA table_info({table})")))


def fetch_one(conn: sqlite3.Connection, query: str, params: tuple = ()) -> sqlite3.Row | None:
    return conn.execute(query, params).fetchone()


def fetch_all(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[sqlite3.Row]:
    return conn.execute(query, params).fetchall()


def find_one(conn: sqlite3.Connection, spec: TableSpec, item_id: str, column: str | None = None, extra_where: str = "", extra_params: tuple = ()) -> dict | None:
    column = column or spec.conflict_col
    columns: str = select_cols(spec.table)
    row: sqlite3.Row | None = fetch_one(
        conn,
        f"""
        SELECT {columns}
        FROM {spec.table}
        WHERE {column}=? {extra_where}
        """,
        (item_id, *extra_params),
    )
    return dict(row) if row else None


def find_all(conn: sqlite3.Connection, spec: TableSpec, order_by: str = "id", where: str = "", where_params: tuple = ()) -> list[dict]:
    columns: str = select_cols(spec.table)
    rows: list[sqlite3.Row] = fetch_all(
        conn,
        f"""
        SELECT {columns}
        FROM {spec.table}
        {where}
        ORDER BY {order_by}
        """,
        where_params,
    )
    return [dict(r) for r in rows]


def exists(conn: sqlite3.Connection, spec: TableSpec, column: str, value, extra_where: str = "", extra_params: tuple = ()) -> bool:
    row: sqlite3.Row | None = fetch_one(
        conn,
        f"""
        SELECT 1
        FROM {spec.table}
        WHERE {column}=? {extra_where}
        """,
        (value, *extra_params),
    )
    return bool(row)


def insert(conn: sqlite3.Connection, spec: TableSpec, values: dict) -> None:
    placeholders: str = ",".join("?" for _ in spec.columns)
    conn.execute(f"INSERT INTO {spec.table} ({join_columns(spec.columns)}) VALUES ({placeholders})", tuple(values[c] for c in spec.columns))


def update(conn: sqlite3.Connection, spec: TableSpec, set: dict, where: dict) -> None:
    """set의 값이 RawSQL이면 바인딩 없이 그 SQL을 그대로 쓴다 (예: {"regenerate_count": RawSQL("regenerate_count+1")}).
    where의 값이 Not이면 <> 비교, 그 외엔 = 비교. 여러 컬럼은 AND로 묶인다."""
    set_clause: str = ",".join(f"{c}={v.sql}" if isinstance(v, RawSQL) else f"{c}=?" for c, v in set.items())
    set_params: tuple = tuple(v for v in set.values() if not isinstance(v, RawSQL))
    where_clause: str = " AND ".join(f"{c}<>?" if isinstance(v, Not) else f"{c}=?" for c, v in where.items())
    where_params: tuple = tuple(v.value if isinstance(v, Not) else v for v in where.values())
    conn.execute(
        f"""
        UPDATE {spec.table}
        SET {set_clause}
        WHERE {where_clause}
        """,
        (*set_params, *where_params),
    )

def delete(conn: sqlite3.Connection, spec: TableSpec, column: str, value) -> None:
    conn.execute(
        f"""
        DELETE FROM {spec.table}
        WHERE {column}=?
        """,
        (value,),
    )



def upsert(conn: sqlite3.Connection, spec: TableSpec, values: dict) -> None:
    placeholders: str = ",".join("?" for _ in spec.columns)
    update_cols: list[str] = [c for c in spec.columns if c not in (spec.conflict_col, "created_at")]
    updates: str = ",".join(f"{c}=excluded.{c}" for c in update_cols)
    conn.execute(
        f"""
        INSERT INTO {spec.table} ({join_columns(spec.columns)})
        VALUES ({placeholders})
        ON CONFLICT({spec.conflict_col}) DO UPDATE SET {updates}
        """,
        tuple(values[c] for c in spec.columns),
    )
