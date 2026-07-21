# FastAPI dependency that opens one trainer DB connection per request.

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import Depends

from ..core.db import connect


def get_db_conn():
    with connect() as conn:
        yield conn


DbConn = Annotated[sqlite3.Connection, Depends(get_db_conn)]
