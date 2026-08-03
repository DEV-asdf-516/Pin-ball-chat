import logging
from enum import Enum
from pathlib import Path
from typing import Callable, NamedTuple

from ai.errors import ErrorRule, ProviderErrorCode, ProviderRuntimeError, match_error_rule, runtime_error_factory
from ai.specs import ProviderName
from util.safe_util import get_safe_dict, get_safe_str, has_str_field


log = logging.getLogger(__name__)

_runtime_error : Callable[..., ProviderRuntimeError] = runtime_error_factory(ProviderName.CLAUDE_CLI)


_EVENT_ERROR_RULES: list[ErrorRule] = [
    ErrorRule({"authentication_error", "authentication_failed", "auth_required", "invalid_api_key", "unauthorized", "permission_error"}, 
        ProviderErrorCode.PROVIDER_AUTH_REQUIRED, 
        "Claude login is required"
    ),
    ErrorRule({"rate_limit", "rate_limit_error", "quota_exhausted", "usage_limit", "usage_limit_reached", "credit_balance_too_low", "billing_error", "error_max_budget_usd"}, 
        ProviderErrorCode.PROVIDER_QUOTA_EXHAUSTED, 
        "Claude usage limit has been reached", 
        retryable=True
    ),
    ErrorRule({"not_found_error", "model_not_found", "model_unavailable", "model_access_denied"}, 
        ProviderErrorCode.MODEL_UNAVAILABLE, 
        "the selected Claude model is unavailable"
    ),
]


_USAGE_FIELDS: tuple = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)

class _EventStructureCheck(NamedTuple):
    predicate: Callable[[dict], bool]
    message: str


# 위에서 아래로 첫 매치가 이긴다 — 현행 if-체인의 검사 순서와 동일해야 한다.
_EVENT_STRUCTURE_CHECKS: list[_EventStructureCheck] = [
    _EventStructureCheck(lambda e: not has_str_field(e, "type"), "claude runtime emitted a malformed stream event"),
    _EventStructureCheck(
        lambda e: e.get("type") == "stream_event" \
            and (not isinstance(e.get("event"), dict) or not has_str_field(e["event"], "type")),
        "claude runtime emitted a malformed nested stream event",
    ),
    _EventStructureCheck(
        lambda e: _unwrap_stream_event(e).get("type") == "content_block_start" \
            and not isinstance(_unwrap_stream_event(e).get("content_block"), dict),
        "claude runtime emitted a malformed content block",
    ),
    _EventStructureCheck(
        lambda e: _unwrap_stream_event(e).get("type") == "error" \
            and not isinstance(_unwrap_stream_event(e).get("error"), dict),
        "claude runtime emitted a malformed error event",
    ),
    _EventStructureCheck(
        lambda e: e.get("type") in {"assistant", "user"} \
            and (not isinstance(e.get("message"), dict) or not isinstance(e.get("message").get("content"), list)),
        "claude runtime emitted a malformed message event",
    ),
]



def find_structure_violation(event: dict) -> str | None:
    return next((message for predicate, message in _EVENT_STRUCTURE_CHECKS if predicate(event)), None)


def _unwrap_stream_event(event: dict) -> dict:
    nested = event.get("event")
    return nested if event.get("type") == "stream_event" and isinstance(nested, dict) else event


def _classify_event_error(event: dict) -> ProviderRuntimeError | None:
    stream_event: dict = _unwrap_stream_event(event)
    raw_error = stream_event.get("error")

    error: dict = get_safe_dict(stream_event, "error")
    event_type: str = get_safe_str(stream_event, "type")

    is_error_result: bool = event.get("type") == "result" and event.get("is_error") is True

    error_type_or_code: str = get_safe_str(error, "type") or get_safe_str(error, "code")
    raw_error_str: str = raw_error if isinstance(raw_error, str) else ""
    result_subtype: str = event.get("subtype") if is_error_result else ""

    code: str = str(error_type_or_code or raw_error_str or result_subtype or "")

    if event_type != "error" and not is_error_result and not isinstance(raw_error, str):
        return None

    rule: ErrorRule | None = match_error_rule(_EVENT_ERROR_RULES, {code})

    if rule:
        return _runtime_error(rule.code, rule.message, retryable=rule.retryable)

    log.warning("claude runtime returned an unrecognized error: type=%s subtype=%s error=%s", event_type, result_subtype, error)

    if event_type == "error":
        return _runtime_error(ProviderErrorCode.PROVIDER_BAD_GATEWAY, "Claude runtime returned an upstream error", retryable=True)

    return _runtime_error(ProviderErrorCode.PROVIDER_BAD_GATEWAY, "Claude runtime returned an unsuccessful result", retryable=True)


def _extract_text_delta(event: dict) -> str:
    stream_event: dict = _unwrap_stream_event(event)

    if stream_event.get("type") != "content_block_delta":
        return ""

    delta: dict = stream_event.get("delta")

    if not isinstance(delta, dict):
        raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime emitted a malformed content delta")


    if delta.get("type") != "text_delta":
        return ""

    if not has_str_field(delta, "text"):
        raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime emitted a malformed text delta")

    return delta.get("text")



def _contains_prohibited_tool_use(event: dict) -> bool:
    stream_event: dict = _unwrap_stream_event(event)

    if stream_event.get("type") in {"tool_use", "tool_result", "tool", "tool_progress"}:
        return True

    if (
        stream_event.get("type") == "content_block_start"
        and get_safe_dict(stream_event, "content_block").get("type") in {"tool_use", "server_tool_use"}
    ):
        return True

    content: list = get_safe_dict(event, "message").get("content", [])

    part_types: set = {part.get("type") for part in content if isinstance(part, dict)}

    return bool(part_types & {"tool_use", "tool_result"})



def _parse_result_event(event: dict) -> tuple[str, dict[str, int]]:
    raw_usage = event.get("usage")

    if not has_str_field(event, "result") or not isinstance(raw_usage, dict):
        raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime emitted a malformed result event")

    result = event.get("result")

    usage: dict[str, int] = {}

    for field in _USAGE_FIELDS:
        value = raw_usage.get(field)

        if value is None:
            continue

        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime emitted malformed usage data")

        usage[field] = value

    return result, usage


class ClaudeTurnPhase(Enum):
    AWAITING_INIT = "awaiting_init"            # spawn 직후
    STREAMING = "streaming"                    # init 수신 후
    FINISHED = "finished"                      # init과 result 모두 수신. 이후 이벤트는 위반
    FINISHED_WITHOUT_INIT = "finished_without_init"  # init 없이 result 수신 (현행 도달 가능 경로).
                                               # 이후 이벤트는 위반, 성공 판정에서는 init 누락으로 실패


class ClaudeTurnStateMachine:
    # phase 전이: AWAITING_INIT --init--> STREAMING --result--> FINISHED
    #            AWAITING_INIT --result--> FINISHED_WITHOUT_INIT
    # 불변식: phase가 FINISHED 또는 FINISHED_WITHOUT_INIT ⇒ result_text/result_usage is not None
    def __init__(self, scratch: Path):
        self._scratch = scratch
        self.phase: ClaudeTurnPhase = ClaudeTurnPhase.AWAITING_INIT
        self.result_text: str | None = None
        self.result_usage: dict[str, int] | None = None
        self.emitted_text: list[str] = []

    @property
    def has_emitted_text(self) -> bool:
        return bool(self.emitted_text)

    def consume_event(self, event: dict) -> str:

        if self.phase in (ClaudeTurnPhase.FINISHED, ClaudeTurnPhase.FINISHED_WITHOUT_INIT):
            raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime emitted an event after the final result")

        if _contains_prohibited_tool_use(event):
            raise _runtime_error(ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION, "Claude attempted a prohibited tool action")

        error:ProviderRuntimeError | None = _classify_event_error(event)

        if error:
            raise error

        event_type: str | None = event.get("type")
        event_subtype: object = event.get("subtype")

        if event_type == "system" and event_subtype == "init":
            if self.phase == ClaudeTurnPhase.STREAMING:
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime emitted duplicate initialization")

            event_cwd: Path | None = Path(event.get("cwd")) if has_str_field(event, "cwd") else None

            cwd_isolated: bool = event_cwd is not None and event_cwd.resolve() == self._scratch.resolve()
            tools_disabled: bool = event.get("tools") == [] and event.get("mcp_servers") == []

            if not cwd_isolated or not tools_disabled:
                raise _runtime_error(ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION, "Claude did not apply the required isolated runtime policy")

            self.phase = ClaudeTurnPhase.STREAMING

        if event_type == "result":
            malformed_result: bool = not has_str_field(event, "subtype") or not isinstance(event.get("is_error"), bool)

            if malformed_result:
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime emitted a malformed result event")

            if event_subtype != "success":
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime emitted an unknown result subtype")

            if event.get("permission_denials") not in (None, []):
                raise _runtime_error(ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION, "Claude attempted a prohibited tool action")

            self.result_text, self.result_usage = _parse_result_event(event)
            self.phase: ClaudeTurnPhase = ClaudeTurnPhase.FINISHED if self.phase == ClaudeTurnPhase.STREAMING else ClaudeTurnPhase.FINISHED_WITHOUT_INIT

        text :str = _extract_text_delta(event)

        if not text:
            return ""

        if self.phase == ClaudeTurnPhase.AWAITING_INIT:
            raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime emitted text before initialization")

        self.emitted_text.append(text)

        return text
