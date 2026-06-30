from domain.content_upsert import upsert_content_item
from util.content_file import load_content_file


def import_content_catalog(conn, root):
    errors = []
    specs = [
        ("characters", "characters", "character"),
        ("user_profiles", "user_profiles", "user_profile"),
        ("plots", "plots", "plot"),
        ("preferences", "preference_profiles", "preference"),
    ]
    loaded = {kind: set() for _, _, kind in specs}
    pending_plots = []
    for dirname, table, kind in specs:
        for path in sorted((root / dirname).glob("*")):
            if path.suffix not in (".json", ".md"):
                continue
            try:
                data, source_text, source_format = load_content_file(path)
                if data.get("type", kind) != kind:
                    raise ValueError(f"type must be {kind}")
                row_id = data["id"]
                if kind == "plot":
                    pending_plots.append((data, source_text, source_format))
                    continue
                if kind == "preference":
                    upsert_content_item(conn, table, row_id, data.get("scope", "global"), data, source_format, source_text, (data.get("scopeId"),))
                else:
                    upsert_content_item(conn, table, row_id, data.get("name") or row_id, data, source_format, source_text)
                loaded[kind].add(row_id)
            except Exception as exc:
                errors.append(f"{path}: {exc}")
    for data, source_text, source_format in pending_plots:
        try:
            char_id = data["characterId"]
            user_id = data["userProfileId"]
            if char_id not in loaded["character"] and not conn.execute("SELECT 1 FROM characters WHERE id=?", (char_id,)).fetchone():
                raise ValueError(f"unknown characterId {char_id}")
            if user_id not in loaded["user_profile"] and not conn.execute("SELECT 1 FROM user_profiles WHERE id=?", (user_id,)).fetchone():
                raise ValueError(f"unknown userProfileId {user_id}")
            upsert_content_item(conn, "plots", data["id"], data.get("title") or data["id"], data, source_format, source_text, (char_id, user_id))
            loaded["plot"].add(data["id"])
        except Exception as exc:
            errors.append(f"plot {data.get('id', '<missing>')}: {exc}")
    conn.commit()
    return errors
