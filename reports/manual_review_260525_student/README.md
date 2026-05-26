# Manual Review Package

生成时间：2026-05-26T11:12:32

数据源：`/Users/way/Library/Application Support/Shengji/app/artifacts`

## 文件说明

- `manual_review_items.csv`：evidence 级待人工复核主清单，可直接在 Excel/WPS 中填写。
- `manual_review_priority_p0_p1.csv`：高优先级子集，建议先做。
- `manual_review_items.jsonl`：同一清单的机器可读版本。
- `bad_table_review.csv`：表格/坏表相关条目合集。
- `source_qa_items.csv`：chunk/table source 级 QA 条目，主要用于定位上游 OCR/table 问题。
- `placeholder_pages.csv`：fallback placeholder 页清单，原则上不得入库。
- `manual_edit_template.json`：执行 edit curation 时可复制的 JSON 模板。
- `manual_review_sop.md`：给人工复核人员的操作规范。
- `summary.json`：本包统计。

## 当前统计

- evidence review items: 1142
- source QA items: 103
- total review rows: 1245
- bad table rows: 1059
- placeholder pages: 34

建议先读 `manual_review_sop.md`，再从 `manual_review_priority_p0_p1.csv` 开始。
