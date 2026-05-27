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
const paperSelector = document.querySelector("[data-paper-selector]");
const paperSearch = document.querySelector("[data-paper-search]");
const paperOptions = document.querySelector("[data-paper-options]");
const selectedPaperBox = document.querySelector("[data-selected-paper]");
const paperCount = document.querySelector("[data-paper-count]");

const JSON_REQUEST_TIMEOUT_MS = 120000;
const STREAM_REQUEST_TIMEOUT_MS = 300000;
const STREAM_FIRST_TOKEN_TIMEOUT_MS = 45000;
const STREAM_IDLE_TIMEOUT_MS = 45000;
const STREAM_TOP_K = 6;
const SEARCH_TOP_K = 8;

let activeMode = "recommend";
let loadingTimer = null;
let loadingStartedAt = 0;
let streamBuffer = "";
let activeReferenceHits = [];
let activeReferenceLookup = new Map();
let activeReferenceHit = null;
let activeReferenceExpanded = false;
let documentCatalog = [];
let selectedPaper = null;

const CHUNK_PREVIEW_LIMIT = 900;

modeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    setActiveMode(button.dataset.mode || "recommend");
  });
});

promptButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (button.dataset.modePrompt) {
      setActiveMode(button.dataset.modePrompt);
    }
    textarea.value = button.dataset.prompt || button.textContent.trim();
    textarea.focus();
  });
});

paperSearch?.addEventListener("input", () => {
  renderPaperOptions(paperSearch.value);
});

paperOptions?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-paper-id]");
  if (!button) return;
  event.preventDefault();
  const documentId = button.dataset.paperId || "";
  const item = documentCatalog.find((document) => document.document_id === documentId);
  if (item) {
    selectPaper(item);
  }
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
loadDocumentCatalog();

function setActiveMode(mode) {
  activeMode = mode || "recommend";
  modeButtons.forEach((item) => item.classList.toggle("active", item.dataset.mode === activeMode));
  if (paperSelector) {
    paperSelector.hidden = activeMode !== "paper";
  }
  if (activeMode === "optimize") {
    textarea.placeholder =
      '输入配方 JSON，例如：{"enzyme_loading":{"value":500,"unit":"mg"},"buffer":{"pH":7},"immobilization_conditions":{"time":{"value":60,"unit":"min"}}}';
  } else if (activeMode === "search") {
    textarea.placeholder = "输入证据检索 query，例如：soybean oil ethanol yield 93.4 8 cycles last yield";
  } else if (activeMode === "paper") {
    textarea.placeholder = "例如：B10论文对酶固定化剂的优化过程是怎么样的？";
    if (!documentCatalog.length) {
      loadDocumentCatalog();
    }
  } else {
    textarea.placeholder =
      "例如：Burkholderia cepacia lipase，用于大豆油乙醇酯交换制备 biodiesel，推荐固定化载体和条件。";
  }
}

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

async function loadDocumentCatalog() {
  if (!paperSelector) return;
  try {
    const data = await requestJson(`/api/documents${DEFAULT_COLLECTION ? `?collection=${encodeURIComponent(DEFAULT_COLLECTION)}` : ""}`, {
      method: "GET",
    });
    documentCatalog = Array.isArray(data.documents) ? data.documents : [];
    if (paperCount) {
      paperCount.textContent = `${documentCatalog.length} 篇可选论文`;
    }
    renderPaperOptions(paperSearch?.value || "");
  } catch (_error) {
    documentCatalog = [];
    if (paperCount) {
      paperCount.textContent = "文献目录加载失败";
    }
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
          top_k: SEARCH_TOP_K,
          usable_only: true,
        }),
      });
      renderSearch(data);
    } else {
      const payload = buildRecommendPayload(rawInput);
      if (streamingMode) {
        prepareStreamView(activeMode === "paper" || payload.objective === "answer_paper_process_question" ? "论文问答结果" : "固定化推荐结果");
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
  const paperIntent = activeMode === "paper" || hasPaperQuestionIntent(rawInput);
  const recommendationIntent = !paperIntent && hasRecommendationIntent(rawInput);
  const constraints = paperIntent && selectedPaper ? [paperConstraint(selectedPaper)] : [];
  return {
    enzyme_name: extractEnzymeName(rawInput),
    objective: paperIntent
      ? "answer_paper_process_question"
      : recommendationIntent
        ? "recommend_best_immobilization_agent"
        : "answer_evidence_question",
    application_context: rawInput,
    constraints,
    ...(DEFAULT_COLLECTION ? { collection: DEFAULT_COLLECTION } : {}),
    top_k: paperIntent ? Math.max(STREAM_TOP_K, 12) : STREAM_TOP_K,
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

const ENZYME_NAME_ALIASES = [
  {
    pattern: /伯克霍尔德(?:菌)?脂肪酶|伯克霍尔德|Burkholderia(?:\s+cepacia)?\s+lipase|\bBCL\b/i,
    canonical: "Burkholderia cepacia lipase",
  },
  {
    pattern: /假单胞菌脂肪酶|假单胞菌|Pseudomonas(?:\s+\w+)?\s+lipase|\bPFL\b/i,
    canonical: "Pseudomonas lipase",
  },
  {
    pattern: /南极假丝酵母脂肪酶\s*B?|南极假丝酵母|Candida\s+antarctica\s+lipase\s+B|\bCAL-?B\b/i,
    canonical: "Candida antarctica lipase B",
  },
  {
    pattern: /皱褶假丝酵母脂肪酶|皱褶假丝酵母|Candida\s+rugosa\s+lipase|\bCRL\b/i,
    canonical: "Candida rugosa lipase",
  },
  {
    pattern: /猪胰(?:腺)?脂肪酶|porcine\s+pancreatic\s+lipase|\bPPL\b/i,
    canonical: "porcine pancreatic lipase",
  },
  {
    pattern: /米根霉脂肪酶|米黑根毛霉脂肪酶|Rhizomucor\s+miehei\s+lipase|\bRML\b/i,
    canonical: "Rhizomucor miehei lipase",
  },
  {
    pattern: /疏棉状嗜热丝孢菌脂肪酶|嗜热真菌脂肪酶|Thermomyces\s+lanuginosus\s+lipase|\bTLL\b/i,
    canonical: "Thermomyces lanuginosus lipase",
  },
];

function extractEnzymeName(rawInput) {
  const value = String(rawInput || "").trim();
  const matchedAlias = ENZYME_NAME_ALIASES.find((item) => item.pattern.test(value));
  if (matchedAlias) return matchedAlias.canonical;

  const knownNames = [
    "Burkholderia cepacia lipase",
    "Candida antarctica lipase B",
    "Candida rugosa lipase",
    "Pseudomonas lipase",
    "porcine pancreatic lipase",
    "Rhizomucor miehei lipase",
    "Thermomyces lanuginosus lipase",
  ];
  const lower = value.toLowerCase();
  const match = knownNames.find((name) => lower.includes(name.toLowerCase()));
  return match || value.split(/[，,。.\n]/)[0].trim();
}

function hasRecommendationIntent(rawInput) {
  const value = String(rawInput || "").toLowerCase();
  if (hasPaperQuestionIntent(value)) return false;
  return /recommend|recommendation|best|optimal|optimise|optimize|suggest|should|better|prefer|推荐|最适合|最佳|最优|优化|建议|应该|该用|更好|效果好|方案/.test(value);
}

function hasPaperQuestionIntent(rawInput) {
  const value = String(rawInput || "").toLowerCase();
  const hasPaperHint = /\b[a-z]\d{1,3}(?:\.pdf)?\b/.test(value) || /paper|article|study|pdf|论文|文章|文献|这篇/.test(value);
  const hasProcessHint = /optimization process|optimisation process|procedure|workflow|optimi[sz]e|优化过程|优化流程|固定化剂.*优化|流程|过程|步骤/.test(value);
  return hasPaperHint && hasProcessHint;
}

function paperConstraint(item) {
  return [
    `document_id:${item.document_id}`,
    `source_pdf:${item.source_pdf}`,
    item.title_candidate ? `title:${item.title_candidate}` : "",
  ]
    .filter(Boolean)
    .join(" ");
}

function renderPaperOptions(query = "") {
  if (!paperOptions) return;
  const normalizedQuery = normalizePaperText(query);
  const options = documentCatalog
    .map((item) => ({ item, score: paperMatchScore(item, normalizedQuery) }))
    .filter(({ score }) => !normalizedQuery || score > 0)
    .sort((left, right) => right.score - left.score || naturalDocumentCompare(left.item.document_id, right.item.document_id))
    .slice(0, 8);
  if (!options.length) {
    paperOptions.innerHTML = '<p class="result-muted">没有匹配的论文。可直接在问题里输入 A12 / B10 / PDF 文件名。</p>';
    return;
  }
  paperOptions.innerHTML = options
    .map(({ item }) => {
      const selected = selectedPaper?.document_id === item.document_id;
      return `
        <button class="paper-option${selected ? " selected" : ""}" type="button" data-paper-id="${escapeHtml(item.document_id)}">
          <strong>${escapeHtml(item.document_id)} · ${escapeHtml(item.source_pdf || "-")}</strong>
          <span>${escapeHtml(truncateDisplayText(item.title_candidate || "无标题候选", 140))}</span>
        </button>
      `;
    })
    .join("");
}

function selectPaper(item) {
  selectedPaper = item;
  if (selectedPaperBox) {
    selectedPaperBox.hidden = false;
    selectedPaperBox.innerHTML = `
      <strong>${escapeHtml(item.document_id)} · ${escapeHtml(item.source_pdf || "-")}</strong>
      <span>${escapeHtml(truncateDisplayText(item.title_candidate || "无标题候选", 180))}</span>
      <button type="button" data-clear-paper>清除</button>
    `;
    selectedPaperBox.querySelector("[data-clear-paper]")?.addEventListener("click", () => {
      selectedPaper = null;
      selectedPaperBox.hidden = true;
      renderPaperOptions(paperSearch?.value || "");
    });
  }
  if (paperSearch) {
    paperSearch.value = item.document_id;
  }
  renderPaperOptions(paperSearch?.value || "");
}

function paperMatchScore(item, normalizedQuery) {
  if (!normalizedQuery) return 1;
  const aliases = [item.document_id, item.source_pdf, item.title_candidate, ...(item.aliases || [])]
    .filter(Boolean)
    .map(normalizePaperText);
  let best = 0;
  for (const alias of aliases) {
    if (!alias) continue;
    if (alias === normalizedQuery) best = Math.max(best, 3);
    if (alias.includes(normalizedQuery) || normalizedQuery.includes(alias)) best = Math.max(best, 2);
    const queryTokens = new Set(normalizedQuery.split(/\s+/).filter(Boolean));
    const aliasTokens = new Set(alias.split(/\s+/).filter(Boolean));
    const overlap = Array.from(queryTokens).filter((token) => aliasTokens.has(token)).length;
    if (overlap) best = Math.max(best, overlap / Math.max(queryTokens.size, 1));
  }
  return best;
}

function normalizePaperText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/\.pdf\b/g, "")
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function naturalDocumentCompare(left, right) {
  const a = String(left || "").match(/^([A-Za-z]+)(\d+)$/);
  const b = String(right || "").match(/^([A-Za-z]+)(\d+)$/);
  if (a && b && a[1] === b[1]) return Number(a[2]) - Number(b[2]);
  return String(left || "").localeCompare(String(right || ""));
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
  resultTitle.textContent =
    data.objective === "answer_paper_process_question"
      ? "论文问答结果"
      : data.objective === "answer_evidence_question"
        ? "证据问答结果"
        : "固定化推荐结果";
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
  const paperButton = event.target.closest("[data-paper-followup]");
  if (paperButton) {
    event.preventDefault();
    const documentId = paperButton.dataset.paperFollowup || "";
    const item =
      documentCatalog.find((document) => document.document_id === documentId) || {
        document_id: documentId,
        source_pdf: `${documentId}.pdf`,
        title_candidate: "",
        aliases: [documentId, `${documentId}.pdf`],
      };
    selectPaper(item);
    setActiveMode("paper");
    textarea.focus();
    return;
  }
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
        ${hit.document_id ? `<button class="paper-followup" type="button" data-paper-followup="${escapeHtml(hit.document_id)}">围绕这篇论文继续问</button>` : ""}
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
  const text = cleanReferenceText(getReferenceText(hit)) || "无 chunk 文本";
  const isLong = text.length > CHUNK_PREVIEW_LIMIT;
  const renderedText = isReferenceTableText(text) ? text : isLong && !activeReferenceExpanded ? `${text.slice(0, CHUNK_PREVIEW_LIMIT).trimEnd()}...` : text;
  const pdfName = hit.source_pdf || parsePdfName(citation) || "-";
  const pdfUrl = buildPdfUrl(hit);

  referenceModalTitle.textContent = citation || "参考论文";
  referenceModalMeta.innerHTML = `
    <span>${escapeHtml(hit.record_type || hit.point_type || "chunk")}</span>
    <span>${escapeHtml(formatPageLabel(hit))}</span>
    <span>score ${Number(hit.score || 0).toFixed(3)}</span>
  `;
  referenceModalText.innerHTML = renderReferenceText(renderedText);
  referenceModalFooter.innerHTML = `
    ${isLong && !isReferenceTableText(text) ? `<button class="ghost-button" type="button" data-reference-more>${activeReferenceExpanded ? "收起" : "更多"}</button>` : ""}
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
    .split("\n")
    .map((line) => cleanDisplayLine(line))
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

function cleanReferenceText(value) {
  return String(value || "")
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => cleanDisplayLine(line))
    .join("\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function cleanDisplayLine(value) {
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
      ${table.caption ? `<p class="extracted-table-caption">${escapeHtml(cleanMathText(table.caption))}</p>` : ""}
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

function isReferenceTableText(text) {
  return /\bColumns:\s+/i.test(String(text || "")) && /\bRow\s+\d+:\s+/i.test(String(text || ""));
}

function parseLinearizedTable(text) {
  const source = String(text || "").trim();
  const columnsMatch = source.match(/\bColumns:\s*/i);
  if (!columnsMatch) return null;

  const columnsStart = columnsMatch.index + columnsMatch[0].length;
  const beforeColumns = source.slice(0, columnsMatch.index).trim();
  const afterColumns = source.slice(columnsStart);
  const firstRowMatch = afterColumns.match(/\bRow\s+\d+:\s*/i);
  if (!firstRowMatch) return null;

  const columnsText = afterColumns.slice(0, firstRowMatch.index).trim();
  const rowsText = afterColumns.slice(firstRowMatch.index).trim();
  const columns = columnsText
    .split("|")
    .map((column) => column.trim())
    .filter(Boolean);
  if (!columns.length) return null;

  const rows = [];
  for (const body of splitLinearizedRows(rowsText)) {
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

  return rows.length ? { caption: beforeColumns, columns, rows } : null;
}

function splitLinearizedRows(rowsText) {
  const matches = Array.from(String(rowsText || "").matchAll(/\bRow\s+\d+:\s*/gi));
  return matches
    .map((match, index) => {
      const start = match.index + match[0].length;
      const end = matches[index + 1]?.index ?? rowsText.length;
      return rowsText.slice(start, end).trim();
    })
    .filter(Boolean);
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
