import json

from util.time_util import utc_now_string


CONTENT_COLUMNS = {
    "characters": "id,name,profile_json,source_format,source_text,created_at,updated_at",
    "user_profiles": "id,name,profile_json,source_format,source_text,created_at,updated_at",
    "plots": "id,title,character_id,user_profile_id,plot_json,source_format,source_text,created_at,updated_at",
    "preference_profiles": "id,scope,scope_id,profile_json,source_format,source_text,created_at,updated_at",
}


def upsert_content_item(conn, table, row_id, display_name, payload, source_format, source_text, extra=()):
    ts = utc_now_string()
    cols = CONTENT_COLUMNS[table]
    values = (row_id, display_name, *extra, json.dumps(payload, ensure_ascii=False), source_format, source_text, ts, ts)
    placeholders = ",".join("?" for _ in values)
    update_cols = [c for c in cols.split(",") if c not in ("id", "created_at")]
    updates = ",".join(f"{c}=excluded.{c}" for c in update_cols)
    conn.execute(
        f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        values,
    )
