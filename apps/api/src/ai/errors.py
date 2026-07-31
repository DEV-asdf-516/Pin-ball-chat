from enum import Enum
from functools import partial
from typing import Callable

from ai.specs import ProviderName
from util.safe_util import get_safe_list


class ProviderErrorCode(str, Enum):
    PROVIDER_AUTH_REQUIRED = "provider_auth_required"
    PROVIDER_QUOTA_EXHAUSTED = "provider_quota_exhausted"
    MODEL_UNAVAILABLE = "model_unavailable"
    PROVIDER_CONTRACT_VIOLATION = "provider_contract_violation"
    PROVIDER_BAD_GATEWAY = "provider_bad_gateway"
    PROVIDER_RUNTIME_INCOMPATIBLE = "provider_runtime_incompatible"
    PROVIDER_RUNTIME_CRASHED = "provider_runtime_crashed"
    PROVIDER_TIMEOUT = "provider_timeout"
    LOGIN_REQUIRED = "login_required"
    API_KEY_REQUIRED = "api_key_required"
    OLLAMA_URL_REQUIRED = "ollama_url_required"
    OLLAMA_UNAVAILABLE = "ollama_unavailable"
    RUNTIME_SETUP_REQUIRED = "runtime_setup_required"


class ProviderTimeoutError(Exception):
    def __init__(self, message: str, phase: str | None = None, provider: str | None = None):
        super().__init__(message)
        self.phase = phase
        self.provider = provider


class ProviderBadGatewayError(Exception):
    def __init__(self, message: str, provider: str | None = None):
        super().__init__(message)
        self.provider = provider


class ProviderRuntimeError(Exception):
    def __init__(self, code: ProviderErrorCode | str, message: str, provider: str, retryable: bool = False, phase: str | None = None):
        super().__init__(message)
        self.code = code
        self.provider = provider
        self.retryable = retryable
        self.phase = phase


class EmptyOutputError(Exception):
    pass


class ProviderConnectionBusyError(Exception):
    pass


def runtime_error_factory(provider_name: str) -> Callable[..., ProviderRuntimeError]:
    return partial(ProviderRuntimeError, provider=provider_name)


def timeout_error_factory(provider_name: str) -> Callable[..., ProviderTimeoutError]:
    return partial(ProviderTimeoutError, provider=provider_name)


ProviderError = ProviderTimeoutError | ProviderRuntimeError | ProviderBadGatewayError


def provider_error_payload(exc: ProviderError, *, fallback_provider: str | None = None) -> dict:
    if isinstance(exc, ProviderRuntimeError):
        code = exc.code
        retryable = exc.retryable
        phase = exc.phase
    elif isinstance(exc, ProviderTimeoutError):
        code = ProviderErrorCode.PROVIDER_TIMEOUT
        retryable = True
        phase = exc.phase
    else:
        code = ProviderErrorCode.PROVIDER_BAD_GATEWAY
        retryable = True
        phase = None

    payload = {
        "error": code,
        "code": code,
        "provider": exc.provider or fallback_provider,
        "message": str(exc),
        "retryable": retryable,
    }

    if phase:
        payload["phase"] = phase

    return payload


def provider_failure_code(exc: Exception) -> ProviderErrorCode | str:
    if isinstance(exc, ProviderTimeoutError):
        return ProviderErrorCode.PROVIDER_TIMEOUT
    if isinstance(exc, ProviderRuntimeError):
        return exc.code
    return ProviderErrorCode.PROVIDER_BAD_GATEWAY


class ErrorRule:
    def __init__(self, codes: set[str], code: ProviderErrorCode, message: str, retryable: bool = False):
        self.codes = codes
        self.code = code
        self.message = message
        self.retryable = retryable


_PROVIDER_ERROR_RULES: dict[ProviderName, list[ErrorRule]] = {
    ProviderName.GEMINI: [
        ErrorRule(
            {"API_KEY_SERVICE_BLOCKED"},
            ProviderErrorCode.PROVIDER_AUTH_REQUIRED,
            "Gemini authorization key migration is required"
        ),
    ],
}

_COMMON_PROVIDER_ERROR_RULES: list[ErrorRule] = [
    ErrorRule(
        {"rate_limit_error", "rate_limit_exceeded", "insufficient_quota", "quota_exhausted", "RESOURCE_EXHAUSTED", "429"},
        ProviderErrorCode.PROVIDER_QUOTA_EXHAUSTED,
        "{provider} quota is exhausted",
        retryable=True
    ),
    ErrorRule(
        {"model_not_found", "model_unavailable", "not_found_error", "NOT_FOUND", "404"},
        ProviderErrorCode.MODEL_UNAVAILABLE,
        "{provider} model is unavailable"
    ),
    ErrorRule(
        {"authentication_error", "invalid_api_key", "unauthorized", "UNAUTHENTICATED", "PERMISSION_DENIED", "API_KEY_INVALID", "401", "403"},
        ProviderErrorCode.PROVIDER_AUTH_REQUIRED,
        "{provider} authentication is required"
    ),
]

_ALL_ERROR_RULES: dict[ProviderName, list[ErrorRule]] = {
    provider: rules + _COMMON_PROVIDER_ERROR_RULES for provider, rules in _PROVIDER_ERROR_RULES.items()
}


def match_error_rule(rules: list[ErrorRule], codes: set[str]) -> ErrorRule | None:
    for rule in rules:
        if codes & rule.codes:
            return rule
    return None


def classify_provider_error(provider_name: str, error: dict) -> ProviderRuntimeError | ProviderBadGatewayError:
    details: list = get_safe_list(error, "details")
    reasons: list[str] = [str(item.get("reason")) for item in details if isinstance(item, dict) and item.get("reason")]
    
    codes: set[str] = {
        str(value) for value in
        (error.get("type"), error.get("status"), error.get("code"), *reasons)
        if value is not None
    }

    rule = match_error_rule(_ALL_ERROR_RULES.get(provider_name, _COMMON_PROVIDER_ERROR_RULES), codes)
    
    if rule:
        return ProviderRuntimeError(
            rule.code, 
            rule.message.format(provider=provider_name), 
            provider_name, 
            retryable=rule.retryable
        )
    
    return ProviderBadGatewayError(f"{provider_name} returned an upstream error", provider_name)
