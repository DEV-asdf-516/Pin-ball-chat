import os
import sqlite3
import uuid
from pathlib import Path

from core.schema import SCHEMA_DDL
from util.string_util import join_columns


# core/db.py는 항상 <repo>/apps/api/src/core/db.py에 위치한다 (repo root까지 4단계).
# Docker는 PINBALLCHAT_ROOT=/app을 항상 명시적으로 주입하므로 이 fallback은 로컬 실행 전용이다.
_HERE: Path = Path(__file__).resolve()
ROOT: Path = Path(os.environ.get("PINBALLCHAT_ROOT") or _HERE.parents[4])
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


def find_by_id(conn: sqlite3.Connection, table: str, item_id: str) -> dict | None:
    columns: str = select_cols(table)
    row: sqlite3.Row | None = fetch_one(conn, f"SELECT {columns} FROM {table} WHERE id=?", (item_id,))
    return dict(row) if row else None


def find_all(conn: sqlite3.Connection, table: str) -> list[dict]:
    columns: str = select_cols(table)
    return [dict(r) for r in fetch_all(conn, f"SELECT {columns} FROM {table} ORDER BY id")]


def exists(conn: sqlite3.Connection, table: str, column: str, value) -> bool:
    return bool(fetch_one(conn, f"SELECT 1 FROM {table} WHERE {column}=?", (value,)))


def insert(conn: sqlite3.Connection, table: str, columns: tuple[str, ...], values: tuple) -> None:
    placeholders: str = ",".join("?" for _ in values)
    conn.execute(f"INSERT INTO {table} ({join_columns(columns)}) VALUES ({placeholders})", values)
