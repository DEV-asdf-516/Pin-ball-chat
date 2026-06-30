import json
import os
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("DB_PATH", ROOT / "data" / "pinballchat.sqlite"))


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT e.edited_text, g.prompt_snapshot, g.plot_id, g.character_id, g.user_profile_id,
               m.content AS user_message
        FROM generation_edits e
        JOIN generations g ON g.id = e.generation_id
        JOIN turns t ON t.id = g.turn_id
        JOIN messages m ON m.id = t.user_message_id
        """
    ).fetchall()
    for row in rows:
        print(json.dumps({
            "messages": [
                {"role": "system", "content": row["prompt_snapshot"]},
                {"role": "user", "content": row["user_message"]},
                {"role": "assistant", "content": row["edited_text"]},
            ],
            "metadata": {
                "plot_id": row["plot_id"],
                "character_id": row["character_id"],
                "user_profile_id": row["user_profile_id"],
                "source": "generation_edit",
            },
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
