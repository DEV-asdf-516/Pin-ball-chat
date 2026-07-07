from dataclasses import dataclass


@dataclass
class GenerateRequest:
    prompt: str
    user_message: str
    model: str
    candidate_index: int
    num_predict: int | None = None
    num_ctx: int | None = None
    stream: bool = False


@dataclass
class GenerateResponse:
    text: str
    provider: str
    fallback_applied: bool = False
