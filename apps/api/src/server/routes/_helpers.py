from fastapi import HTTPException

from core.db import connect, init_db, rows
from server.errors import business


def _with_db(call):
    with connect() as conn:
        init_db(conn)
        return call(conn)


def db_business(call):
    return business(lambda: _with_db(call))


def one(table, item_id):
    row = _with_db(lambda conn: rows(conn, table, item_id))
    if not row:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "not found"})
    return row
