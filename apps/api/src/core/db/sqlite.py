import os
import sqlite3
from pathlib import Path

import dbkit
from core.schema import SCHEMA_DDL

# core/db/sqlite.py는 항상 <repo>/apps/api/src/core/db/sqlite.py에 위치한다 (repo root까지 5단계).
# Docker는 PINBALLCHAT_ROOT=/app을 항상 명시적으로 주입하므로 이 fallback은 로컬 실행 전용이다.
_HERE: Path = Path(__file__).resolve()
ROOT: Path = Path(os.environ.get("PINBALLCHAT_ROOT") or _HERE.parents[5])
# 콘텐츠 파일(characters/plots/user_profiles/preferences/rules)과 DB가 전부 이 하나의 디렉토리 밑에 산다 —
# 배포 시 코드 위치(ROOT)와 무관하게 이 한 곳만 볼륨/경로로 잡아주면 된다.
DATA_ROOT: Path = ROOT / "data"
DB_PATH: Path = Path(os.environ.get(
    "DB_PATH", DATA_ROOT / "pinballchat.sqlite"))

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


def connect(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    return dbkit.connect(db_path)


def init_db(conn: sqlite3.Connection) -> None:
    dbkit.init_db(conn, SCHEMA_DDL, TABLE_NAMES)
