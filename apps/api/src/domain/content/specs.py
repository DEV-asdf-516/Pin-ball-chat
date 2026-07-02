from dataclasses import dataclass, field, fields
from enum import StrEnum


class ContentKind(StrEnum):
    CHARACTER = "character"
    USER_PROFILE = "user_profile"
    PLOT = "plot"
    PREFERENCE = "preference"


@dataclass(frozen=True)
class ContentSpec:
    dirname: str
    table: str
    kind: ContentKind
    columns: tuple[str, ...]


CONTENT_SPECS = [
    ContentSpec(
        dirname="characters",
        table="characters",
        kind=ContentKind.CHARACTER,
        columns=("id", "name", "profile_json", "source_format", "source_text", "created_at", "updated_at"),
    ),
    ContentSpec(
        dirname="user_profiles",
        table="user_profiles",
        kind=ContentKind.USER_PROFILE,
        columns=("id", "name", "profile_json", "source_format", "source_text", "created_at", "updated_at"),
    ),
    ContentSpec(
        dirname="plots",
        table="plots",
        kind=ContentKind.PLOT,
        columns=("id", "title", "character_id", "user_profile_id", "plot_json", "source_format", "source_text", "created_at", "updated_at"),
    ),
    ContentSpec(
        dirname="preferences",
        table="preference_profiles",
        kind=ContentKind.PREFERENCE,
        columns=("id", "scope", "scope_id", "profile_json", "source_format", "source_text", "created_at", "updated_at"),
    ),
]

KIND_DIR = {spec.kind: spec.dirname for spec in CONTENT_SPECS}
KIND_TABLE = {spec.kind: spec.table for spec in CONTENT_SPECS}
TABLE_COLUMNS = {spec.table: spec.columns for spec in CONTENT_SPECS}


@dataclass
class ContentPayload:
    id: str
    type: str

    @property
    def label(self) -> str:
        """DB의 name/title/scope 컬럼에 들어갈 사람이 읽는 라벨."""
        return self.id

    @property
    def extra_columns(self) -> tuple:
        """upsert 시 name/title 다음에 추가로 필요한 컬럼 값들 (참조키 등)."""
        return ()


@dataclass
class CharacterData(ContentPayload):
    sourceText: str
    name: str | None = None
    displayName: str | None = None

    @property
    def label(self) -> str:
        return self.name or self.id


@dataclass
class UserProfileData(ContentPayload):
    sourceText: str
    name: str | None = None
    displayName: str | None = None

    @property
    def label(self) -> str:
        return self.name or self.id


@dataclass
class PlotData(ContentPayload):
    characterId: str
    userProfileId: str
    sourceText: str
    title: str | None = None
    genre: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.title or self.id

    @property
    def extra_columns(self) -> tuple:
        return (self.characterId, self.userProfileId)


@dataclass
class PreferenceData(ContentPayload):
    profile: dict
    scope: str = "global"
    scopeId: str | None = None
    ooc: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.scope

    @property
    def extra_columns(self) -> tuple:
        return (self.scopeId,)


PAYLOAD_CLASS: dict[ContentKind, type[ContentPayload]] = {
    ContentKind.CHARACTER: CharacterData,
    ContentKind.USER_PROFILE: UserProfileData,
    ContentKind.PLOT: PlotData,
    ContentKind.PREFERENCE: PreferenceData,
}


def parse_content_data(kind: ContentKind, data: dict) -> ContentPayload:
    cls: type[ContentPayload] = PAYLOAD_CLASS[kind]
    known_fields: set[str] = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known_fields})
