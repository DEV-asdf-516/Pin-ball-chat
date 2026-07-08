from dataclasses import dataclass


@dataclass
class Message:
    role: str
    content: str


@dataclass
class GenerateRequest:
    system: str
    messages: list[Message]
    model: str
    candidate_index: int
    num_predict: int | None = None
    num_ctx: int | None = None
    stream: bool = False
