import json
import os
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("DB_PATH", ROOT / "data" / "pinballchat.sqlite"))


def classify_strength(turn):
    if turn["regenerate_count"] >= 3:
        return "strong"
    if turn["regenerate_count"] == 2:
        return "medium"
    return "weak"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    turns = conn.execute("SELECT * FROM turns WHERE selected_generation_id IS NOT NULL").fetchall()
    for turn in turns:
        selected = conn.execute("SELECT * FROM generations WHERE id=?", (turn["selected_generation_id"],)).fetchone()
        if not selected:
            continue
        rejected_rows = conn.execute(
            "SELECT * FROM generations WHERE turn_id=? AND rejected=1 AND id<>?",
            (turn["id"], selected["id"]),
        ).fetchall()
        for rejected in rejected_rows:
            print(json.dumps({
                "prompt": rejected["prompt_snapshot"],
                "chosen": selected["output_text"],
                "rejected": rejected["output_text"],
                "metadata": {
                    "plot_id": selected["plot_id"],
                    "character_id": selected["character_id"],
                    "user_profile_id": selected["user_profile_id"],
                    "conversation_id": selected["conversation_id"],
                    "turn_id": turn["id"],
                    "regenerate_count": turn["regenerate_count"],
                    "strength": classify_strength(turn),
                },
            }, ensure_ascii=False))


if __name__ == "__main__":
    main()
