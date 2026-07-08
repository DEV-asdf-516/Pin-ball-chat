from dataclasses import dataclass, field, fields
from enum import StrEnum

from core.db import TableSpec
from util.string_util import camel_to_snake


class CatalogKind(StrEnum):
    CHARACTER = "character"
    USER_PROFILE = "user_profile"
    PLOT = "plot"
    PREFERENCE = "preference"


@dataclass(frozen=True)
class CatalogSpec(TableSpec):
    dirname: str
    kind: CatalogKind
    source_format: str


CATALOG_SPECS = [
    CatalogSpec(
        dirname="characters",
        table="characters",
        kind=CatalogKind.CHARACTER,
        source_format="md",
        columns=("id", "name", "profile_json", "source_format", "source_text", "created_at", "updated_at"),
    ),
    CatalogSpec(
        dirname="user_profiles",
        table="user_profiles",
        kind=CatalogKind.USER_PROFILE,
        source_format="md",
        columns=("id", "name", "profile_json", "source_format", "source_text", "created_at", "updated_at"),
    ),
    CatalogSpec(
        dirname="plots",
        table="plots",
        kind=CatalogKind.PLOT,
        source_format="md",
        columns=("id", "title", "character_id", "user_profile_id", "plot_json", "source_format", "source_text", "created_at", "updated_at"),
    ),
    CatalogSpec(
        dirname="preferences",
        table="preference_profiles",
        kind=CatalogKind.PREFERENCE,
        source_format="json",
        columns=("id", "scope", "scope_id", "profile_json", "source_format", "source_text", "created_at", "updated_at"),
    ),
]

KIND_DIR = {spec.kind: spec.dirname for spec in CATALOG_SPECS}
SPEC_BY_KIND: dict[CatalogKind, CatalogSpec] = {spec.kind: spec for spec in CATALOG_SPECS}

# 어떤 kind를 지우려 할 때, 어떤 kind의 어떤 컬럼이 그 id를 참조하고 있는지 확인해야 하는지 선언한다.
# kind가 늘어나도 여기 항목만 추가하면 되고, delete_catalog_item의 분기는 늘어나지 않는다.
REFERENCED_BY: dict[CatalogKind, tuple[tuple[CatalogKind, str], ...]] = {
    CatalogKind.CHARACTER: ((CatalogKind.PLOT, "character_id"),),
    CatalogKind.USER_PROFILE: ((CatalogKind.PLOT, "user_profile_id"),),
}

# 이 kind의 payload가 다른 kind를 참조하는 필드들을 선언한다: (참조 대상 kind, payload attribute명).
# writer._validate_references와 importer의 의존성 로딩 순서가 이 하나의 선언을 공유한다.
FORWARD_REFS: dict[CatalogKind, tuple[tuple[CatalogKind, str], ...]] = {
    CatalogKind.PLOT: (
        (CatalogKind.CHARACTER, "character_id"),
        (CatalogKind.USER_PROFILE, "user_profile_id"),
    ),
}


@dataclass
class CatalogPayload:
    id: str
    type: str

    @property
    def columns(self) -> dict:
        """upsert 시 id 외에 이 payload가 채우는 {컬럼명: 값} (라벨, 참조키 등)."""
        return {}

    @property
    def json_column(self) -> str:
        """원본 dict 전체(catalog.data)를 JSON으로 직렬화해 넣을 컬럼명."""
        return "profile_json"


@dataclass
class CharacterData(CatalogPayload):
    source_text: str
    name: str | None = None
    display_name: str | None = None

    @property
    def columns(self) -> dict:
        return {"name": self.name or self.id}


@dataclass
class UserProfileData(CatalogPayload):
    source_text: str
    name: str | None = None
    display_name: str | None = None

    @property
    def columns(self) -> dict:
        return {"name": self.name or self.id}


@dataclass
class PlotData(CatalogPayload):
    character_id: str
    user_profile_id: str
    source_text: str
    title: str | None = None
    genre: list[str] = field(default_factory=list)

    @property
    def columns(self) -> dict:
        return {"title": self.title or self.id, "character_id": self.character_id, "user_profile_id": self.user_profile_id}

    @property
    def json_column(self) -> str:
        return "plot_json"


@dataclass
class PreferenceData(CatalogPayload):
    profile: dict
    scope: str = "global"
    scope_id: str | None = None
    ooc: list[str] = field(default_factory=list)

    @property
    def columns(self) -> dict:
        return {"scope": self.scope, "scope_id": self.scope_id}


PAYLOAD_CLASS: dict[CatalogKind, type[CatalogPayload]] = {
    CatalogKind.CHARACTER: CharacterData,
    CatalogKind.USER_PROFILE: UserProfileData,
    CatalogKind.PLOT: PlotData,
    CatalogKind.PREFERENCE: PreferenceData,
}


def parse_catalog_data(kind: CatalogKind, data: dict) -> CatalogPayload:
    """data는 콘텐츠 파일/API 요청 바디에서 온 camelCase wire format dict다.
    CatalogPayload 필드는 snake_case라서 매칭 전에 키를 변환한다."""
    cls: type[CatalogPayload] = PAYLOAD_CLASS[kind]
    
    known_fields: set[str] = {f.name for f in fields(cls)}
    snake_data: dict = {camel_to_snake(k): v for k, v in data.items()}
    
    return cls(**{k: v for k, v in snake_data.items() if k in known_fields})
