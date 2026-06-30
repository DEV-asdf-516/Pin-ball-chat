from dataclasses import dataclass


@dataclass
class GenerateRequest:
    prompt: str
    user_message: str
    model: str
    candidate_index: int
    num_predict: int | None = None
    num_ctx: int | None = None
