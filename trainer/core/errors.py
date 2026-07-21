# Exception types raised from the domain layer, mapped to HTTP status by api/errors.py.

from __future__ import annotations


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class AppDbUnavailable(Exception):
    pass


def get_or_raise(value, message: str):
    # apps/api/src/core/errors.py의 get_or_raise와 동일 — 존재 여부 체크 전용.
    if not value:
        raise NotFound(message)
    return value
