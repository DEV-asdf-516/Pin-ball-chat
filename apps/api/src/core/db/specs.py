from dataclasses import dataclass, field


@dataclass(frozen=True)
class TableSpec:
    """table명, insert/upsert 컬럼 목록, upsert 충돌키를 하나로 묶는다. 도메인별 specs.py가 이 클래스로 테이블 스펙을 선언하고, db 함수들은 전부 이 spec 하나만 받는다."""
    table: str
    columns: tuple[str, ...]
    conflict_col: str = field(default="id", kw_only=True)


@dataclass(frozen=True)
class RawSQL:
    """update()의 set dict에서, 바인딩 값이 아니라 기존 컬럼값을 참조하는 SQL 표현식(예: regenerate_count+1)임을 표시한다."""
    sql: str


@dataclass(frozen=True)
class Not:
    """update()의 where dict에서 <> 비교임을 표시한다 (기본은 =)."""
    value: object
