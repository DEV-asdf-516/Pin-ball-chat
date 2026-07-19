from dataclasses import dataclass, field
from enum import StrEnum
from typing import Self

# ReadQuery/WriteQuery의 where(Bind) 값은 bare(=Eq와 동일)가 기본, Ne/Gt/Lt/In/NotIn으로 감싸면 각각 <>/>/</IN/NOT IN 비교로 바뀐다.


@dataclass(frozen=True)
class TableSpec:
    # table명, insert/upsert 컬럼 목록, upsert 충돌키를 하나로 묶는다. 도메인별 specs.py가 이 클래스로 테이블 스펙을 선언하고, db 함수들은 전부 이 spec 하나만 받는다.
    table: str
    columns: tuple[str, ...]
    conflict_col: str = field(default="id", kw_only=True)


@dataclass(frozen=True)
class RawSQL:
    # RAW SQL 텍스트임을 표시한다 — 바인딩 값이 아니라 SQL 코드 그대로 쓰인다.
    # (예: WriteQuery.set/In.values, fetch_one/fetch_all/CursorQuery.query에 넘기는 SQL 문자열).
    sql: str


class CursorClause(StrEnum):
    # CursorQuery.clause()가 만드는 조건절 접두사. 쿼리의 첫 조건이면 WHERE, 이미 다른 조건이 있으면 AND.
    WHERE = "WHERE"
    AND = "AND"


@dataclass(frozen=True)
class CursorQuery:
    # paginate()에 넘기는 raw SQL + 파라미터 묶음.
    # query는 rowid DESC로 정렬돼야 하고 rowid를 SELECT에 포함해야 한다.
    # query의 LIMIT 자리는 :limit로 남겨두면 된다 — to_dict()가 limit+1을 자동으로 채워 넣는다.
    query: RawSQL
    params: dict
    limit: int

    def to_dict(self) -> dict:
        return {**self.params, "limit": self.limit + 1}

    @staticmethod
    def clause(column: str, before: int | None, prefix: CursorClause = CursorClause.WHERE) -> str:
        # before가 있을 때만 '{prefix} {column}<:before' 조건을 만든다. 이미 다른 조건이 있는 쿼리면 prefix=Clause.AND로 넘긴다.
        return f"{prefix} {column}<:before" if before is not None else ""


@dataclass(frozen=True)
class Bind:
    # column: value 매핑에 이름을 붙인 것
    # ReadQuery.where/WriteQuery.set·where, insert/upsert의 values, In/NotIn.params가 쓴다.
    # 값 해석은 쓰이는 자리에 따라 다르다:
    # - WHERE: Eq/Ne/Gt/Lt/In/NotIn이면 해당 비교(bare value는 Eq와 동일)
    # - SET: RawSQL이면 SQL 그대로/그 외엔 =
    # insert/upsert의 values는 항상 단순 바인딩이다.
    values: dict = field(default_factory=dict)

    def items(self):
        return self.values.items()

    def __bool__(self) -> bool:
        return bool(self.values)

    def __len__(self) -> int:
        return len(self.values)


@dataclass(frozen=True)
class _Query:
    # ReadQuery/WriteQuery 공통 베이스. by_id()만 공유하고, where/set 필드는 positional 순서 보존을 위해 각 서브클래스가 직접 선언한다.
    spec: TableSpec

    @classmethod
    def by_id(cls, spec: TableSpec, value, column: str | None = None) -> Self:
        return cls(spec, where=Bind({(column or spec.conflict_col): value}))


class Direction(StrEnum):
    # OrderBy.direction — ASC가 기본이라 렌더링 시(OrderBy.__str__) 생략된다.
    ASC = "ASC"
    DESC = "DESC"


@dataclass(frozen=True)
class OrderBy:
    # ReadQuery.order_by에 넘기는 정렬 컬럼 하나. 튜플로 여러 개 이어붙이면 다중 컬럼 정렬이 된다.
    column: str
    direction: Direction = Direction.ASC

    def __str__(self) -> str:
        return self.column if self.direction is Direction.ASC else f"{self.column} {self.direction}"


@dataclass(frozen=True)
class ReadQuery(_Query):
    # find_one/find_all/exists에 넘기는 조회 조건 묶음.
    where: Bind = field(default_factory=Bind)
    order_by: tuple[OrderBy, ...] = (OrderBy("id"),)


@dataclass(frozen=True)
class WriteQuery(_Query):
    # update()/delete()에 넘기는 SET + WHERE 묶음(CUD 공용). delete()는 set을 안 쓴다.
    # set 값이 RawSQL이면 바인딩 없이 그 SQL을 그대로 쓴다.
    set: Bind = field(default_factory=Bind)
    where: Bind = field(default_factory=Bind)


@dataclass(frozen=True)
class Eq:
    # WHERE 조건에서 = 비교임을 표시한다. 값을 안 감싸도(bare value) 기본으로 이 취급을 받는다 — 명시하고 싶을 때만 쓰면 된다.
    value: object


@dataclass(frozen=True)
class Ne:
    # WHERE 조건에서 <> 비교임을 표시한다 (기본은 =).
    value: object


@dataclass(frozen=True)
class Gt:
    # WHERE 조건에서 > 비교(부등호)임을 표시한다.
    value: object


@dataclass(frozen=True)
class Lt:
    # WHERE 조건에서 < 비교(부등호)임을 표시한다.
    value: object


@dataclass(frozen=True)
class In:
    # WHERE 조건에서 IN 비교임을 표시한다.
    # values가 list/tuple이면 각 원소를 개별 바인딩한다.
    # values가 RawSQL이면(주로 subquery) 그 SQL을 그대로 IN절에 쓰고, params로 그 subquery가 필요로 하는 바인딩을 함께 넘긴다.
    values: object
    params: Bind = field(default_factory=Bind)


@dataclass(frozen=True)
class NotIn:
    # WHERE 조건에서 NOT IN 비교임을 표시한다. values/params 규칙은 In과 동일.
    values: object
    params: Bind = field(default_factory=Bind)
