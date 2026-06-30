from ai.provider import GenerateRequest


class LocalStubProvider:
    name = "local-stub"
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def generate(self, req: GenerateRequest):
        text = f"{req.user_message} 테스트 메시지 생성이야."
        return text, {"provider": self.name, "fallbackApplied": False}

    def stream(self, _req: GenerateRequest):
        text = "테스트 응답이야. 지금은 local-stub으로 대답하고 있어."
        for token in text.split(" "):
            yield token + " "
