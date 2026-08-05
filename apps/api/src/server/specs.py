from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from domain.specs import GenerationParams


class CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class CursorPageResponse(BaseModel):
    nextCursor: str | None = None
    hasMore: bool


class CatalogBody(CamelModel):
    # character/user_profile/plot/preference create/update body의 공통 베이스.
    # content 파일은 정의 안 된 필드도 그대로 저장하는 라운드트립 계약이 있어서
    # (`write_catalog_file`이 dict를 통째로 파일에 쓴다), 알려지지 않은 필드를
    # 버리지 않도록 `extra="allow"`를 쓴다.

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True, exclude_none=True)


class CharacterCreateRequest(CatalogBody):
    id: str
    type: str = "character"
    plot_id: str = Field(alias="plotId")
    sort_order: int = Field(default=0, alias="sortOrder")
    source_text: str = Field(alias="sourceText")
    name: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")


class CharacterUpdateRequest(CatalogBody):
    type: str = "character"
    plot_id: str | None = Field(default=None, alias="plotId")
    sort_order: int | None = Field(default=None, alias="sortOrder")
    source_text: str = Field(alias="sourceText")
    name: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")


class PlotCharacterRequest(CatalogBody):
    id: str
    type: str = "character"
    source_text: str = Field(alias="sourceText")
    name: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")


class UserProfileCreateRequest(CatalogBody):
    id: str
    type: str = "user_profile"
    source_text: str = Field(alias="sourceText")
    name: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")


class UserProfileUpdateRequest(CatalogBody):
    type: str = "user_profile"
    source_text: str = Field(alias="sourceText")
    name: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")


class PlotCreateRequest(CatalogBody):
    id: str
    type: str = "plot"
    source_text: str = Field(alias="sourceText")
    title: str | None = None
    genre: list[str] = Field(default_factory=list)
    characters: list[PlotCharacterRequest] = Field(default_factory=list)


class PlotUpdateRequest(CatalogBody):
    type: str = "plot"
    source_text: str = Field(alias="sourceText")
    title: str | None = None
    genre: list[str] = Field(default_factory=list)
    # 캐릭터 추가·삭제·정렬은 개별 character CRUD로 처리한다. 이 필드는 구버전 클라이언트의
    # 요청을 파싱할 수 있게만 두고, update route에서 plot 데이터로 저장하지 않는다.
    characters: list[PlotCharacterRequest] | None = None


class PreferenceCreateRequest(CatalogBody):
    id: str
    type: str = "preference"
    profile: dict[str, Any]
    scope: str = "global"
    scope_id: str | None = Field(default=None, alias="scopeId")
    ooc: list[str] = Field(default_factory=list)


class PreferenceUpdateRequest(CatalogBody):
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
    num_predict: int | None = Field(default=1500, alias="numPredict")
    num_ctx: int | None = Field(default=8192, alias="numCtx")
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
    user_profile_id: str | None = Field(default=None, alias="userProfileId")
    title: str | None = None


class SetConversationUserProfileRequest(CamelModel):
    user_profile_id: str = Field(alias="userProfileId")


class SetConversationTitleRequest(CamelModel):
    title: str | None = None


class StartImportSessionRequest(CamelModel):
    room_id: str = Field(alias="roomId")
    expected_parts: int = Field(alias="expectedParts")
    expected_messages: int = Field(alias="expectedMessages")
    manifest: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True)


class UploadImportPartRequest(CamelModel):
    messages: list[dict[str, Any]]

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True)


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
                "numPredict": 1500,
                "numCtx": 8192,
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
                "numPredict": 1500,
                "numCtx": 8192,
                "compactPrompt": True,
            }
        },
    )


class EditGenerationRequest(CamelModel):
    edited_text: str = Field(alias="editedText")


class EditMessageRequest(CamelModel):
    edited_text: str = Field(alias="editedText")


class HealthResponse(BaseModel):
    ok: bool


class ModelsResponse(BaseModel):
    provider: str
    models: list[str]


class ProviderConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    provider: str
    status: str
    action_required: str | None = Field(default=None, alias="actionRequired")
    credential_type: str = Field(alias="credentialType")
    runtime_version: str | None = Field(default=None, alias="runtimeVersion")
    resolved_auth_mode: str | None = Field(default=None, alias="resolvedAuthMode")
    account_label: str | None = Field(default=None, alias="accountLabel")
    plan: str | None = None
    verification_url: str | None = Field(default=None, alias="verificationUrl")
    user_code: str | None = Field(default=None, alias="userCode")
    key_source: str | None = Field(default=None, alias="keySource")


class ProviderConnectionsResponse(BaseModel):
    providers: list[ProviderConnectionResponse]


class ProviderLoginResponse(BaseModel):
    provider: str
    verification_url: str | None = Field(default=None, alias="verificationUrl")
    user_code: str | None = Field(default=None, alias="userCode")
    status: str = "login_pending"


class ProviderLoginCodeRequest(CamelModel):
    code: str


class ProviderKeyRequest(CamelModel):
    key: str


class ConversationResponse(BaseModel):
    conversationId: str
    plotId: str
    userProfileId: str | None = None


class ConversationDeleteResponse(BaseModel):
    conversationId: str
    deleted: bool


class SelectResponse(BaseModel):
    generationId: str
    selected: bool


class GenerationCandidate(BaseModel):
    generationId: str
    content: str
    selected: bool
    candidateIndex: int


class TurnGenerationsResponse(BaseModel):
    turnId: str
    selectedGenerationId: str | None = None
    generations: list[GenerationCandidate]


class EditResponse(BaseModel):
    generationId: str
    edited: bool


class EditMessageResponse(BaseModel):
    messageId: str
    edited: bool


class MessageDeleteResponse(BaseModel):
    messageId: str
    turnId: str
    deleted: bool


class BulkDeleteMessagesRequest(CamelModel):
    message_ids: list[str] = Field(alias="messageIds")


class BulkDeleteMessagesResponse(BaseModel):
    messageIds: list[str]
    turnIds: list[str]
    deleted: bool


class CatalogItemResponse(BaseModel):
    id: str
    source_format: str
    source_text: str
    created_at: str
    updated_at: str


class CharacterResponse(CatalogItemResponse):
    name: str
    plot_id: str
    sort_order: int
    profile_json: str


class UserProfileResponse(CatalogItemResponse):
    name: str
    profile_json: str


class PlotResponse(CatalogItemResponse):
    title: str
    plot_json: str


class PreferenceResponse(CatalogItemResponse):
    scope: str
    scope_id: str | None = None
    profile_json: str


class CharactersPageResponse(CursorPageResponse):
    characters: list[CharacterResponse]


class UserProfilesPageResponse(CursorPageResponse):
    user_profiles: list[UserProfileResponse]


class PlotsPageResponse(CursorPageResponse):
    plots: list[PlotResponse]


class PreferenceProfilesPageResponse(CursorPageResponse):
    preference_profiles: list[PreferenceResponse]


class CatalogDeleteResponse(BaseModel):
    id: str
    deleted: bool


class ConversationDetailResponse(BaseModel):
    id: str
    plot_id: str
    user_profile_id: str | None = None
    title: str | None = None
    active_adapter_id: str | None = None
    created_at: str
    updated_at: str


class ConversationsPageResponse(CursorPageResponse):
    conversations: list[ConversationDetailResponse]


class MessageItem(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    turn_id: str | None = None
    generation_id: str | None = None
    created_at: str


class MessagesPageResponse(CursorPageResponse):
    messages: list[MessageItem]


class ConversationSettingsResponse(BaseModel):
    conversation_id: str
    provider: str | None = None
    model: str | None = None
    num_predict: int | None = None
    num_ctx: int | None = None
    compact_prompt: bool | None = None
    adapter_id: str | None = None
    created_at: str
    updated_at: str


class ImportSessionResponse(BaseModel):
    sessionId: str
    conversationId: str
    roomId: str
    expectedParts: int
    expectedMessages: int
    receivedParts: list[int]
    receivedMessages: int
    receivedBytes: int
    warningCount: int
    state: str
    createdAt: str
    lastActivityAt: str


class UploadImportPartResponse(ImportSessionResponse):
    partNumber: int
    warnings: list[str]


class CommitImportSessionResponse(BaseModel):
    sessionId: str
    conversationId: str
    turnCount: int
    messageCount: int
    warnings: list[str]


class DiscardImportSessionResponse(BaseModel):
    sessionId: str
    discarded: bool
