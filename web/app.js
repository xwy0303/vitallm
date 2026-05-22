const API_BASE_URL = window.ENZYME_API_BASE_URL || "http://127.0.0.1:8001";
const DEFAULT_COLLECTION = "enzyme_immobilization_b10";

const textarea = document.querySelector("[data-query-input]");
const sendButton = document.querySelector("[data-send-button]");
const modeButtons = Array.from(document.querySelectorAll("[data-mode]"));
const resultPanel = document.querySelector("[data-result-panel]");
const resultTitle = document.querySelector("[data-result-title]");
const resultBody = document.querySelector("[data-result-body]");
const statusText = document.querySelector("[data-api-status]");
const promptButtons = Array.from(document.querySelectorAll("[data-prompt]"));

let activeMode = "recommend";
let loadingTimer = null;
let loadingStartedAt = 0;

modeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    activeMode = button.dataset.mode || "recommend";
    modeButtons.forEach((item) => item.classList.toggle("active", item === button));
    if (activeMode === "optimize") {
      textarea.placeholder =
        '输入配方 JSON，例如：{"enzyme_loading":{"value":500,"unit":"mg"},"buffer":{"pH":7},"immobilization_conditions":{"time":{"value":60,"unit":"min"}}}';
    } else if (activeMode === "search") {
      textarea.placeholder = "输入证据检索 query，例如：soybean oil ethanol yield 93.4 8 cycles last yield";
    } else {
      textarea.placeholder =
        "例如：Burkholderia cepacia lipase，用于大豆油乙醇酯交换制备 biodiesel，推荐固定化载体和条件。";
    }
  });
});

promptButtons.forEach((button) => {
  button.addEventListener("click", () => {
    textarea.value = button.dataset.prompt || button.textContent.trim();
    textarea.focus();
  });
});

sendButton.addEventListener("click", () => {
  runQuery().catch((error) => {
    renderError(error.message || String(error));
  });
});

textarea.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    runQuery().catch((error) => renderError(error.message || String(error)));
  }
});

checkHealth();

async function checkHealth() {
  try {
    const data = await requestJson("/api/health", { method: "GET" });
    statusText.textContent = `${data.generator_provider} / ${data.collection}`;
  } catch (_error) {
    statusText.textContent = "API 未连接";
  }
}

async function runQuery() {
  const rawInput = textarea.value.trim();
  if (!rawInput) {
    renderError("请输入酶名、配方 JSON 或证据 query。");
    return;
  }

  setLoading(true);
  try {
    if (activeMode === "optimize") {
      const payload = buildOptimizePayload(rawInput);
      const data = await requestJson("/api/optimize/formulation", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      renderOptimization(data);
    } else if (activeMode === "search") {
      const data = await requestJson("/api/search/evidence", {
        method: "POST",
        body: JSON.stringify({
          query: rawInput,
          collection: DEFAULT_COLLECTION,
          top_k: 5,
          usable_only: true,
        }),
      });
      renderSearch(data);
    } else {
      const data = await requestJson("/api/recommend/by-enzyme", {
        method: "POST",
        body: JSON.stringify(buildRecommendPayload(rawInput)),
      });
      renderRecommendation(data);
    }
  } catch (error) {
    renderError(error.message || String(error));
  } finally {
    setLoading(false);
  }
}

function buildRecommendPayload(rawInput) {
  return {
    enzyme_name: extractEnzymeName(rawInput),
    application_context: rawInput,
    collection: DEFAULT_COLLECTION,
    top_k: 5,
  };
}

function buildOptimizePayload(rawInput) {
  let formulation;
  try {
    formulation = JSON.parse(rawInput);
  } catch (_error) {
    formulation = {
      note: rawInput,
    };
  }
  return {
    enzyme_name: rawInput.startsWith("{") ? "Burkholderia cepacia lipase" : extractEnzymeName(rawInput),
    user_formulation: formulation,
    application_context: rawInput,
    collection: DEFAULT_COLLECTION,
    top_k: 5,
  };
}

function extractEnzymeName(rawInput) {
  const knownNames = ["Burkholderia cepacia lipase", "BCL", "lipase"];
  const lower = rawInput.toLowerCase();
  const match = knownNames.find((name) => lower.includes(name.toLowerCase()));
  return match === "BCL" ? "Burkholderia cepacia lipase" : match || rawInput.split(/[，,。.\n]/)[0].trim();
}

async function requestJson(path, options) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 120000);
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    signal: controller.signal,
    ...options,
  }).catch((error) => {
    if (error.name === "AbortError") {
      throw new Error("请求超过 120 秒仍未返回。请稍后重试，或先使用证据检索模式确认知识库可用。");
    }
    throw error;
  });
  try {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = data?.error?.message || data?.detail?.error?.message || response.statusText;
      throw new Error(typeof message === "string" ? message : JSON.stringify(message));
    }
    return data;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function setLoading(isLoading) {
  sendButton.disabled = isLoading;
  sendButton.textContent = isLoading ? "处理中" : "发送";
  resultPanel.hidden = false;
  resultTitle.textContent = isLoading ? "正在检索证据并生成建议" : resultTitle.textContent;
  if (isLoading) {
    loadingStartedAt = Date.now();
    updateLoadingMessage();
    loadingTimer = window.setInterval(updateLoadingMessage, 1000);
  } else if (loadingTimer) {
    window.clearInterval(loadingTimer);
    loadingTimer = null;
  }
}

function updateLoadingMessage() {
  const seconds = Math.max(0, Math.round((Date.now() - loadingStartedAt) / 1000));
  resultBody.innerHTML = `
    <div class="loading-steps">
      <span>1. Qdrant evidence retrieval：通常 &lt; 1 秒</span>
      <span>2. SiliconFlow generation：当前已等待 ${seconds} 秒</span>
      <span>3. Structured response rendering：返回后自动展示 citations</span>
    </div>
    <p class="result-muted">真实 LLM 生成不是卡死，通常需要 10-40 秒；超过 120 秒会自动报错。</p>
  `;
}

function renderRecommendation(data) {
  resultTitle.textContent = "固定化推荐结果";
  const candidates = data.candidates || [];
  resultBody.innerHTML = [
    renderMeta(data.generator_provider, data.generator_model, data.limitations),
    candidates.length
      ? candidates
          .map(
            (item) => `
              <article class="result-card">
                <div class="result-card-head">
                  <strong>#${escapeHtml(item.rank)} ${escapeHtml(item.carrier || item.strategy_summary)}</strong>
                  <span>${escapeHtml(item.confidence)}</span>
                </div>
                <p>${escapeHtml(item.strategy_summary)}</p>
                <p><b>method</b>: ${escapeHtml(item.immobilization_method || "-")}</p>
                ${renderKeyValues(item.recommended_conditions)}
                ${renderList("expected benefits", item.expected_benefits)}
                ${renderList("citations", item.citations)}
              </article>
            `
          )
          .join("")
      : '<p class="result-muted">没有生成可排序候选，请检查 collection 或 query。</p>',
  ].join("");
}

function renderOptimization(data) {
  resultTitle.textContent = "配方优化建议";
  const changes = data.changes || [];
  resultBody.innerHTML = [
    renderMeta(data.generator_provider, data.generator_model, data.limitations),
    changes.length
      ? changes
          .map(
            (item) => `
              <article class="result-card">
                <div class="result-card-head">
                  <strong>${escapeHtml(item.field_path)}</strong>
                  <span>${escapeHtml(item.confidence)}</span>
                </div>
                <p><b>current</b>: ${escapeHtml(formatValue(item.current_value))}</p>
                <p><b>recommended</b>: ${escapeHtml(formatValue(item.recommended_value))}</p>
                <p>${escapeHtml(item.rationale)}</p>
                ${renderList("citations", item.citations)}
              </article>
            `
          )
          .join("")
      : '<p class="result-muted">没有生成字段级改动建议。</p>',
  ].join("");
}

function renderSearch(data) {
  resultTitle.textContent = "证据检索结果";
  const hits = data.hits || [];
  resultBody.innerHTML = hits.length
    ? hits
        .map(
          (hit) => `
            <article class="result-card">
              <div class="result-card-head">
                <strong>${escapeHtml(hit.record_type || hit.point_type)}</strong>
                <span>${Number(hit.score || 0).toFixed(3)}</span>
              </div>
              <p>${escapeHtml(hit.citation || "-")}</p>
              <p>${escapeHtml((hit.text || "").slice(0, 460))}</p>
            </article>
          `
        )
        .join("")
    : '<p class="result-muted">没有检索到 evidence。</p>';
}

function renderMeta(provider, model, limitations) {
  return `
    <div class="result-meta">
      <span>provider: ${escapeHtml(provider || "-")}</span>
      <span>model: ${escapeHtml(model || "-")}</span>
    </div>
    ${renderList("limitations", limitations || [])}
  `;
}

function renderKeyValues(value) {
  const entries = Object.entries(value || {});
  if (!entries.length) return "";
  return `
    <dl class="kv-list">
      ${entries
        .map(([key, item]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(formatValue(item))}</dd></div>`)
        .join("")}
    </dl>
  `;
}

function renderList(title, items) {
  const normalizedItems = Array.isArray(items) ? items : items ? [items] : [];
  if (!normalizedItems.length) return "";
  return `
    <div class="result-list">
      <b>${escapeHtml(title)}</b>
      ${normalizedItems.map((item) => `<span>${escapeHtml(formatValue(item))}</span>`).join("")}
    </div>
  `;
}

function renderError(message) {
  resultPanel.hidden = false;
  resultTitle.textContent = "请求失败";
  resultBody.innerHTML = `<p class="result-error">${escapeHtml(message)}</p>`;
}

function formatValue(value) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
