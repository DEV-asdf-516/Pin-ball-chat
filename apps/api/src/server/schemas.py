from pydantic import BaseModel, ConfigDict, Field

from domain.services import GenerationParams


class CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


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
