(() => {
  const namePattern = /^[a-z0-9][a-z0-9-]{1,62}$/;
  const state = {
    tab: "datasets",
    datasets: [],
    manualTurns: [],
    selectedRun: null,
    lastLog: "",
  };
  const $ = (selector) => document.querySelector(selector);

  class ApiError extends Error {
    constructor(method, path, status, detail) {
      super(detail);
      this.method = method;
      this.path = path;
      this.status = status;
      this.detail = detail;
    }
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function textElement(tag, text, className) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = String(text ?? "");
    return element;
  }

  function formatDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value ?? "");
    const pad = (part) => String(part).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function showError(error) {
    const banner = $("#error-banner");
    $("#error-summary").textContent = "요청을 완료하지 못했습니다.";
    const status = error.status ? String(error.status) : "network error";
    $("#error-detail").textContent = `${error.method || "REQUEST"} ${error.path || ""} → ${status} · ${error.detail || error.message}`;
    banner.hidden = false;
  }

  function clearError() {
    $("#error-banner").hidden = true;
    $("#error-summary").textContent = "";
    $("#error-detail").textContent = "";
  }

  async function request(path, options = {}) {
    const method = options.method || "GET";
    let response;
    try {
      response = await fetch(path, options);
    } catch (error) {
      throw new ApiError(method, path, null, error.message || "Network request failed");
    }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new ApiError(method, path, response.status, body.error || response.statusText || "Unknown server error");
    }
    clearError();
    return body;
  }

  async function runRequest(callback) {
    try {
      return await callback();
    } catch (error) {
      showError(error);
      return null;
    }
  }

  function setButtonLoading(button, loading) {
    if (!button) return;
    if (loading) {
      button.dataset.label = button.textContent;
      button.textContent = "…";
      button.disabled = true;
      return;
    }
    button.textContent = button.dataset.label || button.textContent;
    button.disabled = false;
  }

  function setFeedback(selector, message, isError = false) {
    const feedback = $(selector);
    feedback.textContent = message;
    feedback.classList.toggle("is-error", isError);
  }

  function statusBadge(status) {
    return textElement("span", status, `status-badge status-${status}`);
  }

  function renderEmptyRow(target, columns, title, action) {
    clear(target);
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = columns;
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.append(textElement("strong", title), textElement("span", action));
    cell.append(empty);
    row.append(cell);
    target.append(row);
  }

  function renderDatasets() {
    const list = $("#dataset-list");
    if (!state.datasets.length) {
      renderEmptyRow(list, 5, "아직 데이터셋이 없습니다", "아래 세 가지 방법으로 첫 데이터셋을 만드세요.");
    } else {
      clear(list);
      state.datasets.forEach((dataset) => {
        const row = document.createElement("tr");
        row.append(
          textElement("td", dataset.name, "dataset-name"),
          textElement("td", dataset.source),
          textElement("td", dataset.format),
          textElement("td", dataset.row_count),
          textElement("td", formatDate(dataset.created_at)),
        );
        list.append(row);
      });
    }
    const invalid = $("#invalid-datasets");
    invalid.textContent = state.invalidDatasets?.length ? `읽을 수 없는 폴더: ${state.invalidDatasets.join(", ")}` : "";
    invalid.hidden = !invalid.textContent;
    renderDatasetChoices();
  }

  function renderDatasetChoices() {
    const choices = $("#training-datasets");
    clear(choices);
    if (!state.datasets.length) {
      choices.append(textElement("p", "학습할 데이터셋이 아직 없습니다.", "loading-text"));
      updateTrainingSummary();
      return;
    }
    state.datasets.forEach((dataset) => {
      const item = document.createElement("div");
      item.className = "dataset-choice";
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = dataset.name;
      checkbox.dataset.rows = String(dataset.row_count);
      checkbox.disabled = dataset.format !== "chat";
      if (checkbox.disabled) checkbox.title = "v0.2에서 지원";
      checkbox.addEventListener("change", updateTrainingSummary);
      label.append(checkbox, textElement("span", dataset.name, "dataset-name"));
      const meta = document.createElement("span");
      meta.className = "dataset-choice-meta";
      meta.textContent = `${dataset.format} · ${dataset.row_count} rows`;
      item.append(label, meta);
      if (checkbox.disabled) item.append(textElement("span", "v0.2에서 지원", "dataset-unavailable"));
      choices.append(item);
    });
    updateTrainingSummary();
  }

  function updateTrainingSummary() {
    const selected = Array.from($("#training-datasets").querySelectorAll("input:checked"));
    const rowCount = selected.reduce((total, input) => total + Number(input.dataset.rows || 0), 0);
    $("#training-summary").textContent = `선택됨: ${selected.length}개 데이터셋 · ${rowCount.toLocaleString()} rows`;
  }

  async function refreshDatasets() {
    const data = await request("/api/datasets");
    state.datasets = data.datasets || [];
    state.invalidDatasets = data.invalid || [];
    renderDatasets();
  }

  async function refreshRecipes() {
    const data = await request("/api/recipes");
    const select = $("#recipe");
    clear(select);
    (data.recipes || []).forEach((recipe) => {
      const option = document.createElement("option");
      option.value = recipe;
      option.textContent = recipe;
      select.append(option);
    });
  }

  function renderManualTurns() {
    const list = $("#manual-turns");
    clear(list);
    state.manualTurns.forEach((turn, index) => {
      const item = document.createElement("article");
      item.className = "turn-item";
      const header = document.createElement("div");
      header.className = "turn-item-header";
      const remove = textElement("button", "삭제", "delete-turn");
      remove.type = "button";
      remove.addEventListener("click", () => {
        state.manualTurns.splice(index, 1);
        renderManualTurns();
      });
      header.append(textElement("span", `턴 ${index + 1}`), remove);
      item.append(header, textElement("div", turn.user, "turn-bubble"), textElement("div", turn.assistant, "turn-bubble assistant"));
      list.append(item);
    });
  }

  function addManualTurn() {
    const form = $("#manual-form");
    const user = form.elements.user.value.trim();
    const assistant = form.elements.assistant.value.trim();
    if (!user || !assistant) {
      setFeedback("#manual-feedback", "user와 assistant 내용을 모두 입력하세요.", true);
      return;
    }
    state.manualTurns.push({ user, assistant });
    form.elements.user.value = "";
    form.elements.assistant.value = "";
    setFeedback("#manual-feedback", "");
    renderManualTurns();
  }

  function outputNameIsValid() {
    const input = $("#output-name");
    const valid = namePattern.test(input.value);
    $("#output-name-error").hidden = !input.value || valid;
    return valid;
  }

  function renderRuns() {
    const list = $("#run-list");
    const runs = state.runs || [];
    if (!runs.length) {
      renderEmptyRow(list, 5, "아직 실행 이력이 없습니다", "학습 탭에서 첫 학습 작업을 시작하세요.");
    } else {
      clear(list);
      runs.forEach((run) => {
        const row = document.createElement("tr");
        row.dataset.runId = String(run.id);
        if (state.selectedRun?.id === run.id) row.classList.add("is-selected");
        row.addEventListener("click", () => selectRun(run));
        const status = document.createElement("td");
        status.append(statusBadge(run.status));
        row.append(textElement("td", run.id), textElement("td", run.type), status, textElement("td", run.output_name, "run-name"), textElement("td", formatDate(run.created_at)));
        list.append(row);
      });
    }
    if (state.selectedRun) {
      const updated = runs.find((run) => run.id === state.selectedRun.id);
      if (updated) state.selectedRun = updated;
    }
    renderLogHeader();
  }

  function renderLogHeader() {
    const header = $("#log-header");
    clear(header);
    const run = state.selectedRun;
    if (!run) {
      const heading = document.createElement("div");
      heading.className = "card-heading";
      heading.append(textElement("h2", "로그"), textElement("p", "실행을 선택하면 최근 200줄을 3초마다 갱신합니다."));
      header.append(heading);
      return;
    }
    const heading = document.createElement("div");
    heading.className = "card-heading";
    const title = document.createElement("h2");
    title.append(document.createTextNode(`#${run.id} · ${run.output_name} `), statusBadge(run.status));
    heading.append(title, textElement("p", `${run.type} · ${formatDate(run.created_at)}`));
    header.append(heading);
    if (run.type === "TRAIN" && run.status === "DONE") {
      const button = textElement("button", "Ollama 등록", "primary-button");
      button.type = "button";
      button.addEventListener("click", () => registerRun(run, button));
      header.append(button);
    }
  }

  async function refreshRuns() {
    const data = await request("/api/training-runs");
    state.runs = data.runs || [];
    renderRuns();
  }

  async function selectRun(run) {
    state.selectedRun = run;
    state.lastLog = "";
    renderRuns();
    $("#log-empty").hidden = true;
    $("#log").hidden = false;
    await runRequest(refreshLog);
  }

  async function refreshLog() {
    if (!state.selectedRun) return;
    const data = await request(`/api/training-runs/${state.selectedRun.id}/log?tail=200`);
    const content = (data.lines || []).join("\n");
    const log = $("#log");
    log.textContent = content;
    if (content !== state.lastLog) log.scrollTop = log.scrollHeight;
    state.lastLog = content;
  }

  async function registerRun(run, button) {
    setButtonLoading(button, true);
    const created = await runRequest(() => request(`/api/training-runs/${run.id}/register`, { method: "POST" }));
    setButtonLoading(button, false);
    if (!created) return;
    setFeedback("#log-feedback", `등록 작업 #${created.id}을 대기열에 추가했습니다.`);
    await runRequest(refreshRuns);
  }

  async function showTab(tab) {
    state.tab = tab;
    document.querySelectorAll(".tab-panel").forEach((panel) => { panel.hidden = panel.id !== tab; });
    document.querySelectorAll(".tab-button").forEach((button) => { button.setAttribute("aria-selected", String(button.dataset.tab === tab)); });
    if (tab === "datasets" || tab === "training") await runRequest(refreshDatasets);
    if (tab === "training") await runRequest(refreshRecipes);
    if (tab === "runs") await runRequest(refreshRuns);
  }

  $("#export-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    setButtonLoading(button, true);
    const form = new FormData(event.currentTarget);
    const result = await runRequest(() => request("/api/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.fromEntries(form)) }));
    setButtonLoading(button, false);
    if (!result) return;
    setFeedback("#export-feedback", `${result.row_count.toLocaleString()} rows 등록됨`);
    event.currentTarget.reset();
    await runRequest(refreshDatasets);
  });

  $("#import-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    setButtonLoading(button, true);
    const result = await runRequest(() => request("/api/import", { method: "POST", body: new FormData(event.currentTarget) }));
    setButtonLoading(button, false);
    if (!result) return;
    setFeedback("#import-feedback", `${result.row_count.toLocaleString()} rows 등록됨 · 거부 ${result.rejected_rows} · 중복 제거 ${result.duplicates_removed}`);
    event.currentTarget.reset();
    await runRequest(refreshDatasets);
  });

  $("#add-turn").addEventListener("click", addManualTurn);
  $("#manual-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.manualTurns.length) {
      setFeedback("#manual-feedback", "저장할 턴을 먼저 추가하세요.", true);
      return;
    }
    const button = event.submitter;
    setButtonLoading(button, true);
    const form = event.currentTarget;
    const messages = [];
    const system = form.elements.system.value.trim();
    if (system) messages.push({ role: "system", content: system });
    state.manualTurns.forEach((turn) => messages.push({ role: "user", content: turn.user }, { role: "assistant", content: turn.assistant }));
    const result = await runRequest(() => request("/api/examples", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ dataset: form.elements.dataset.value, format: "chat", row: { messages } }) }));
    setButtonLoading(button, false);
    if (!result) return;
    setFeedback("#manual-feedback", `${result.row_count.toLocaleString()} rows 등록됨`);
    state.manualTurns = [];
    form.reset();
    renderManualTurns();
    await runRequest(refreshDatasets);
  });

  $("#output-name").addEventListener("input", outputNameIsValid);
  $("#output-name").addEventListener("invalid", () => { $("#output-name-error").hidden = false; });
  $("#training-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!outputNameIsValid()) return;
    const button = event.submitter;
    setButtonLoading(button, true);
    const form = event.currentTarget;
    const datasets = Array.from(form.querySelectorAll("input[type=checkbox]:checked")).map((input) => input.value);
    const created = await runRequest(() => request("/api/training-runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ datasets, recipe: form.elements.recipe.value, output_name: form.elements.output_name.value }) }));
    setButtonLoading(button, false);
    if (!created) return;
    setFeedback("#training-feedback", `학습 작업 #${created.id}을 대기열에 추가했습니다.`);
    form.reset();
    await showTab("runs");
  });

  document.querySelectorAll(".tab-button").forEach((button) => button.addEventListener("click", () => showTab(button.dataset.tab)));
  window.setInterval(() => {
    if (state.tab === "runs") runRequest(refreshRuns);
  }, 5000);
  window.setInterval(() => {
    if (state.tab === "runs" && state.selectedRun) runRequest(refreshLog);
  }, 3000);
  showTab("datasets");
})();
