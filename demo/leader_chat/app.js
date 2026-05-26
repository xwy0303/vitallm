const messages = document.querySelector("#messages");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#user-input");
const quickActions = document.querySelectorAll("[data-prompt]");

const answers = {
  recommendation: {
    title: "推荐结论",
    body:
      "对 Burkholderia cepacia lipase (BCL)，当前 B10 证据支持优先展示 hierarchical mesoporous ZIF-8 作为 MOF 固定化载体，固定化方式为 adsorption。该组合在 biodiesel production 场景下给出了较完整的配方条件和性能指标，因此适合进入第一版候选推荐集。",
    citation: "B10 · enzyme_identity + immobilization_strategy + table_comparison_row",
  },
  optimization: {
    title: "配方优化方向",
    body:
      "如果目标是提高 biodiesel yield，可以把当前条件向 B10 的已验证条件靠近：pH 7.5、25 degC、BCL loading 700 mg、adsorption time 30 min，并重点记录 substrate、alcohol donor、water content 和复用轮次。当前系统会把这些建议标记为 evidence-backed suggestion，而不是全局最优结论。",
    citation: "B10 · formulation_condition + performance_metric",
  },
  review: {
    title: "学生参与方式",
    body:
      "学生后续不只是收论文，而是进入 review queue 校验知识库。系统会自动标出 OCR 重复、百分比异常、表格数值异常和需要回看图片的 evidence；学生负责确认、修正或标记不可用，最终形成 curated knowledge base。",
    citation: "review_queue · 24 flagged records in B10 smoke test",
  },
  fallback: {
    title: "当前可回答范围",
    body:
      "这个演示前端目前接入的是 B10 smoke test 的本地证据样例。它能展示最终问答形态：推荐结论、配方建议、证据引用和人工复核入口。扩展到更多论文后，回答会由向量检索和 LLM 共同生成。",
    citation: "MVP demo · local evidence only",
  },
};

function appendMessage(role, html) {
  const node = document.createElement("article");
  node.className = `message ${role}`;
  node.innerHTML = html;
  messages.appendChild(node);
  messages.scrollTop = messages.scrollHeight;
}

function selectAnswer(text) {
  const normalized = text.toLowerCase();
  if (normalized.includes("学生") || normalized.includes("review")) {
    return answers.review;
  }
  if (
    normalized.includes("优化") ||
    normalized.includes("配方") ||
    normalized.includes("ph") ||
    normalized.includes("yield")
  ) {
    return answers.optimization;
  }
  if (
    normalized.includes("burkholderia") ||
    normalized.includes("bcl") ||
    normalized.includes("脂肪酶") ||
    normalized.includes("固定化剂") ||
    normalized.includes("zif")
  ) {
    return answers.recommendation;
  }
  return answers.fallback;
}

function ask(text) {
  const trimmed = text.trim();
  if (!trimmed) return;
  appendMessage("user", escapeHtml(trimmed));
  const answer = selectAnswer(trimmed);
  appendMessage(
    "assistant",
    `<strong>${answer.title}</strong><br>${answer.body}<br><span class="citation">${answer.citation}</span>`,
  );
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (char) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    };
    return entities[char];
  });
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  ask(input.value);
  input.value = "";
  input.focus();
});

quickActions.forEach((button) => {
  button.addEventListener("click", () => ask(button.dataset.prompt || ""));
});

appendMessage(
  "assistant",
  '<strong>系统已加载 B10 smoke test 证据。</strong><br>你可以直接问“BCL 推荐什么固定化剂”或“配方怎么优化”。<br><span class="citation">Demo mode · evidence-grounded</span>',
);
