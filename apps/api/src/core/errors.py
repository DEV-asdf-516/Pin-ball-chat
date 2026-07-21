class BadRequest(Exception):
    pass


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def get_or_raise(value, message: str):
    if not value:
        raise NotFound(message)
    return value


def ensure(condition, message: str) -> None:
    if not condition:
        raise NotFound(message)
