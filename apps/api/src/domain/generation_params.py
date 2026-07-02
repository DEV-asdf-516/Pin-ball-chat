from dataclasses import dataclass


@dataclass
class GenerationParams:
    model: str = "local-stub"
    adapter_id: str | None = None
    num_predict: int | None = None
    num_ctx: int | None = None
    compact_prompt: bool = True
    provider_name: str | None = None
