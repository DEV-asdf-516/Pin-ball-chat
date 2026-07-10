import sqlite3

from core.db import Bind, ReadQuery, find_all, find_one
from core.errors import get_or_raise
from domain.turns.specs import GENERATIONS, TURNS


def list_turn_generations(conn: sqlite3.Connection, turn_id: str) -> dict:
    turn_row: dict | None = find_one(conn, ReadQuery.by_id(TURNS, turn_id))
    turn: dict = get_or_raise(turn_row, "turn not found")

    rows: list[dict] = find_all(conn, ReadQuery(GENERATIONS, where=Bind({"turn_id": turn_id}), order_by="candidate_index"))

    return {
        "turnId": turn_id,
        "selectedGenerationId": turn["selected_generation_id"],
        "generations": [
            {
                "generationId": r["id"],
                "content": r["output_text"],
                "selected": bool(r["selected"]),
                "candidateIndex": r["candidate_index"],
            }
            for r in rows
        ],
    }
