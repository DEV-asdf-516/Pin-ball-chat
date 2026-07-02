from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from domain.generation_params import GenerationParams


class CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ContentBody(CamelModel):
    """character/user_profile/plot/preference create/update body의 공통 베이스.

    content 파일은 정의 안 된 필드도 그대로 저장하는 라운드트립 계약이 있어서
    (`write_content_file`이 dict를 통째로 파일에 쓴다), 알려지지 않은 필드를
    버리지 않도록 `extra="allow"`를 쓴다.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True, exclude_none=True)


class CharacterCreateRequest(ContentBody):
    id: str
    type: str = "character"
    source_text: str = Field(alias="sourceText")
    name: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")


class CharacterUpdateRequest(ContentBody):
    type: str = "character"
    source_text: str = Field(alias="sourceText")
    name: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")


class UserProfileCreateRequest(ContentBody):
    id: str
    type: str = "user_profile"
    source_text: str = Field(alias="sourceText")
    name: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")


class UserProfileUpdateRequest(ContentBody):
    type: str = "user_profile"
    source_text: str = Field(alias="sourceText")
    name: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")


class PlotCreateRequest(ContentBody):
    id: str
    type: str = "plot"
    character_id: str = Field(alias="characterId")
    user_profile_id: str = Field(alias="userProfileId")
    source_text: str = Field(alias="sourceText")
    title: str | None = None
    genre: list[str] = Field(default_factory=list)


class PlotUpdateRequest(ContentBody):
    type: str = "plot"
    character_id: str = Field(alias="characterId")
    user_profile_id: str = Field(alias="userProfileId")
    source_text: str = Field(alias="sourceText")
    title: str | None = None
    genre: list[str] = Field(default_factory=list)


class PreferenceCreateRequest(ContentBody):
    id: str
    type: str = "preference"
    profile: dict[str, Any]
    scope: str = "global"
    scope_id: str | None = Field(default=None, alias="scopeId")
    ooc: list[str] = Field(default_factory=list)


class PreferenceUpdateRequest(ContentBody):
    type: str = "preference"
    profile: dict[str, Any]
    scope: str = "global"
    scope_id: str | None = Field(default=None, alias="scopeId")
    ooc: list[str] = Field(default_factory=list)


class GenerationParamsRequest(CamelModel):
    model: str = "local-stub"
    provider: str | None = None
    adapter_id: str | None = Field(default=None, alias="adapterId")
    max_tokens: int | None = Field(default=None, alias="maxTokens")
    num_predict: int | None = Field(default=None, alias="numPredict")
    num_ctx: int | None = Field(default=None, alias="numCtx")
    compact_prompt: bool = Field(default=True, alias="compactPrompt")

    def to_params(self) -> GenerationParams:
        return GenerationParams(
            model=self.model,
            adapter_id=self.adapter_id,
            num_predict=self.num_predict if self.num_predict is not None else self.max_tokens,
            num_ctx=self.num_ctx,
            compact_prompt=self.compact_prompt,
            provider_name=self.provider,
        )


class CreateConversationRequest(CamelModel):
    plot_id: str = Field(alias="plotId")
    title: str | None = None


class ChatRequest(GenerationParamsRequest):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "conversationId": "conv_xxx",
                "message": "",
                "model": "qwen3:4b",
                "provider": "ollama",
                "adapterId": None,
                "maxTokens": 160,
                "numCtx": 1024,
                "compactPrompt": True,
            }
        },
    )
    conversation_id: str = Field(alias="conversationId")
    message: str


class RegenerateRequest(GenerationParamsRequest):
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "model": "qwen3:4b",
                "provider": "ollama",
                "adapterId": None,
                "maxTokens": 160,
                "numCtx": 1024,
                "compactPrompt": True,
            }
        },
    )


class EditGenerationRequest(CamelModel):
    edited_text: str = Field(alias="editedText")


class HealthResponse(BaseModel):
    ok: bool


class ConversationResponse(BaseModel):
    conversationId: str
    plotId: str


class ChatResponse(BaseModel):
    generationId: str
    turnId: str
    output: str
    candidateIndex: int


class SelectResponse(BaseModel):
    generationId: str
    selected: bool


class EditResponse(BaseModel):
    generationId: str
    edited: bool
