# 生物酶固定化 RAG 人工复核规范

适用对象：0 基础研究生。目标是把机器抽取的可疑 evidence 校正成可追溯、可入库、可用于 RAG ranking 的结构化证据。

## 1. 复核目标

人工复核只做三件事：

1. 判断 evidence 是否与 PDF 原文一致。
2. 修正 OCR、表格错列、单位、小数点、reference、enzyme/support 等字段错误。
3. 对无法确认或来源损坏的条目明确 reject，避免错误事实进入 RAG。

不要做以下事情：

- 不凭常识补全 PDF 中没有写明的信息。
- 不把不同论文、不同表格、不同实验条件混在同一条 evidence 里。
- 不接受 placeholder 页、坏表、无法定位来源的内容。
- 不为了让数据“看起来合理”修改数值；必须以 PDF 可见内容为准。

## 2. 本次复核包范围

- evidence 级待复核：1142 条。
- source QA 条目：103 条。
- 表格相关条目：1059 条。
- placeholder 页：34 页。

优先级含义：

- `P0`：严重来源问题，通常 reject 或禁止入库。
- `P1`：表格/数值/单位/reference 高风险，必须优先处理。
- `P2`：OCR 重复、轻中度质量问题。
- `P3`：低风险字段确认。

## 3. 需要打开哪些文件

1. `manual_review_sop.md`：本规范。
2. `manual_review_priority_p0_p1.csv`：先处理这个。
3. `manual_review_items.csv`：完整 evidence 复核表。
4. `bad_table_review.csv`：专门查表格错列、坏表。
5. `placeholder_pages.csv`：只用于排除，不用于录入证据。

CSV 可以用 Excel、WPS 或 LibreOffice 打开。打开后不要删除原始列，只填写空白列。

## 4. 每条 evidence 的标准操作

对 `manual_review_items.csv` 的每一行，按顺序做：

1. 看 `priority`，优先做 `P0` 和 `P1`。
2. 打开 `pdf_path`。
3. 跳到 `page_start_1based`；如果有 `page_end_1based`，检查整个页码范围。
4. 在 PDF 中找到 `section`、表格 caption 或 `evidence_span` 对应文字。
5. 对照 `record_type`、`extracted_json`、`metrics_json`。
6. 填写 `student_decision`：
   - `accept`：PDF 可验证，字段和数值都正确。
   - `edit`：PDF 可验证，但字段/数值/单位/reference 有错，需要修正。
   - `reject`：PDF 无法验证、来源是 placeholder、表格错到无法恢复、字段没有依据。
   - `needs_engineer`：你能确认 PDF 有事实，但当前行没有合适 evidence_id 或需要新增人工 evidence。
7. 填写 `reviewer` 和 `review_notes`。不要留空。

## 5. accept / edit / reject 判定标准

### accept

同时满足：

- PDF 中能看到对应文字、表格行或图表说明。
- `evidence_span` 表达的事实没有错。
- `extracted_json` 关键字段正确。
- `metrics_json` 的数值、单位和 cycle 等字段正确。
- 没有 placeholder、坏表、无法解释的异常值。

### edit

适用于：

- OCR 把 `90.0` 识别成 `900.00`。
- 表格行缺 enzyme，但 caption 或表头明确说明整张表都是同一 enzyme。
- reference 应为 `[35]` 或 `This study`，机器抽错。
- unit 缺失，但 PDF 表头或正文明确写了单位。
- `evidence_span` 太乱，但 PDF 里事实清楚。

edit 时至少填写：

- `corrected_evidence_span`
- `corrected_extracted_json`
- `corrected_metrics_json`
- `review_notes`

### reject

出现任一情况即 reject：

- 来源页是 `placeholder_pages.csv` 中的页。
- PDF 对应页没有这条事实。
- 表格行列错位，无法确认哪个数值属于哪个 enzyme/support。
- 数值看似异常，但 PDF 无法确认正确值。
- 证据需要跨多个不相邻段落拼接才成立。

## 6. 不同 record_type 怎么核对

### `enzyme_identity`

检查 enzyme 名称是否准确，例如 `BCL`、`CALB`、`lipase`、`PPL`。不要把 carrier 当 enzyme。

`extracted_json` 示例：

```json
{"enzyme_name": "BCL"}
```

### `immobilization_strategy`

检查 carrier/support/material 和 immobilization method。

允许字段：

```json
{"carrier": "ZIF-8", "material_class": "MOF", "immobilization_method": "adsorption"}
```

如果只看到 material，但没有 method，不要硬填 method。

### `formulation_condition`

检查 pH、temperature、time、loading、buffer、concentration 等。

示例：

```json
{"pH": 7.5, "temperature": "25 C", "time": "30 min", "loading": "700 mg"}
```

单位必须来自 PDF，不要自行换算。

### `performance_metric`

检查 yield、activity、recovery、reuse cycles、stability 等。

`metrics_json` 示例：

```json
[{"name": "reuse_cycles", "value": 10, "unit": "cycle", "raw": "10 cycles"}]
```

百分比超过 100 必须重点核对。除 activity recovery 这类确实可能超过 100 的指标外，yield 通常不应超过 100%。

### `table_comparison_row`

必须逐列核对：

1. 表格标题/caption。
2. 列名。
3. 当前行的 enzyme/support/substrate/condition/reference。
4. 数值单位。
5. 是否续表、合并单元格、旋转宽表。

如果 `quality_flags` 有 `missing_enzyme_cell`：

- 表头/caption 明确整张表同一 enzyme：可以 edit。
- 相邻行能唯一推断：在 `review_notes` 说明依据后 edit。
- 不能唯一推断：reject。

## 7. quality_flags 处理规则

- `unrecoverable_page_placeholder`：reject，不得入库。
- `placeholder_page_overlap`：reject，除非重新从原 PDF 可视确认并由工程侧人工补录。
- `table_parse_empty`：reject。
- `bad_table_structure`：先看 PDF；若无法逐列确认，reject。
- `table_ragged_rows`：重点检查列错位。
- `table_header_suspect`：重点检查表头和单位。
- `missing_enzyme_cell`：只在 caption/表头/上下文明确时 edit。
- `suspicious_table_yield_gt_100`：核对小数点和单位；不能确认则 reject。
- `suspicious_percent_gt_300`：核对是否 OCR 错误或 activity recovery；不能确认则 reject。
- `possible_ocr_duplicate_text`：如果事实和字段正确，可以 accept。
- `suspicious_reference_cell` / `malformed_reference`：修正 reference 或 reject。

## 8. 表格坏表如何做成人工 evidence

当前系统支持对已有 `evidence_id` 做 `accept/edit/reject`。如果坏表没有生成可用 evidence_id，只出现在 `source_qa_items.csv`：

1. 在 PDF 中确认该表格事实确实存在。
2. 在 `source_qa_items.csv` 填 `student_decision=needs_engineer`。
3. 在 `review_notes` 写清楚：
   - PDF 页码。
   - 表格编号。
   - 表格标题。
   - 应录入的 enzyme/support/condition/metric/reference。
   - 为什么机器表格不能直接用。
4. 不要自己改 `rag_chunks.jsonl`、`table_records.jsonl` 或 `evidence_records.jsonl`。

工程侧随后会把这些 notes 转成 curated evidence 或专门的人工 evidence overlay。

## 9. 复核完成后交付什么

每位复核人员交付：

1. 填好的 CSV。
2. 如果有 edit，提供对应修正 JSON 或在 CSV 的 corrected 字段填完整 JSON。
3. 所有 reject 必须写 `reject_reason`。
4. 所有 `needs_engineer` 必须写清楚人工补录依据。

## 10. 工程侧回灌命令

accept 示例：

```bash
PYTHONPATH=src .venv/bin/python scripts/curate_evidence.py \
  --artifact-root artifacts \
  --document-id A11 \
  --evidence-id ev_xxx \
  --action accept \
  --reviewer reviewer_name \
  --reason "verified against PDF page"
```

reject 示例：

```bash
PYTHONPATH=src .venv/bin/python scripts/curate_evidence.py \
  --artifact-root artifacts \
  --document-id A11 \
  --evidence-id ev_xxx \
  --action reject \
  --reviewer reviewer_name \
  --reason "table row cannot be verified"
```

edit 示例：

```bash
PYTHONPATH=src .venv/bin/python scripts/curate_evidence.py \
  --artifact-root artifacts \
  --document-id A11 \
  --evidence-id ev_xxx \
  --action edit \
  --edit-file reports/manual_review_260525/manual_edit_template.json \
  --reviewer reviewer_name \
  --reason "corrected OCR value after PDF check"
```

严重 flags 默认不能 accept/edit。只有重新视觉确认后，工程侧才可加 `--allow-severe`。

## 11. 最低质控要求

- 每条 `P0/P1` 至少由 1 人复核。
- 表格相关 `P1` 建议 10% 抽样双人复核。
- 两人结论冲突时，以 reject 或 needs_engineer 为默认保守结论。
- 不确定就不要入库。
