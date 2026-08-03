import logging
from pathlib import Path
from typing import Callable

from ai.errors import ErrorRule, ProviderErrorCode, ProviderRuntimeError, match_error_rule, runtime_error_factory
from ai.specs import ProviderName
from util.safe_util import get_safe_dict, get_safe_str, has_str_field


log = logging.getLogger(__name__)

_runtime_error: Callable[..., ProviderRuntimeError] = runtime_error_factory(ProviderName.OPENAI_CODEX)

_JSON_RPC_PROTOCOL_ERROR_CODES = {"-32700", "-32600", "-32601", "-32602"}

_EVENT_ERROR_RULES: list[ErrorRule] = [
    ErrorRule({"auth_required", "authentication_required", "unauthorized"}, 
        ProviderErrorCode.PROVIDER_AUTH_REQUIRED, 
        "ChatGPT login is required"
    ),
    ErrorRule({"rate_limit_exceeded", "quota_exhausted", "usage_limit_reached", "usageLimitExceeded", "sessionBudgetExceeded"}, 
        ProviderErrorCode.PROVIDER_QUOTA_EXHAUSTED, 
        "ChatGPT usage limit has been reached", 
        retryable=True
    ),
    ErrorRule({"model_not_found", "model_unavailable", "model_access_denied"}, 
        ProviderErrorCode.MODEL_UNAVAILABLE, 
        "the selected Codex model is unavailable"
    ),
]

_PROHIBITED_SERVER_REQUESTS = {
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/tool/requestUserInput",
    "mcpServer/elicitation/request",
    "item/permissions/requestApproval",
    "item/tool/call",
    "applyPatchApproval",
    "execCommandApproval",
}


_PROHIBITED_ITEM_TYPES = {
    "commandExecution", 
    "fileChange", 
    "mcpToolCall", 
    "dynamicToolCall", 
    "collabAgentToolCall",
    "subAgentActivity", 
    "webSearch", 
    "imageView", 
    "sleep", 
    "imageGeneration",
}

_SAFE_ITEM_TYPES = {"userMessage", "agentMessage", "reasoning", "plan", "contextCompaction"}

# turn 루프 전용 금지 목록. _PROHIBITED_SERVER_REQUESTS와 다르다
PROHIBITED_TURN_METHODS = {
    "item/commandExecution/requestApproval", 
    "item/fileChange/requestApproval", 
    "item/tool/requestUserInput",
    "item/tool/call", 
    "item/permissions/requestApproval", 
    "mcpServer/elicitation/request", 
    "command/exec/outputDelta",
}


def is_prohibited_server_request(method: str | None) -> bool:
    return method in _PROHIBITED_SERVER_REQUESTS


def classify_event_error(event: dict) -> ProviderRuntimeError:
    params: dict = get_safe_dict(event, "params")
    raw_error = event.get("error")
    error: dict = raw_error if isinstance(raw_error, dict) else params.get("error", {})

    if not isinstance(error, dict):
        return _runtime_error(
            ProviderErrorCode.PROVIDER_BAD_GATEWAY,
            "codex runtime returned an invalid error"
        )

    codex_error_info: str = get_safe_str(error, "codexErrorInfo")
    error_code: str = get_safe_str(error, "code")
    error_type: str = get_safe_str(error, "type")

    code: str = str(codex_error_info or error_code or error_type)

    if code in _JSON_RPC_PROTOCOL_ERROR_CODES:
        return _runtime_error(
            ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, 
            "codex runtime rejected the stable protocol request"
        )

    rule: ErrorRule | None = match_error_rule(_EVENT_ERROR_RULES, {code})

    if rule:
        return _runtime_error(rule.code, rule.message, retryable=rule.retryable)

    log.warning("codex runtime rejected the request with an unrecognized error: %s", error)
    return _runtime_error(
        ProviderErrorCode.PROVIDER_BAD_GATEWAY,
        "codex runtime rejected the request",
        retryable=True
    )


def is_secure_thread(thread_start: dict, model: str, scratch: Path) -> bool:
    effective_sandbox: dict = get_safe_dict(thread_start, "sandbox")
    cwd = thread_start.get("cwd")
    response_cwd: Path | None = Path(cwd) if isinstance(cwd, str) else None

    return (
        response_cwd is not None
        and response_cwd.resolve() == scratch.resolve()
        and thread_start.get("approvalPolicy") == "never"
        and effective_sandbox.get("type") == "readOnly"
        and effective_sandbox.get("networkAccess") is not True
        and thread_start.get("instructionSources", []) == []
        and thread_start.get("model") == model
    )


def parse_started_turn_id(turn_start: dict) -> str | None:
    turn: dict = get_safe_dict(turn_start, "turn")

    if (
        not has_str_field(turn, "id")
        or not isinstance(turn.get("items"), list)
        or not has_str_field(turn, "status")
    ):
        return None

    return turn.get("id")


def parse_model_page(result: dict) -> list[str]:
    def is_model_item(item: object) -> bool:
        return (
            isinstance(item, dict)
            and has_str_field(item, "model")
            and isinstance(item.get("hidden"), bool)
        )

    data = result.get("data")

    if (
        not isinstance(data, list)
        or not all(is_model_item(item) for item in data)
    ):
        raise _runtime_error(
            ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE,
            "codex runtime returned a malformed model list",
        )

    cursor = result.get("nextCursor")

    if cursor is not None and not isinstance(cursor, str):
        raise _runtime_error(
            ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE,
            "codex runtime returned a malformed model cursor",
        )

    return [item["model"] for item in data if not item["hidden"]]


def is_valid_device_login(device_login_result: dict) -> bool:
    is_device_code: bool = device_login_result.get("type") == "chatgptDeviceCode"

    return is_device_code and all(
        has_str_field(device_login_result, field) \
        and device_login_result.get(field)
        for field in ("loginId", "verificationUrl", "userCode")
    )


class CodexTurnStateMachine:
    # 공유 app-server의 한 turn에 대한 이벤트 소비 규칙. queue도 process도 모른다.
    def __init__(self, turn_id: str):
        self.turn_id: str = turn_id
        self.has_emitted: bool = False
        self.completed: bool = False
        self.terminal_received: bool = False

    def consume_event(self, event: dict) -> str:
        method: str | None = event.get("method")
        params: dict = event.get("params", {})
        item_type = get_safe_dict(params, "item").get("type")
        
        is_item_event = method in {"item/started", "item/completed"}
       
        is_prohibited_item = is_item_event \
            and isinstance(item_type, str) \
            and item_type in _PROHIBITED_ITEM_TYPES

        if method in PROHIBITED_TURN_METHODS or is_prohibited_item:
            raise _runtime_error(
                ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION,
                "Codex attempted a prohibited tool action"
            )

        if method == "item/agentMessage/delta":
            delta = params.get("delta")

            if (
                not isinstance(delta, str)
                or not all(has_str_field(params, field) for field in ("threadId", "turnId", "itemId"))
            ):
                raise _runtime_error(
                    ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE,
                    "codex runtime emitted a malformed agent message delta"
                )

            if not delta:
                return ""
        
            self.has_emitted = True
            return delta

        if is_item_event:
            if not isinstance(item_type, str):
                raise _runtime_error(
                    ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, 
                    "codex runtime emitted a malformed item event"
                )

            if item_type not in _SAFE_ITEM_TYPES:
                raise _runtime_error(
                    ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, 
                    "codex runtime emitted an unknown item type"
                )

            return ""

        if method == "turn/completed":
            self.terminal_received = True
            turn: dict = get_safe_dict(params, "turn")

            if turn.get("id") != self.turn_id or not has_str_field(turn, "status"):
                raise _runtime_error(
                    ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, 
                    "codex runtime emitted a malformed turn completion"
                )

            status: str = turn["status"]

            if status == "completed":
                self.completed = True
                return ""

            if status == "interrupted":
                raise _runtime_error(
                    ProviderErrorCode.PROVIDER_BAD_GATEWAY, 
                    "Codex generation was interrupted"
                )

            if status == "failed":
                raise classify_event_error({"error": get_safe_dict(turn, "error")})

            raise _runtime_error(
                ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, 
                "Codex turn completed with an invalid status"
            )

        log.debug("ignored Codex turn event method=%s", str(method)[:120])
        return ""
