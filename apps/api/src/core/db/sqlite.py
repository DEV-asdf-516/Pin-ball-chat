import os
import sqlite3
import uuid
from pathlib import Path

from core.db.specs import Bind, CursorQuery, Eq, Gt, In, Lt, Ne, NotIn, ReadQuery, RawSQL, TableSpec, WriteQuery
from core.schema import SCHEMA_DDL
from util.string_util import join_columns


# core/db/sqlite.py는 항상 <repo>/apps/api/src/core/db/sqlite.py에 위치한다 (repo root까지 5단계).
# Docker는 PINBALLCHAT_ROOT=/app을 항상 명시적으로 주입하므로 이 fallback은 로컬 실행 전용이다.
_HERE: Path = Path(__file__).resolve()
ROOT: Path = Path(os.environ.get("PINBALLCHAT_ROOT") or _HERE.parents[5])
# 콘텐츠 파일(characters/plots/user_profiles/preferences/rules)과 DB가 전부 이 하나의 디렉토리 밑에 산다 —
# 배포 시 코드 위치(ROOT)와 무관하게 이 한 곳만 볼륨/경로로 잡아주면 된다.
DATA_ROOT: Path = ROOT / "data"
DB_PATH: Path = Path(os.environ.get("DB_PATH", DATA_ROOT / "pinballchat.sqlite"))

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


_OPS: dict[type, str] = {Eq: "=", Ne: "<>", Gt: ">", Lt: "<"}

def _op(v) -> str:
    return _OPS.get(type(v), "=")


def _unwrap(v):
    return v.value if type(v) in _OPS else v


def _in_clause(column: str, v: In | NotIn) -> tuple[str, dict]:
    op: str = "NOT IN" if isinstance(v, NotIn) else "IN"
    if isinstance(v.values, RawSQL):
        return f"{column} {op} ({v.values.sql})", dict(v.params.values)
    names: list[str] = [f"where_{column}_{i}" for i in range(len(v.values))]
    return f"{column} {op} ({','.join(':' + n for n in names)})", dict(zip(names, v.values))


def _where(conditions: Bind) -> tuple[str, dict]:
    # update()의 set과 겹치지 않도록 바인딩 변수명에 where_ 접두사를 붙인다.
    clauses: list[str] = []
    params: dict = {}
    for c, v in conditions.items():
        if isinstance(v, (In, NotIn)):
            clause, in_params = _in_clause(c, v)
            clauses.append(clause)
            params.update(in_params)
        else:
            clauses.append(f"{c}{_op(v)}:where_{c}")
            params[f"where_{c}"] = _unwrap(v)
    return " AND ".join(clauses), params

def select_cols(table: str) -> str:
    return _column_cache[table]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def fetch_one(conn: sqlite3.Connection, query: RawSQL, params: dict | None = None) -> sqlite3.Row | None:
    return conn.execute(query.sql, params or {}).fetchone()


def fetch_all(conn: sqlite3.Connection, query: RawSQL, params: dict | None = None) -> list[sqlite3.Row]:
    return conn.execute(query.sql, params or {}).fetchall()


def find_one(conn: sqlite3.Connection, query: ReadQuery) -> dict | None:
    columns: str = select_cols(query.spec.table)
    where_clause, where_params = _where(query.where)
    row: sqlite3.Row | None = fetch_one(
        conn,
        RawSQL(f"""
        SELECT {columns}
        FROM {query.spec.table}
        WHERE {where_clause}
        """),
        where_params,
    )
    return dict(row) if row else None


def find_all(conn: sqlite3.Connection, query: ReadQuery) -> list[dict]:
    columns: str = select_cols(query.spec.table)
    where_clause, where_params = _where(query.where) if query.where else ("", {})
    rows: list[sqlite3.Row] = fetch_all(
        conn,
        RawSQL(f"""
        SELECT {columns}
        FROM {query.spec.table}
        {"WHERE " + where_clause if where_clause else ""}
        ORDER BY {query.order_by}
        """),
        where_params,
    )
    return [dict(r) for r in rows]


def paginate(conn: sqlite3.Connection, cursor_query: CursorQuery) -> dict:
    # limit+1개를 가져와 초과분 존재 여부로 hasMore를 판정.
    rows_desc: list[sqlite3.Row] = fetch_all(conn, cursor_query.query, cursor_query.to_dict())

    has_more: bool = len(rows_desc) > cursor_query.limit
    
    items: list[dict] = [dict(r) for r in rows_desc[:cursor_query.limit]]

    next_cursor: str | None = str(items[-1]["rowid"]) if has_more and items else None
    
    for item in items:
        item.pop("rowid")

    return {
        "items": items,
        "nextCursor": next_cursor,
        "hasMore": has_more
        }


def exists(conn: sqlite3.Connection, query: ReadQuery) -> bool:
    where_clause, where_params = _where(query.where)
    row: sqlite3.Row | None = fetch_one(
        conn,
        RawSQL(f"""
        SELECT 1
        FROM {query.spec.table}
        WHERE {where_clause}
        """),
        where_params,
    )
    return bool(row)


def insert(conn: sqlite3.Connection, spec: TableSpec, values: Bind) -> None:
    placeholders: str = ",".join(f":{c}" for c in spec.columns)
    conn.execute(f"INSERT INTO {spec.table} ({join_columns(spec.columns)}) VALUES ({placeholders})", values.values)


def upsert(conn: sqlite3.Connection, spec: TableSpec, values: Bind) -> None:
    placeholders: str = ",".join(f":{c}" for c in spec.columns)
    update_cols: list[str] = [c for c in spec.columns if c not in (spec.conflict_col, "created_at")]
    updates: str = ",".join(f"{c}=excluded.{c}" for c in update_cols)
    conn.execute(
        f"""
        INSERT INTO {spec.table} ({join_columns(spec.columns)})
        VALUES ({placeholders})
        ON CONFLICT({spec.conflict_col}) DO UPDATE SET {updates}
        """,
        values.values,
    )
    
def update(conn: sqlite3.Connection, query: WriteQuery) -> None:
    set_clause: str = ",".join(f"{c}={v.sql}" if isinstance(v, RawSQL) else f"{c}=:set_{c}" for c, v in query.set.items())
    set_params: dict = {f"set_{c}": v for c, v in query.set.items() if not isinstance(v, RawSQL)}
    where_clause, where_params = _where(query.where)
    conn.execute(
        f"""
        UPDATE {query.spec.table}
        SET {set_clause}
        WHERE {where_clause}
        """,
        {**set_params, **where_params},
    )

def delete(conn: sqlite3.Connection, query: WriteQuery) -> None:
    where_clause, where_params = _where(query.where)
    conn.execute(
        f"""
        DELETE FROM {query.spec.table}
        WHERE {where_clause}
        """,
        where_params,
    )
