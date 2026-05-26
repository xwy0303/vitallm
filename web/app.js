const API_BASE_URL = window.ENZYME_API_BASE_URL || "http://127.0.0.1:8001";
const DEFAULT_COLLECTION = window.ENZYME_COLLECTION || null;

const textarea = document.querySelector("[data-query-input]");
const sendButton = document.querySelector("[data-send-button]");
const modeButtons = Array.from(document.querySelectorAll("[data-mode]"));
const resultPanel = document.querySelector("[data-result-panel]");
const resultTitle = document.querySelector("[data-result-title]");
const resultBody = document.querySelector("[data-result-body]");
const statusText = document.querySelector("[data-api-status]");
const promptButtons = Array.from(document.querySelectorAll("[data-prompt]"));
const referenceModal = document.querySelector("[data-reference-modal]");
const referenceModalTitle = document.querySelector("[data-reference-modal-title]");
const referenceModalMeta = document.querySelector("[data-reference-modal-meta]");
const referenceModalText = document.querySelector("[data-reference-modal-text]");
const referenceModalFooter = document.querySelector("[data-reference-modal-footer]");
const pdfDocsMetric = document.querySelector("[data-pdf-docs]");
const pdfPagesMetric = document.querySelector("[data-pdf-pages]");
const qdrantPointsMetric = document.querySelector("[data-qdrant-points]");
const reviewItemsMetric = document.querySelector("[data-review-items]");

const JSON_REQUEST_TIMEOUT_MS = 120000;
const STREAM_REQUEST_TIMEOUT_MS = 300000;
const STREAM_FIRST_TOKEN_TIMEOUT_MS = 45000;
const STREAM_IDLE_TIMEOUT_MS = 45000;
const STREAM_TOP_K = 3;

let activeMode = "recommend";
let loadingTimer = null;
let loadingStartedAt = 0;
let streamBuffer = "";
let activeReferenceHits = [];
let activeReferenceLookup = new Map();
let activeReferenceHit = null;
let activeReferenceExpanded = false;

const CHUNK_PREVIEW_LIMIT = 900;

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

resultBody.addEventListener("click", handleResultBodyClick);

referenceModal?.addEventListener("click", (event) => {
  const closeButton = event.target.closest("[data-close-reference-modal]");
  if (closeButton) {
    event.preventDefault();
    closeReferenceModal();
    return;
  }
  const moreButton = event.target.closest("[data-reference-more]");
  if (moreButton) {
    event.preventDefault();
    activeReferenceExpanded = !activeReferenceExpanded;
    renderReferenceModalContent();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && referenceModal && !referenceModal.hidden) {
    closeReferenceModal();
  }
});

checkHealth();
loadDashboardSummary();

async function checkHealth() {
  try {
    const data = await requestJson("/api/health", { method: "GET" });
    statusText.textContent = `${data.generator_provider} / ${data.collection}`;
  } catch (_error) {
    statusText.textContent = "API 未连接";
  }
}

async function loadDashboardSummary() {
  try {
    const data = await requestJson("/api/dashboard/summary", { method: "GET" });
    renderDashboardSummary(data);
  } catch (_error) {
    renderDashboardSummaryFallback();
  }
}

function renderDashboardSummary(data) {
  const processedDocs = safeNumber(data.processed_docs);
  const processedPages = safeNumber(data.processed_pages);
  const indexedDocs = safeNumber(data.indexed_docs);
  const qdrantPoints = safeNumber(data.qdrant_points);
  const reviewItems = safeNumber(data.review_items);

  if (pdfDocsMetric) {
    const docLabel = processedDocs === null ? "docs 待同步" : `${formatInteger(processedDocs)} docs`;
    pdfDocsMetric.textContent = docLabel;
  }
  if (pdfPagesMetric) {
    pdfPagesMetric.textContent = processedPages === null ? "pages 待同步" : `${formatInteger(processedPages)} pages`;
  }
  if (qdrantPointsMetric) {
    const pointsLabel = qdrantPoints === null ? "points 待同步" : `${formatInteger(qdrantPoints)} points`;
    qdrantPointsMetric.textContent =
      indexedDocs !== null && qdrantPoints !== null
        ? `${pointsLabel} / ${formatInteger(indexedDocs)} docs`
        : pointsLabel;
  }
  if (reviewItemsMetric) {
    reviewItemsMetric.textContent = reviewItems === null ? "待同步" : formatInteger(reviewItems);
  }
}

function renderDashboardSummaryFallback() {
  if (pdfDocsMetric) pdfDocsMetric.textContent = "docs 待同步";
  if (pdfPagesMetric) pdfPagesMetric.textContent = "pages 待同步";
  if (qdrantPointsMetric) qdrantPointsMetric.textContent = "points 待同步";
  if (reviewItemsMetric) reviewItemsMetric.textContent = "待同步";
}

async function runQuery() {
  const rawInput = textarea.value.trim();
  if (!rawInput) {
    renderError("请输入酶名、配方 JSON 或证据 query。");
    return;
  }

  const streamingMode = activeMode !== "search";
  setLoading(true, { showSteps: !streamingMode });
  try {
    if (activeMode === "optimize") {
      const payload = buildOptimizePayload(rawInput);
      if (streamingMode) {
        prepareStreamView("配方优化建议");
        const data = await requestNdjsonStream("/api/optimize/formulation/stream", payload, {
          onStatus: updateStreamStatus,
          onDelta: appendStreamDelta,
        });
        renderOptimization(data);
      } else {
        const data = await requestJson("/api/optimize/formulation", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        renderOptimization(data);
      }
    } else if (activeMode === "search") {
      const data = await requestJson("/api/search/evidence", {
        method: "POST",
        body: JSON.stringify({
          query: rawInput,
          ...(DEFAULT_COLLECTION ? { collection: DEFAULT_COLLECTION } : {}),
          top_k: 5,
          usable_only: true,
        }),
      });
      renderSearch(data);
    } else {
      const payload = buildRecommendPayload(rawInput);
      if (streamingMode) {
        prepareStreamView("固定化推荐结果");
        const data = await requestNdjsonStream("/api/recommend/by-enzyme/stream", payload, {
          onStatus: updateStreamStatus,
          onDelta: appendStreamDelta,
        });
        renderRecommendation(data);
      } else {
        const data = await requestJson("/api/recommend/by-enzyme", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        renderRecommendation(data);
      }
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
    ...(DEFAULT_COLLECTION ? { collection: DEFAULT_COLLECTION } : {}),
    top_k: STREAM_TOP_K,
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
    ...(DEFAULT_COLLECTION ? { collection: DEFAULT_COLLECTION } : {}),
    top_k: STREAM_TOP_K,
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
  const timeoutId = window.setTimeout(() => controller.abort(), JSON_REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      signal: controller.signal,
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = data?.error?.message || data?.detail?.error?.message || response.statusText;
      throw new Error(typeof message === "string" ? message : JSON.stringify(message));
    }
    return data;
  } catch (error) {
    if (isAbortError(error, controller)) {
      throw new Error(formatTimeoutMessage(JSON_REQUEST_TIMEOUT_MS));
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

async function requestNdjsonStream(path, payload, handlers = {}) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), STREAM_REQUEST_TIMEOUT_MS);
  let firstTokenTimeoutId = null;
  let idleTimeoutId = null;
  let firstTokenReceived = false;
  let firstTokenTimedOut = false;
  let streamIdleTimedOut = false;

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/x-ndjson",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const message = data?.error?.message || data?.detail?.error?.message || response.statusText;
      throw new Error(typeof message === "string" ? message : JSON.stringify(message));
    }
    if (!response.body) {
      throw new Error("当前浏览器不支持流式响应。");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalData = null;
    const resetIdleTimeout = () => {
      clearStreamTimeout(idleTimeoutId);
      idleTimeoutId = window.setTimeout(() => {
        streamIdleTimedOut = true;
        controller.abort("stream_idle_timeout");
      }, STREAM_IDLE_TIMEOUT_MS);
    };
    const handleStreamEvent = (event) => {
      resetIdleTimeout();
      if (event.event === "delta") {
        handlers.onDelta?.(event.delta || "");
      } else if (event.event === "preview") {
        handlers.onPreview?.(event.delta || "", event);
      } else if (event.event === "status") {
        handlers.onStatus?.(event.stage || "processing", event.message || "", event);
        if (event.stage === "generation_start") {
          firstTokenTimeoutId = startFirstTokenTimeout(controller, () => {
            firstTokenTimedOut = true;
          });
        } else if (event.stage === "first_delta") {
          firstTokenReceived = true;
          clearStreamTimeout(firstTokenTimeoutId);
          firstTokenTimeoutId = null;
        }
      } else if (event.event === "retrieval") {
        handlers.onStatus?.(
          "retrieval_done",
          `已检索 ${event.hits_count || 0} 条参考文献 chunk，正在生成建议。`,
          event,
        );
      } else if (event.event === "final") {
        finalData = event.data || null;
        firstTokenReceived = true;
        clearStreamTimeout(firstTokenTimeoutId);
        clearStreamTimeout(idleTimeoutId);
        firstTokenTimeoutId = null;
        idleTimeoutId = null;
        handlers.onStatus?.("finalizing", "正在整理结构化结果。", event);
      } else if (event.event === "error") {
        throw new Error(event.message || "流式响应失败");
      }
    };
    resetIdleTimeout();

    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const rawLine of lines) {
        const line = rawLine.trim();
        if (!line) continue;
        const event = JSON.parse(line);
        handleStreamEvent(event);
      }

      if (done) break;
    }

    if (buffer.trim()) {
      const event = JSON.parse(buffer);
      handleStreamEvent(event);
    }

    if (!finalData) {
      throw new Error("流式响应结束，但没有收到最终结果。");
    }
    handlers.onStatus?.("done", "生成完成");
    return finalData;
  } catch (error) {
    if (isAbortError(error, controller)) {
      if (firstTokenTimedOut && !firstTokenReceived) {
        throw new Error(formatFirstTokenTimeoutMessage());
      }
      if (streamIdleTimedOut) {
        throw new Error(formatStreamIdleTimeoutMessage());
      }
      throw new Error(formatTimeoutMessage(STREAM_REQUEST_TIMEOUT_MS));
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
    clearStreamTimeout(firstTokenTimeoutId);
    clearStreamTimeout(idleTimeoutId);
  }
}

function startFirstTokenTimeout(controller, onTimeout) {
  return window.setTimeout(() => {
    onTimeout?.();
    controller.abort("first_token_timeout");
  }, STREAM_FIRST_TOKEN_TIMEOUT_MS);
}

function clearStreamTimeout(timeoutId) {
  if (timeoutId) {
    window.clearTimeout(timeoutId);
  }
}

function isAbortError(error, controller) {
  if (controller?.signal?.aborted) return true;
  const name = error?.name || "";
  const message = String(error?.message || error || "").toLowerCase();
  return name === "AbortError" || message.includes("aborted") || message.includes("fetch is aborted");
}

function formatTimeoutMessage(timeoutMs) {
  const seconds = Math.round(timeoutMs / 1000);
  return `请求超过 ${seconds} 秒仍未完成。Qwen 生成可能仍在排队或响应较慢，请稍后重试，或先使用证据检索模式确认知识库可用。`;
}

function formatFirstTokenTimeoutMessage() {
  const seconds = Math.round(STREAM_FIRST_TOKEN_TIMEOUT_MS / 1000);
  return `模型生成阶段超过 ${seconds} 秒仍未返回首 token。通常是 SiliconFlow 上游排队、网络/DNS/proxy 问题或模型服务波动；证据检索已完成，可以稍后重试。`;
}

function formatStreamIdleTimeoutMessage() {
  const seconds = Math.round(STREAM_IDLE_TIMEOUT_MS / 1000);
  return `模型流式输出超过 ${seconds} 秒没有新内容。通常是 SiliconFlow stream 中途停顿或网络连接空闲超时；已收到的内容不会继续等待，请重试。`;
}

function setLoading(isLoading, options = {}) {
  const showSteps = options.showSteps !== false;
  sendButton.disabled = isLoading;
  sendButton.textContent = isLoading ? "处理中" : "发送";
  resultPanel.hidden = false;
  resultTitle.textContent = isLoading && showSteps ? "正在检索证据并生成建议" : resultTitle.textContent;
  if (isLoading) {
    loadingStartedAt = Date.now();
    if (showSteps) {
      updateLoadingMessage();
      loadingTimer = window.setInterval(updateLoadingMessage, 1000);
    }
  } else if (loadingTimer) {
    window.clearInterval(loadingTimer);
    loadingTimer = null;
  }
}

function updateLoadingMessage() {
  const seconds = Math.max(0, Math.round((Date.now() - loadingStartedAt) / 1000));
  resultBody.innerHTML = `
    <div class="loading-steps">
      <span>1. Qdrant reference retrieval：通常 &lt; 1 秒</span>
      <span>2. SiliconFlow generation：当前已等待 ${seconds} 秒</span>
      <span>3. Reference rendering：返回后自动展示参考论文</span>
    </div>
    <p class="result-muted">真实 LLM 生成不是卡死，通常需要 10-90 秒；流式生成超过 300 秒会自动报错。</p>
  `;
}

function prepareStreamView(title) {
  streamBuffer = "";
  setReferenceHits([]);
  resultPanel.hidden = false;
  resultTitle.textContent = title;
  resultBody.innerHTML = `
    <div class="stream-status" data-stream-status>准备检索参考文献</div>
    <div class="stream-metrics" data-stream-metrics></div>
    <div class="stream-output live-answer-content" data-stream-output></div>
  `;
}

function updateStreamStatus(stage, message, event = {}) {
  const status = resultBody.querySelector("[data-stream-status]");
  if (!status) return;
  updateStreamMetrics(stage, event);
  const elapsedLabel = event.elapsed_ms !== undefined ? `（${formatElapsedMs(event.elapsed_ms)}）` : "";
  if (stage === "generation_start") {
    status.textContent = `正在生成建议${elapsedLabel}`;
    return;
  }
  if (stage === "model_reasoning") {
    status.textContent = `模型已开始推理，等待可见 token${elapsedLabel}`;
    return;
  }
  if (stage === "first_delta") {
    status.textContent = `首 token 已到达${elapsedLabel}`;
    return;
  }
  if (stage === "retrieval_done") {
    status.textContent = `${message || "证据检索完成"}${elapsedLabel}`;
    return;
  }
  if (stage === "finalizing") {
    status.textContent = `${message || "正在整理结构化结果"}${elapsedLabel}`;
    return;
  }
  if (stage === "done") {
    status.textContent = message || "生成完成";
    return;
  }
  status.textContent = message || "处理中";
}

function updateStreamMetrics(stage, event = {}) {
  const metrics = resultBody.querySelector("[data-stream-metrics]");
  if (!metrics || event.elapsed_ms === undefined) return;
  const labelByStage = {
    retrieval_done: "retrieval",
    model_reasoning: "reasoning",
    first_delta: "first token",
    finalizing: "final",
  };
  const label = labelByStage[stage];
  if (!label) return;
  let item = metrics.querySelector(`[data-stream-metric="${stage}"]`);
  if (!item) {
    item = document.createElement("span");
    item.setAttribute("data-stream-metric", stage);
    metrics.appendChild(item);
  }
  item.textContent = `${label}: ${formatElapsedMs(event.elapsed_ms)}`;
}

function formatElapsedMs(value) {
  const ms = Number(value);
  if (!Number.isFinite(ms)) return "-";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function appendStreamDelta(delta) {
  streamBuffer += delta;
  const output = resultBody.querySelector("[data-stream-output]");
  if (!output) return;
  output.innerHTML = renderMarkdownLite(streamBuffer);
  output.scrollTop = output.scrollHeight;
}

function renderRecommendation(data) {
  setReferenceHits(data.evidence_hits);
  resultTitle.textContent = "固定化推荐结果";
  resultBody.innerHTML = [
    renderMeta(data.generator_provider, data.generator_model, data.limitations),
    renderLiveAnswer(data),
    renderReferenceSection(data.evidence_hits),
  ].join("");
}

function renderOptimization(data) {
  setReferenceHits(data.evidence_hits);
  resultTitle.textContent = "配方优化建议";
  resultBody.innerHTML = [
    renderMeta(data.generator_provider, data.generator_model, data.limitations),
    renderLiveAnswer(data),
    renderReferenceSection(data.evidence_hits),
  ].join("");
}

function renderSearch(data) {
  setReferenceHits(data.hits);
  resultTitle.textContent = "证据检索结果";
  const hits = data.hits || [];
  resultBody.innerHTML = hits.length
    ? hits
        .map((hit, index) => renderReferenceCard(hit, index, { score: true }))
        .join("")
    : '<p class="result-muted">没有检索到 evidence。</p>';
}

function handleResultBodyClick(event) {
  const referenceButton = event.target.closest("[data-reference-key]");
  if (!referenceButton) return;
  event.preventDefault();
  const hit = activeReferenceLookup.get(referenceButton.dataset.referenceKey || "");
  if (hit) {
    openReferenceModal(hit);
  }
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

function renderLiveAnswer(data) {
  if (data.generation_json || !data.generation_content) return "";
  return `
    <section class="live-answer">
      <strong>live answer</strong>
      <div class="live-answer-content">${renderMarkdownLite(data.generation_content)}</div>
    </section>
  `;
}

function renderMarkdownLite(value) {
  const lines = String(value || "").replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let paragraph = [];
  let listItems = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push(`<p>${renderInlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length) return;
    blocks.push(`<ul>${listItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</ul>`);
    listItems = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }

    const bulletMatch = line.match(/^[-*]\s+(.+)$/);
    if (bulletMatch) {
      flushParagraph();
      listItems.push(bulletMatch[1].trim());
      continue;
    }

    flushList();
    paragraph.push(line);
  }

  flushParagraph();
  flushList();
  return blocks.join("");
}

function renderInlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/(^|[^_])_([^_\n]+)_(?!_)/g, "$1<em>$2</em>")
    .replace(/\[(\d+)\]/g, (_match, rawIndex) => renderInlineCitation(Number(rawIndex)));
}

function renderInlineCitation(index) {
  if (!Number.isInteger(index) || index < 1 || index > activeReferenceHits.length) {
    return `[${escapeHtml(index)}]`;
  }
  return `<a class="inline-citation" href="#${referenceAnchorId(index)}">[${index}]</a>`;
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

function renderCitationList(title, items) {
  const normalizedItems = Array.isArray(items) ? items : items ? [items] : [];
  if (!normalizedItems.length) return "";
  return `
    <div class="result-list citation-list">
      <b>${escapeHtml(title)}</b>
      ${normalizedItems
        .map((item) => {
          const label = formatValue(item);
          const hit = activeReferenceLookup.get(label);
          if (!hit) {
            return `<span>${escapeHtml(label)}</span>`;
          }
          return `<button class="citation-chip" type="button" data-reference-key="${escapeHtml(label)}">${escapeHtml(formatReferenceCitation(hit))}</button>`;
        })
        .join("")}
    </div>
  `;
}

function setReferenceHits(hits) {
  activeReferenceHits = Array.isArray(hits) ? hits.filter(Boolean) : [];
  activeReferenceLookup = new Map();
  activeReferenceHits.forEach((hit, index) => {
    const key = referenceKey(hit, index);
    activeReferenceLookup.set(key, hit);
    if (hit.source_id) activeReferenceLookup.set(String(hit.source_id), hit);
    if (hit.citation) activeReferenceLookup.set(String(hit.citation), hit);
    activeReferenceLookup.set(formatReferenceCitation(hit), hit);
  });
}

function renderReferenceSection(hits) {
  const normalizedHits = Array.isArray(hits) ? hits.filter(Boolean) : [];
  if (!normalizedHits.length) return "";
  return `
    <section class="reference-section">
      <div class="reference-section-head">
        <b>参考论文</b>
        <span>${normalizedHits.length} chunks</span>
      </div>
      <div class="reference-grid">
        ${normalizedHits.map((hit, index) => renderReferenceCard(hit, index)).join("")}
      </div>
    </section>
  `;
}

function renderReferenceCard(hit, index, options = {}) {
  const key = referenceKey(hit, index);
  const citation = formatReferenceCitation(hit);
  const text = cleanDisplayText(getReferenceText(hit));
  const preview = truncateDisplayText(text, 320);
  const pdfName = hit.source_pdf || parsePdfName(citation) || "-";
  const pdfUrl = buildPdfUrl(hit);
  const referenceIndex = index + 1;
  return `
    <article class="reference-card" id="${referenceAnchorId(referenceIndex)}">
      <div class="reference-card-head">
        <button class="reference-title" type="button" data-reference-key="${escapeHtml(key)}">
          #${referenceIndex} ${escapeHtml(citation || "reference")}
        </button>
        ${options.score ? `<span>${Number(hit.score || 0).toFixed(3)}</span>` : `<span>${escapeHtml(hit.record_type || hit.point_type || "chunk")}</span>`}
      </div>
      <button class="reference-snippet" type="button" data-reference-key="${escapeHtml(key)}">
        ${escapeHtml(preview || "无 chunk 文本")}
      </button>
      <p class="reference-file">
        文件：
        <a href="${escapeHtml(pdfUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(pdfName)}</a>
      </p>
    </article>
  `;
}

function openReferenceModal(hit) {
  if (!referenceModal) return;
  activeReferenceHit = hit;
  activeReferenceExpanded = false;
  renderReferenceModalContent();
  referenceModal.hidden = false;
  document.body.classList.add("modal-open");
}

function closeReferenceModal() {
  if (!referenceModal) return;
  referenceModal.hidden = true;
  document.body.classList.remove("modal-open");
  activeReferenceHit = null;
  activeReferenceExpanded = false;
}

function renderReferenceModalContent() {
  if (!activeReferenceHit || !referenceModalTitle || !referenceModalMeta || !referenceModalText || !referenceModalFooter) {
    return;
  }
  const hit = activeReferenceHit;
  const citation = formatReferenceCitation(hit);
  const text = cleanDisplayText(getReferenceText(hit)) || "无 chunk 文本";
  const isLong = text.length > CHUNK_PREVIEW_LIMIT;
  const visibleText = isLong && !activeReferenceExpanded ? `${text.slice(0, CHUNK_PREVIEW_LIMIT).trimEnd()}...` : text;
  const pdfName = hit.source_pdf || parsePdfName(citation) || "-";
  const pdfUrl = buildPdfUrl(hit);

  referenceModalTitle.textContent = citation || "参考论文";
  referenceModalMeta.innerHTML = `
    <span>${escapeHtml(hit.record_type || hit.point_type || "chunk")}</span>
    <span>${escapeHtml(formatPageLabel(hit))}</span>
    <span>score ${Number(hit.score || 0).toFixed(3)}</span>
  `;
  referenceModalText.innerHTML = renderReferenceText(visibleText);
  referenceModalFooter.innerHTML = `
    ${isLong ? `<button class="ghost-button" type="button" data-reference-more>${activeReferenceExpanded ? "收起" : "更多"}</button>` : ""}
    <a class="pdf-file-link" href="${escapeHtml(pdfUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(pdfName)}</a>
  `;
}

function referenceKey(hit, index) {
  return String(hit.source_id || hit.citation || `${hit.source_pdf || "reference"}-${hit.page_start || "p"}-${index}`);
}

function referenceAnchorId(index) {
  return `reference-${index}`;
}

function formatReferenceCitation(hit) {
  const pdfName = hit.source_pdf || "-";
  const pageLabel = formatPageLabel(hit);
  return pageLabel === "page -" ? pdfName : `${pdfName}:${pageLabel.replace("page ", "p")}`;
}

function formatPageLabel(hit) {
  if (hit.page_start === null || hit.page_start === undefined) return "page -";
  const pageStart = displayPageNumber(hit.page_start);
  if (hit.page_end === null || hit.page_end === undefined || hit.page_end === hit.page_start) {
    return `page ${pageStart}`;
  }
  return `page ${pageStart}-${displayPageNumber(hit.page_end)}`;
}

function parsePdfName(citation) {
  const match = String(citation || "").match(/^(.+?\.pdf)(?::p\d+(?:-p\d+)?)?$/i);
  return match ? match[1] : null;
}

function buildPdfUrl(hit) {
  const citation = hit.citation || "";
  const pdfName = hit.source_pdf || parsePdfName(citation);
  if (!pdfName) return "#";
  const page =
    hit.page_start === null || hit.page_start === undefined
      ? parsePageStart(citation)
      : displayPageNumber(hit.page_start);
  const baseUrl = `${API_BASE_URL}/api/pdfs/${encodeURIComponent(pdfName)}`;
  return page ? `${baseUrl}#page=${encodeURIComponent(page)}` : baseUrl;
}

function parsePageStart(citation) {
  const match = String(citation || "").match(/:p(\d+)/i);
  return match ? Number(match[1]) : null;
}

function getReferenceText(hit) {
  return String(hit.source_chunk_text || hit.text || "");
}

function formatCandidateTitle(item) {
  const carrier = cleanDisplayText(item.carrier);
  if (carrier && carrier !== "-") return truncateDisplayText(carrier, 96);

  const method = cleanDisplayText(item.immobilization_method);
  if (method && method !== "-") return truncateDisplayText(method, 96);

  const citation = Array.isArray(item.citations) ? item.citations.find(Boolean) : item.citations;
  if (citation) return `Evidence ${truncateDisplayText(formatValue(citation), 72)}`;

  return "Candidate";
}

function cleanDisplayText(value) {
  return String(value || "")
    .replace(/\$\s*\^\s*\{\s*-\s*1\s*\}/g, "-1")
    .replace(/\$\s*([^$]+?)\s*\$/g, "$1")
    .replace(/\\mu\b/g, "µ")
    .replace(/\\circ\b/g, "°")
    .replace(/\\cdot\b/g, "·")
    .replace(/\\quad\b|\\,/g, " ")
    .replace(/\\mathsf\s*\{\s*p\s*H\s*\}/gi, "pH")
    .replace(/\\(?:mathrm|text|mathbf|mathit|operatorname)\s*\{([^{}]*)\}/g, "$1")
    .replace(/\\(?:mathrm|text|mathbf|mathit|operatorname)\b/g, "")
    .replace(/\^\s*\{\s*([^{}]+?)\s*\}/g, "^$1")
    .replace(/_\s*\{\s*([^{}]+?)\s*\}/g, "_$1")
    .replace(/\bU\s*i\s*O\b/g, "UiO")
    .replace(/\bN\s*H\b/g, "NH")
    .replace(/\bF\s*e\b/g, "Fe")
    .replace(/\bO\s*_?4\b/g, "O4")
    .replace(/\bL\s*\^\s*-\s*1\b/g, "L^-1")
    .replace(/\bm\s*L\b/g, "mL")
    .replace(/µ\s*L\b/g, "µL")
    .replace(/µ\s*g\b/g, "µg")
    .replace(/µ\s*m\b/g, "µm")
    .replace(/([A-Za-z])\s+_([0-9A-Za-z+-]+)/g, "$1_$2")
    .replace(/\\[a-zA-Z]+/g, " ")
    .replace(/\$+/g, " ")
    .replace(/[{}]/g, "")
    .replace(/\s*_\s*/g, "_")
    .replace(/\s*\^\s*/g, "^")
    .replace(/\s*@\s*/g, "@")
    .replace(/\s*\/\s*/g, "/")
    .replace(/\s*·\s*/g, "·")
    .replace(/·\s*([0-9])\s+([0-9])\s*·/g, "·$1$2·")
    .replace(/([=(])\s*([0-9])\s*\.\s*([0-9])\s*([),])/g, "$1$2.$3$4")
    .replace(/([0-9])\s+(\))/g, "$1$2")
    .replace(/\s+([,.;:])/g, "$1")
    .replace(/([,(])\s+/g, "$1")
    .replace(/\s+([)])/g, "$1")
    .replace(/\b(mg|g|mL|L|mol|mmol|µL|µg|µm)\s+-\s*1\b/g, "$1^-1")
    .replace(/\)(?=[A-Za-z])/g, ") ")
    .replace(/,(?=[A-Za-z])/g, ", ")
    .replace(/,(?=\d+\s*(?:mg|g|mL|L|mol|mmol|µL|µg|µm)\b)/g, ", ")
    .replace(/([0-9])(?=µ(?:L|g|m)\b)/g, "$1 ")
    .replace(/\bp\s*H\b/gi, "pH")
    .replace(/\s+/g, " ")
    .trim();
}

function truncateDisplayText(value, limit) {
  const text = String(value || "").trim();
  if (!text || text.length <= limit) return text;
  return `${text.slice(0, limit).trimEnd()}...`;
}

function displayPageNumber(pageIndex) {
  const number = Number(pageIndex);
  return Number.isFinite(number) ? number + 1 : pageIndex;
}

function safeNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatInteger(value) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function renderReferenceText(text) {
  const table = parseLinearizedTable(text);
  if (!table) {
    return `<pre>${escapeHtml(text)}</pre>`;
  }
  return `
    <div class="extracted-table-wrap">
      <table class="extracted-table">
        <thead>
          <tr>${table.columns.map((column) => `<th>${escapeHtml(cleanMathText(column))}</th>`).join("")}</tr>
        </thead>
        <tbody>
          ${table.rows
            .map((row) => `<tr>${table.columns.map((_, index) => `<td>${escapeHtml(cleanMathText(row[index] || ""))}</td>`).join("")}</tr>`)
            .join("")}
        </tbody>
      </table>
      <details class="raw-reference-text">
        <summary>原始提取文本</summary>
        <pre>${escapeHtml(text)}</pre>
      </details>
    </div>
  `;
}

function parseLinearizedTable(text) {
  const lines = String(text || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (!lines.length || !lines[0].startsWith("Columns:")) return null;

  const columns = lines[0]
    .replace(/^Columns:\s*/, "")
    .split("|")
    .map((column) => column.trim())
    .filter(Boolean);
  if (!columns.length) return null;

  const rows = [];
  for (const line of lines.slice(1)) {
    const match = line.match(/^Row\s+\d+:\s*(.+)$/i);
    if (!match) continue;
    const body = match[1].trim();
    const cells = columns.map((column, index) => {
      const nextColumn = columns[index + 1];
      const pattern = nextColumn
        ? new RegExp(`${escapeRegExp(column)}:\\s*([\\s\\S]*?);\\s*${escapeRegExp(nextColumn)}:`, "i")
        : new RegExp(`${escapeRegExp(column)}:\\s*([\\s\\S]*)$`, "i");
      const cellMatch = body.match(pattern);
      return cellMatch ? cellMatch[1].trim() : "";
    });
    if (cells.some(Boolean)) {
      rows.push(cells);
    }
  }

  return rows.length ? { columns, rows } : null;
}

function cleanMathText(value) {
  return String(value)
    .replaceAll("$K _ { m }$", "Km")
    .replaceAll("$V _ { m a x }$", "Vmax")
    .replaceAll("$V _ { m a x } / K _ { m }$", "Vmax / Km");
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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
