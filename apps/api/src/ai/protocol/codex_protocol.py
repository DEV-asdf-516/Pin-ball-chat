import logging
from pathlib import Path
from typing import Callable

from ai.errors import ErrorRule, ProviderErrorCode, ProviderRuntimeError, match_error_rule, runtime_error_factory
from ai.specs import ProviderName
from util.safe_util import get_safe_dict


log = logging.getLogger(__name__)

_runtime_error: Callable[..., ProviderRuntimeError] = runtime_error_factory(ProviderName.OPENAI_CODEX)

_JSON_RPC_PROTOCOL_ERROR_CODES = {"-32700", "-32600", "-32601", "-32602"}

_EVENT_ERROR_RULES: list[ErrorRule] = [
    ErrorRule({"auth_required", "authentication_required", "unauthorized"}, ProviderErrorCode.PROVIDER_AUTH_REQUIRED, "ChatGPT login is required"),
    ErrorRule({"rate_limit_exceeded", "quota_exhausted", "usage_limit_reached", "usageLimitExceeded", "sessionBudgetExceeded"}, ProviderErrorCode.PROVIDER_QUOTA_EXHAUSTED, "ChatGPT usage limit has been reached", retryable=True),
    ErrorRule({"model_not_found", "model_unavailable", "model_access_denied"}, ProviderErrorCode.MODEL_UNAVAILABLE, "the selected Codex model is unavailable"),
]

_PROHIBITED_SERVER_REQUESTS = {
    "item/commandExecution/requestApproval", "item/fileChange/requestApproval", "item/tool/requestUserInput",
    "mcpServer/elicitation/request", "item/permissions/requestApproval", "item/tool/call",
    "applyPatchApproval", "execCommandApproval",
}
_PROHIBITED_ITEM_TYPES = {
    "commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall", "collabAgentToolCall",
    "subAgentActivity", "webSearch", "imageView", "sleep", "imageGeneration",
}
_SAFE_ITEM_TYPES = {"userMessage", "agentMessage", "reasoning", "plan", "contextCompaction"}

# stream() turn 루프가 거부하는 server-initiated 메서드 집합. _PROHIBITED_SERVER_REQUESTS와
# 겹치지만 동일하지 않다 — command/exec/outputDelta를 포함하고 applyPatchApproval/
# execCommandApproval은 빠진다. 별도 상수로 유지한다.
PROHIBITED_TURN_METHODS = {
    "item/commandExecution/requestApproval", "item/fileChange/requestApproval", "item/tool/requestUserInput",
    "item/tool/call", "item/permissions/requestApproval", "mcpServer/elicitation/request", "command/exec/outputDelta",
}


def classify_event_error(event: dict) -> ProviderRuntimeError:
    params = get_safe_dict(event, "params")
    error = event.get("error") if isinstance(event.get("error"), dict) else params.get("error", {})
    if not isinstance(error, dict):
        return _runtime_error(ProviderErrorCode.PROVIDER_BAD_GATEWAY, "codex runtime returned an invalid error")
    code_value = error.get("codexErrorInfo") or error.get("code") or error.get("type") or ""
    code = str(code_value)
    if code in _JSON_RPC_PROTOCOL_ERROR_CODES:
        return _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime rejected the stable protocol request")
    rule = match_error_rule(_EVENT_ERROR_RULES, {code})
    if rule:
        return _runtime_error(rule.code, rule.message, retryable=rule.retryable)
    return _runtime_error(ProviderErrorCode.PROVIDER_BAD_GATEWAY, "codex runtime rejected the request", retryable=True)


def is_secure_thread(thread_start: dict, model: str, scratch: Path) -> bool:
    effective_sandbox = get_safe_dict(thread_start, "sandbox")
    response_cwd = Path(thread_start.get("cwd")) if isinstance(thread_start.get("cwd"), str) else None
    return (
        response_cwd is not None
        and response_cwd.resolve() == scratch.resolve()
        and thread_start.get("approvalPolicy") == "never"
        and effective_sandbox.get("type") == "readOnly"
        and effective_sandbox.get("networkAccess") is not True
        and thread_start.get("instructionSources", []) == []
        and thread_start.get("model") == model
    )


def parse_turn_start(turn_start: dict) -> str | None:
    turn = get_safe_dict(turn_start, "turn")
    turn_id = turn.get("id")
    if not isinstance(turn_id, str) or not isinstance(turn.get("items"), list) or not isinstance(turn.get("status"), str):
        return None
    return turn_id


def validate_model_page(result: dict) -> list[str]:
    data = result.get("data")
    if not isinstance(data, list) or any(not isinstance(item, dict) or not isinstance(item.get("model"), str) or not isinstance(item.get("hidden"), bool) for item in data):
        raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime returned a malformed model list")
    models = [item["model"] for item in data if not item["hidden"]]
    cursor = result.get("nextCursor")
    if cursor is not None and not isinstance(cursor, str):
        raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime returned a malformed model cursor")
    return models


def is_valid_device_login(result: dict) -> bool:
    return result.get("type") == "chatgptDeviceCode" and all(
        isinstance(result.get(field), str) and result.get(field) for field in ("loginId", "verificationUrl", "userCode")
    )


class CodexTurnStateMachine:
    # 공유 app-server의 한 turn에 대한 이벤트 소비 규칙. queue도 process도 모른다.
    def __init__(self, turn_id: str):
        self.turn_id = turn_id
        self.has_emitted = False
        self.completed = False
        self.terminal_received = False

    def consume_event(self, event: dict) -> str:
        method, params = event.get("method"), event.get("params", {})
        if method == "item/agentMessage/delta":
            delta = params.get("delta")
            if not all(isinstance(params.get(field), str) for field in ("threadId", "turnId", "itemId")) or not isinstance(delta, str):
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime emitted a malformed agent message delta")
            if delta:
                self.has_emitted = True
                return delta
            return ""
        if method in {"item/started", "item/completed"}:
            item = get_safe_dict(params, "item")
            item_type = item.get("type")
            if not isinstance(item_type, str):
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime emitted a malformed item event")
            if item_type in _PROHIBITED_ITEM_TYPES:
                raise _runtime_error(ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION, "Codex attempted a prohibited tool action")
            if item_type not in _SAFE_ITEM_TYPES:
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime emitted an unknown item type")
            return ""
        if method in PROHIBITED_TURN_METHODS:
            raise _runtime_error(ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION, "Codex attempted a prohibited tool action")
        if method == "turn/completed":
            self.terminal_received = True
            turn = get_safe_dict(params, "turn")
            if turn.get("id") != self.turn_id or not isinstance(turn.get("status"), str):
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime emitted a malformed turn completion")
            status = turn["status"]
            if status == "completed":
                self.completed = True
                return ""
            if status == "interrupted":
                raise _runtime_error(ProviderErrorCode.PROVIDER_BAD_GATEWAY, "Codex generation was interrupted")
            if status == "failed":
                raise classify_event_error({"error": turn.get("error") or {}})
            raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "Codex turn completed with an invalid status")
        log.debug("ignored Codex turn event method=%s", str(method)[:120])
        return ""
