import sqlite3
from typing import Annotated

from fastapi import Depends

from core.db import connect, init_db


def get_db_conn():
    with connect() as conn:
        init_db(conn)
        yield conn


DbConn = Annotated[sqlite3.Connection, Depends(get_db_conn)]
