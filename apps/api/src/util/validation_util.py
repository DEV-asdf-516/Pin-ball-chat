from core.errors import BadRequest


def required_nonblank_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BadRequest(f"{field} must be a non-empty string")
    return value


def required_bounded_int(value: object, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise BadRequest(f"{field} must be an integer from {minimum} to {maximum}")
    return value
