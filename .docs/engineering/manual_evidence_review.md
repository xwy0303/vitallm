# Manual Evidence Review

## 目标

人工复核只校正 first-pass evidence，不直接修改原始 `evidence_records.jsonl`、`rag_chunks.jsonl`、`table_records.jsonl`。

正式可 ranking 的人工结果必须通过 curated evidence overlay 进入：

```text
artifacts/evidence/<doc>/curation_decisions.jsonl
-> curated_evidence_records.jsonl
-> Qdrant evidence_record(candidate_source=curated_evidence, usable_for_ranking=true)
```

## 复核包导出

当前可复跑导出脚本：

```bash
PYTHONPATH=src .venv/bin/python scripts/export_manual_review_package.py \
  --artifact-root "$HOME/Library/Application Support/Shengji/app/artifacts" \
  --output-dir reports/manual_review_260525_student \
  --student-friendly
```

输出文件：

- `学生标注表_P0P1.csv`：给学生优先填写的极简中文 CSV。
- `学生标注表_全部.csv`：全量极简中文 CSV。
- `学生标注说明_极简版.md`：给 0 基础学生的中文操作说明。
- `student_review_mapping.jsonl`：工程侧映射表，不要求学生理解。
- `manual_review_items.csv`：evidence 级主复核清单。
- `manual_review_priority_p0_p1.csv`：高优先级子集。
- `bad_table_review.csv`：表格/坏表相关条目。
- `source_qa_items.csv`：chunk/table source 级 QA 条目，不能直接 curation 入库。
- `placeholder_pages.csv`：fallback placeholder 页，默认不得入库。
- `manual_review_sop.md`：给 0 基础研究生执行的操作规范。
- `manual_edit_template.json`：`curate_evidence.py --action edit` 模板。

## 当前导出状态 260525

数据源：LaunchAgent runtime mirror artifacts。

- evidence review items: 1142
- source QA items: 103
- total review rows: 1245
- bad table rows: 1059
- placeholder pages: 34

主风险：

- `missing_enzyme_cell`: 1043 evidence records，多数来自 table row 抽取。
- `possible_ocr_duplicate_text`: 52 evidence records / 54 source QA items。
- `suspicious_percent_gt_300`: 50 evidence records / 23 source QA items。
- placeholder source QA: 17 source rows, 34 placeholder pages。

学生版当前状态：

- `学生标注表_P0P1.csv`: 1100 行。
- `学生标注表_全部.csv`: 1142 行。
- `student_review_mapping.jsonl`: 1142 行，`任务编号` 唯一。
- 学生表内容类型只使用：`表格数据`、`酶/蛋白信息`、`载体/材料信息`、`固定化/制备条件`、`性能结果`、`质量问题`。
- 判定结果只允许：`正确`、`需修改`、`错误`、`不确定`。

## 回灌边界

- `manual_review_items.csv` 里的已有 `evidence_id` 可用 `scripts/curate_evidence.py` 执行 `accept/edit/reject`。
- 学生中文 CSV 可用 `scripts/import_student_review_csv.py` 回灌：

```bash
PYTHONPATH=src .venv/bin/python scripts/import_student_review_csv.py \
  --student-csv reports/manual_review_260525_student/学生标注表_P0P1_已完成.csv \
  --mapping reports/manual_review_260525_student/student_review_mapping.jsonl \
  --artifact-root artifacts
```

- 回灌前建议先加 `--dry-run`，检查 `student_review_import_report.json` 和 `student_review_uncertain_or_error.csv`。
- `source_qa_items.csv` 只定位源 chunk/table 问题；如果没有对应 `evidence_id`，不能直接用现有 curation CLI 入库。应标记 `needs_engineer`，由工程侧转换为人工 evidence overlay 或新增专用导入路径。
- `unrecoverable_page_placeholder`、`placeholder_page_overlap`、`table_parse_empty` 默认 severe，不允许 accept/edit；只有重新视觉确认原 PDF 后才可由工程侧用 `--allow-severe`。
