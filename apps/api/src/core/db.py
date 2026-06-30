import os
import sqlite3
import uuid
from pathlib import Path

from domain.content_importer import import_content_catalog
from util.time_util import utc_now_string


_HERE = Path(__file__).resolve()
ROOT = Path(os.environ.get("PINBALLCHAT_ROOT", _HERE.parents[3] if len(_HERE.parents) > 3 else _HERE.parents[1]))
DB_PATH = Path(os.environ.get("DB_PATH", ROOT / "data" / "pinballchat.sqlite"))

TABLE_COLUMNS = {
    "characters": "id,name,profile_json,source_format,source_text,created_at,updated_at",
    "user_profiles": "id,name,profile_json,source_format,source_text,created_at,updated_at",
    "plots": "id,title,character_id,user_profile_id,plot_json,source_format,source_text,created_at,updated_at",
    "preference_profiles": "id,scope,scope_id,profile_json,source_format,source_text,confidence,created_at,updated_at",
    "conversations": "id,plot_id,title,active_adapter_id,created_at,updated_at",
    "turns": "id,conversation_id,user_message_id,selected_generation_id,regenerate_count,status,created_at,updated_at",
    "generations": "id,turn_id,conversation_id,plot_id,character_id,user_profile_id,model_id,adapter_id,candidate_index,prompt_snapshot,prompt_hash,output_text,params_json,output_token_count,selected,rejected,created_at",
}


def select_cols(table):
    return TABLE_COLUMNS[table]


def now():
    return utc_now_string()


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def connect(db_path=DB_PATH):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS characters (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          profile_json TEXT NOT NULL,
          source_format TEXT NOT NULL DEFAULT 'json',
          source_text TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_profiles (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          profile_json TEXT NOT NULL,
          source_format TEXT NOT NULL DEFAULT 'json',
          source_text TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS plots (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          character_id TEXT NOT NULL,
          user_profile_id TEXT NOT NULL,
          plot_json TEXT NOT NULL,
          source_format TEXT NOT NULL DEFAULT 'json',
          source_text TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(character_id) REFERENCES characters(id),
          FOREIGN KEY(user_profile_id) REFERENCES user_profiles(id)
        );
        CREATE TABLE IF NOT EXISTS preference_profiles (
          id TEXT PRIMARY KEY,
          scope TEXT NOT NULL,
          scope_id TEXT,
          profile_json TEXT NOT NULL,
          source_format TEXT NOT NULL DEFAULT 'json',
          source_text TEXT,
          confidence REAL NOT NULL DEFAULT 1.0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversations (
          id TEXT PRIMARY KEY,
          plot_id TEXT NOT NULL,
          title TEXT,
          active_adapter_id TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(plot_id) REFERENCES plots(id)
        );
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY,
          conversation_id TEXT NOT NULL,
          role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
          content TEXT NOT NULL,
          turn_id TEXT,
          generation_id TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(conversation_id) REFERENCES conversations(id)
        );
        CREATE TABLE IF NOT EXISTS turns (
          id TEXT PRIMARY KEY,
          conversation_id TEXT NOT NULL,
          user_message_id TEXT NOT NULL,
          selected_generation_id TEXT,
          regenerate_count INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'open',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(conversation_id) REFERENCES conversations(id),
          FOREIGN KEY(user_message_id) REFERENCES messages(id)
        );
        CREATE TABLE IF NOT EXISTS generations (
          id TEXT PRIMARY KEY,
          turn_id TEXT NOT NULL,
          conversation_id TEXT NOT NULL,
          plot_id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          user_profile_id TEXT NOT NULL,
          model_id TEXT NOT NULL,
          adapter_id TEXT,
          candidate_index INTEGER NOT NULL,
          prompt_snapshot TEXT NOT NULL,
          prompt_hash TEXT NOT NULL,
          output_text TEXT NOT NULL,
          params_json TEXT NOT NULL,
          output_token_count INTEGER,
          selected INTEGER NOT NULL DEFAULT 0,
          rejected INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          FOREIGN KEY(turn_id) REFERENCES turns(id),
          FOREIGN KEY(conversation_id) REFERENCES conversations(id),
          FOREIGN KEY(plot_id) REFERENCES plots(id),
          FOREIGN KEY(character_id) REFERENCES characters(id),
          FOREIGN KEY(user_profile_id) REFERENCES user_profiles(id)
        );
        CREATE TABLE IF NOT EXISTS user_actions (
          id TEXT PRIMARY KEY,
          conversation_id TEXT NOT NULL,
          turn_id TEXT,
          generation_id TEXT,
          action_type TEXT NOT NULL,
          payload_json TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(conversation_id) REFERENCES conversations(id)
        );
        CREATE TABLE IF NOT EXISTS generation_edits (
          id TEXT PRIMARY KEY,
          generation_id TEXT NOT NULL,
          original_text TEXT NOT NULL,
          edited_text TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(generation_id) REFERENCES generations(id)
        );
        """
    )
    conn.commit()


def load_resources(conn, root=ROOT):
    return import_content_catalog(conn, root)


def rows(conn, table, item_id=None):
    columns = select_cols(table)
    if item_id:
        row = conn.execute(f"SELECT {columns} FROM {table} WHERE id=?", (item_id,)).fetchone()
        return dict(row) if row else None
    return [dict(r) for r in conn.execute(f"SELECT {columns} FROM {table} ORDER BY id").fetchall()]
