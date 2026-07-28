const messages = {
  api_key_required: "환경변수 API 키가 필요합니다.",
  login_required: "로그인이 필요합니다.",
  provider_auth_required: "연결이 만료되었습니다. 설정에서 다시 로그인하세요.",
  provider_quota_exhausted: "사용 한도가 소진됐습니다.",
  provider_runtime_incompatible: "공식 런타임 버전을 확인하세요.",
  provider_runtime_crashed: "공식 런타임이 비정상 종료됐습니다. 다시 시도하세요.",
  provider_contract_violation: "안전한 text-only 실행 조건을 확인하세요.",
  model_unavailable: "사용 가능한 모델을 다시 선택하세요.",
  provider_bad_gateway: "AI 제공자 연결에 실패했습니다. 잠시 후 다시 시도하세요.",
  ollama_url_required: "Ollama 주소 설정이 필요합니다.",
  ollama_unavailable: "Ollama에 연결할 수 없습니다.",
};

export function providerErrorMessage(error) {
  const code = typeof error === "string" ? error : error?.code;
  if (code === "provider_timeout") return timeoutMessage(error?.phase);
  return messages[code] || error?.message || code || "알 수 없는 오류";
}

function timeoutMessage(phase) {
  return {
    login: "로그인 시간이 초과됐습니다. 다시 시도하세요.",
    first_delta: "응답 시작 시간이 초과됐습니다. 다시 시도하세요.",
    idle: "응답이 중단되어 시간이 초과됐습니다. 다시 시도하세요.",
    interrupt: "생성 취소가 지연되어 런타임을 종료했습니다. 다시 시도하세요.",
  }[phase] || "시간이 초과됐습니다. 다시 시도하세요.";
}
