# RAG Pipeline Optimization Plan

## 现状分析

当前链路已经打通：

```text
PDF -> MinerU local -> RAG inputs -> rule-based evidence -> Qdrant -> RetrievalResponse -> LLM generation
```

已有基础能力包括 ingestion registry、queued job、sha256 去重、MinerU artifact 复用、Qdrant upsert、dashboard summary 和正式 collection `enzyme_immobilization_literature`。短板集中在四类：embedding 仍以 `hash_v1` 为默认 smoke 模型、collection/index version 契约还没有统一入口、批处理状态虽然已有 registry 但 indexing manifest 还需落地、检索质量缺少 curated benchmark。

## 优化清单

| 优先级 | 优化项 | 交付物 | 验证标准 |
| --- | --- | --- | --- |
| P0 | Collection/version contract | 统一 `collection`、`index_version`、`point_schema_version` 生成函数 | 同一 embedding/schema 得到稳定名称；point payload 带版本字段 |
| P0 | Semantic embedding 切换 | `configs/local.semantic.yaml`、embedding runtime check、语义 collection 重建命令 | 本地 BGE 能 `local_files_only` embed；不污染 hash rollback collection |
| P0 | Document ingestion state | registry + per-document indexing manifest | 每个 PDF 有 `sha256/status/artifact/rag/evidence/collection/index_version` |
| P0 | Retrieval benchmark | curated benchmark JSON + benchmark runner | 输出 Recall@k、MRR、失败 query 和 top hits |
| P1 | Section-aware chunking | section/table/caption/nearby context 更强绑定 | BCL/ZIF-8、biodiesel yield、formulation condition 召回稳定 |
| P1 | Table evidence weighting | table row 绑定 caption、section、单位、附近正文 | performance metrics 相关 query top-k 命中表格 evidence |
| P1 | Reranker | dense recall top-N -> rerank top-k | curated benchmark 的 MRR 提升，unsupported hit 下降 |
| P2 | Query planner | enzyme/application/metric/constraint 解析 | 推荐和配方优化按意图分路召回 |
| P2 | PDF repair fallback | 对 MinerU `Failed to load page` 文档做 repair/re-render | 19 篇失败 PDF 有明确修复结果 |

## 开发规划

### Phase 0：P0 契约闭环

- [x] 新增 `rag.indexing` 统一生成 `collection` / `index_version` / `point_schema_version`。
- [x] ingestion pipeline 写入 per-document indexing manifest。
- [x] 新增 semantic config，不直接覆盖 live hash config。
- [x] 新增 embedding runtime check。
- [x] 新增 retrieval benchmark manifest 和 runner。
- [x] 用当前正式 hash collection 跑 retrieval smoke baseline：Recall@8=1.0，MRR=0.733；`formulation_conditions` 正确 `formulation_condition` 命中 rank=5。
- [x] 验证 `configs/local.semantic.yaml` 可在 `local_files_only=true` 下用 CPU 加载 `BAAI/bge-base-en-v1.5`。
- [x] 用 `configs/local.semantic.yaml` 从当时已有 RAG/evidence artifacts 初始重建 semantic collection：76 docs，6910 points；后续失败 PDF 恢复后已扩到 95 docs，8263 points。
- [x] 跑 retrieval benchmark，对比 hash collection 与 semantic collection。

### Phase 1：检索质量提升

- [x] 把 benchmark 扩到 62 条 curated queries，覆盖 negative / ambiguous / bad-table / placeholder exclusion cases。
- [ ] 增强 chunking 的 section/table parent-child 结构。
- [x] 将 table caption、section、signals、columns、row preview 和 evidence section 纳入 embedding text。
- [x] 加 lightweight lexical+dense hybrid rerank：domain/material/numeric/unit/phrase overlap、英文数字词归一化。
- [x] 加 result diversity：同一 parent/table 多行 evidence 不再刷满 top-k。
- [x] 加 payload index 建议和 Qdrant 初始化脚本。

### Phase 2：科研可靠性与失败恢复

- [x] 抽样审计单栏、双栏和复杂表格 PDF 的 MinerU `middle_json` / `content_list` 质量。
- [x] 为 MinerU 失败 PDF 建 repair/re-render 分支。
- [ ] 对 review queue 建人工校验状态。
- [x] 建离线 benchmark 报告输出到 `artifacts/benchmarks/`。

## 风险与边界

- 不能把 live API 直接切到 semantic config，除非对应 semantic collection 已重建并通过 benchmark。
- `hash_v1` collection 仍保留为 smoke/rollback，不再作为科学语义检索质量判断依据。
- Qdrant storage 不是事实源；正式事实源仍是 registry、MinerU artifacts、RAG inputs 和 evidence JSONL。
- 19 篇 MinerU 失败 PDF 不能静默修复后入库：17 篇 `pypdf_rewrite` 后可渲染但页数减少，必须走 OCR/raster fallback 或人工确认；A47/A75 属于 MinerU runtime/model `state_dict` 问题，应修 runtime 后重跑原 PDF。

## 验证标准

- `pytest tests/test_core_contracts.py` 通过。
- `scripts/check_embedding_runtime.py --config configs/local.semantic.yaml` 能在 `local_files_only=true` 下返回 768 维向量。
- `scripts/benchmark_retrieval.py --config <config>` 输出 Recall@k、MRR。
- 新索引 points payload 含 `point_schema_version`、`embedding_model`、`embedding_dimensions`、`index_version`。

## Retrieval / Indexing Update 260525

本轮已完成的工程收敛：

- `rag.indexing` 成为 collection/index identity 单一入口：`collection=None` 或 `auto` 会按 embedding identity + `point_schema_v1` 派生正式 collection；显式 collection 保持不变。
- ingestion pipeline、worker、Qdrant config、API collection override、standalone index/search/benchmark 脚本已对齐该契约。
- semantic collection 已从当时已有 RAG/evidence artifacts 初始重建，不重跑 MinerU：`enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1`，76 docs，6910 points，其中 `rag_chunk=3057`、`table_record=133`、`evidence_record=3720`；当前失败 PDF 恢复后运行态为 95 docs，8263 points。
- Qdrant payload 增加 `embedding_text`，table embedding text 包含 section/caption/signals/columns/row preview/text；evidence embedding text 包含 section。
- retrieval 增加轻量 deterministic rerank：召回 top_k*3 后按 table/evidence intent、record_type、confidence、token overlap 加权，对 quality flags / requires_review 降权。

Benchmark artifacts：

- `artifacts/benchmarks/retrieval_smoke_hash_rerank_260525.json`：hash live collection，Recall@8=1.0，MRR=0.8333；query ranks：1/1/2。
- `artifacts/benchmarks/retrieval_smoke_semantic_bge_260525.json`：semantic BGE collection，Recall@8=1.0，MRR=0.7778；query ranks：3/1/1。
- 结论：3-query smoke 不能支持直接切 live API 到 semantic；semantic 对 formulation condition 更好，但 BCL/ZIF-8 strategy 仍被 enzyme_identity 抢占，需要扩大 curated benchmark 和改 query/record-type rerank。

## Failed PDF Repair 260525

失败 PDF：`A34 A35 A39 A47 A49 A51 A53 A57 A65 A66 A68 A70 A72 A73 A74 A75 A76 A77 A78`。

修复产物：

- `artifacts/pdf_repair/repair_report.json`
- 17 个 `pypdf_rewrite` candidate：`artifacts/pdf_repair/<doc>/<doc>.pypdf-rewrite.pdf`
- A34 repaired PDF 已通过 MinerU smoke：`artifacts/mineru_repair_smoke/A34.pypdf-rewrite_c837876d-aaf0-4e24-a777-01a1533873b9/`

重要边界：

- 17 篇 `pdf_page_load_failure` 文档 rewrite 后 `bad_pages=[]`，但 `page_count_delta` 均为负数，状态标记为 `repair_candidate_renderable_but_page_count_changed`，`needs_ocr_fallback=true`。这些不能直接作为完整文档入库。
- A47/A75 原 PDF 可渲染，失败类为 `mineru_model_state_dict_mismatch`，动作是修复 MinerU runtime/model cache 后重跑原 PDF。

## Raster/OCR Fallback 260525

已补齐本地 PDF fallback 工具链：

- Homebrew CLI：`qpdf`、`ghostscript`、`poppler` (`pdfinfo`/`pdftoppm`)、`tesseract`、`ocrmypdf`。
- 项目脚本：`scripts/build_pdf_raster_fallbacks.py`。
- 策略：先用 `pdfinfo` 获取原始页数，再用 `pdftoppm` 按原始页码逐页 rasterize，重组为同页数 image PDF，最后用 `ocrmypdf` 生成 searchable PDF。
- 如果某页无法渲染或渲染为异常小图像，则生成显式 placeholder 页，并在 manifest/report 的 `placeholder_pages` 中记录；不得把 placeholder 页作为真实 evidence 入库。

17 篇 `pdf_page_load_failure` 文档均已生成 page-count preserving fallback：

- 总文档数：17
- 原始总页数：180
- 生成最终 PDF：17 个 `*.raster-ocr.pdf`
- 页数校验：全部 `expected_pages == final_pdfinfo_pages`
- 渲染校验：全部 `pypdfium2` `bad_pages=[]`
- 状态：全部 `fallback_ready_with_placeholders`
- placeholder 总数：34 页
- 总产物目录：`artifacts/pdf_raster_fallback/`
- 总 report：`artifacts/pdf_raster_fallback/fallback_report.json`

每篇 placeholder 页：

| doc | pages | placeholder_pages |
| --- | ---: | --- |
| A34 | 10 | 8, 9, 10 |
| A35 | 11 | 9, 10, 11 |
| A39 | 8 | 7, 8 |
| A49 | 12 | 12 |
| A51 | 12 | 11, 12 |
| A53 | 11 | 11 |
| A57 | 9 | 8, 9 |
| A65 | 10 | 9, 10 |
| A66 | 11 | 11 |
| A68 | 12 | 10, 11, 12 |
| A70 | 11 | 10, 11 |
| A72 | 9 | 8, 9 |
| A73 | 12 | 12 |
| A74 | 12 | 10, 11, 12 |
| A76 | 8 | 8 |
| A77 | 13 | 10, 11, 12, 13 |
| A78 | 9 | 9 |

MinerU 验证：

- A34 fallback PDF 已通过 MinerU smoke。
- Task id：`930e33ca-90df-4f31-b4ef-06b77c340577`
- Artifact：`artifacts/mineru_raster_fallback_smoke/A34.raster-ocr_930e33ca-90df-4f31-b4ef-06b77c340577/`
- 解压后确认存在 `A34.raster-ocr_content_list.json`、`A34.raster-ocr_middle.json` 和 `A34.raster-ocr.md`。

后续 ingestion 规则：

- 对 `fallback_ready_with_placeholders` 文档可以进入 MinerU/RAG，但必须把 `placeholder_pages` 写入 provenance，并在 chunk/evidence 层打 `unrecoverable_page_placeholder` / `requires_review`。
- placeholder 页相关内容不得用于 `usable_for_ranking=true` 的 evidence。
- A47/A75 不走 raster fallback；仍应修复 MinerU model/runtime 后重跑原 PDF。

## Failed PDF Ingestion Recovery 260525

已完成最终恢复：

- A34：原 job 卡在 stale `running`，但 MinerU result endpoint 已有 zip；已下载/解压 artifact，旧 job 标记 `stale_worker_recovered`，重新完成 RAG/evidence/Qdrant 入库。
- A47/A75：根因为 MinerU MPS seal OCR server 权重 shape 与 server arch 不匹配；已补齐 `seal_lite` 权重，并在 runtime `deploy/local/env.local` 设置 `MINERU_DEVICE_MODE=cpu`，重跑原 PDF 成功。
- 17 篇 `pdf_page_load_failure` 文档已走 page-count preserving raster/OCR fallback，placeholder pages 经 post-MinerU QA gate 禁止进入 usable ranking。
- 当前 registry：`searchable=95`；runtime dashboard：`indexed_docs=95`、`indexed_pages=1004`、`rag_chunks=3673`、`table_records=166`、`evidence_records=4424`、`review_items=1245`、`qdrant_points=8263`、Qdrant green。

## MinerU Layout Audit 260525

抽样对象覆盖单栏正文、双栏论文和复杂表格：

| 类型 | 样本 | 页码 | 结论 |
| --- | --- | --- | --- |
| 单栏正文 | `B10.pdf` | p1、p8、p9 | 正文 reading order 基本正确；跨页 Table 1 被拆成 `Table 1` 与 `Table 1. Cont.` 两个 table records，续表关系可由 caption/page 连起来。 |
| 双栏论文 | `A24.pdf` | p1-p3 | `content_list` 输出顺序符合双栏阅读：上方图/摘要后进入左栏，再右栏；未发现实质跳栏。 |
| 双栏论文 + 多表 | `A28.pdf` | p1、p5、p6 | 双栏正文顺序可用；表格有 merged header/数学符号 OCR 噪声，适合召回但不适合无校验地做数值事实。 |
| 双栏论文 + ANOVA 表 | `A8.pdf` | p1、p4 | 双栏正文顺序可用；Table 2 主体结构正确，但末尾 `Pure error` / `Cor total` 行发生合并。 |
| 复杂旋转宽表 | `A14.pdf` | p4、p5 | p4 Table 1 可用；p5 旋转宽表 Table 2 结构损坏，列名和分组 header 合并，footnote 混入数据行，不能直接作为 row-level evidence。 |
| 单栏 accepted manuscript | `B1.pdf` | p1、p8 | 单栏正文顺序可用；首页 accepted manuscript boilerplate 会进入 `content_list`，后续 chunking 应过滤前置出版说明和侧边栏。 |

关键发现：

- 当前 `backend=pipeline`、`parse_method=auto` 能处理单栏和双栏主正文；真正风险主要在 table structure，而不是 reading order。
- `content_list.bbox` 与 `middle_json.page_size` 不是同一尺度；layout QA 不能直接混用两者判断左右栏，需按同一来源归一化。
- `B10` 续表被正确拆出两段，但存在细粒度 OCR/表格错误：`Candida antarctica` yield 识别为 `900.00`，部分 reference bracket 丢失。
- `A14` 这类旋转宽表必须进入人工复核或专用 fallback；否则会把 Plackett-Burman/Box-Behnken 设计表污染成错误 evidence。

审计产物：

- `artifacts/mineru_layout_audit_candidates.json`
- `artifacts/mineru_layout_audit_candidates.refined.json`
- `artifacts/mineru_layout_audit/rendered/`
- `artifacts/mineru_layout_audit/table_crops/`

## Retrieval Routing / QA Gate Update 260525

该阶段按“hash baseline + semantic candidate benchmark”策略推进；后续已完成 62-query v3 benchmark 并切换 live collection，见下一节。

已完成：

- `src/enzyme_recommender/rag/retrieval.py` 增加 query planner / intent routing。
- retrieval 从单路 search 升级为 record_type-aware 多路召回，支持 `immobilization_strategy`、`formulation_condition`、`performance_metric`、`table_comparison_row`、`enzyme_identity` route。
- rerank 纳入 route weight、record_type priority、point_type priority、numeric overlap、structured `extracted/metrics` text、table/context intent boost，以及 QA/quality penalty。
- 新增 `src/enzyme_recommender/ingestion/qa.py`，作为 post-MinerU QA gate。
- `build_rag_inputs` 自动读取 `artifacts/pdf_raster_fallback/<doc>/fallback_manifest.json`，把 fallback `placeholder_pages` 映射到 MinerU 0-based `page_idx`。
- placeholder chunk/table 标记 `unrecoverable_page_placeholder`、`requires_review=true`、`usable_for_ranking=false`。
- 空表、疑似坏表、稀疏表、ragged rows、疑似旋转宽表进入 QA fail；QA fail source 不再进入 rule-based evidence 抽取。
- benchmark 扩为 24 条 curated queries，覆盖 strategy、formulation condition、performance、table row、application context。

A34 fallback QA smoke：

- 输入 artifact：`artifacts/mineru_raster_fallback_smoke/A34.raster-ocr_930e33ca-90df-4f31-b4ef-06b77c340577/`
- QA gate 识别 placeholder pages：8、9、10。
- 对应 placeholder chunk 标记 `unrecoverable_page_placeholder`，不可 ranking。

Benchmark artifacts：

- `artifacts/benchmarks/retrieval_curated_v2_hash_live_260525.json`
- `artifacts/benchmarks/retrieval_curated_v2_semantic_shadow_260525.json`

结果：

| collection | role | queries | Recall@8 | MRR | PlanAcc |
| --- | --- | ---: | ---: | ---: | ---: |
| `enzyme_immobilization_literature` | hash baseline | 24 | 0.958 | 0.809 | 0.958 |
| `enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1` | semantic candidate | 24 | 1.000 | 0.931 | 0.958 |

结论：

- semantic candidate 在扩大 benchmark 上已经明显优于 hash baseline。
- 当时未直接切 live：24 条 query 还偏 curated，尚不足以覆盖失败 PDF fallback、复杂表格、人工 review 后事实修订和推荐端真实 query 分布。
- 该下一步已在 62-query v3 benchmark 中完成，并据此切换 semantic 为默认 live。

## Retrieval Benchmark v3 / Live Switch Decision 260525

本轮已把 benchmark 扩到 62 条：

| kind | count | 覆盖目标 |
| --- | ---: | --- |
| positive | 45 | 具体 enzyme/carrier/condition/performance/table row 命中 |
| ambiguous | 5 | 多篇论文均可接受的开放式检索 |
| negative | 5 | corpus 外 unsupported entity/query，不应伪造精确证据 |
| exclusion | 7 | bad-table、requires_review、placeholder page 不得进入 usable ranking |

Benchmark artifacts：

- `artifacts/benchmarks/retrieval_curated_v3_hash_live_260525.json`
- `artifacts/benchmarks/retrieval_curated_v3_semantic_shadow_260525.json`
- `artifacts/benchmarks/retrieval_curated_v3_after_material_rerank_260525.json`

结果：

| collection | role | total pass | positive recall@k | positive MRR | ambiguous | negative | exclusion | PlanAcc |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `enzyme_immobilization_literature` | hash rollback baseline | 57/62 | 45/50 = 0.900 | 0.767 | 3/5 | 5/5 | 7/7 | 0.984 |
| `enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1` | semantic live | 62/62 | 50/50 = 1.000 | 0.895 | 5/5 | 5/5 | 7/7 | 0.984 |
| `enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1` | current after failed-PDF recovery + rare material OCR rerank | 62/62 | 45/45 = 1.000 | 0.941 | 5/5 | 5/5 | 7/7 | 0.984 |

hash baseline 主要失败：

- `calb_ru_uio66_furfuryl_yield`
- `fa_zif8_pseudomonas_cepacia_efficiency`
- `ppl_mof_warfarin_bioreactor`
- `ambiguous_zif8_biodiesel_reuse`
- `ambiguous_cubtc_lipase_conditions`

semantic collection 在 v3 覆盖集上满足 live 切换门槛：

- 45/45 positive 全通过。
- 5/5 ambiguous 全通过。
- 5/5 negative 全通过。
- 7/7 exclusion 全通过，说明 bad-table / placeholder / review-gated evidence 当前没有进入 usable top-k。
- MRR 明显高于 hash baseline：0.895 vs 0.767。

切换执行：

- 已将默认 runtime `configs/local.yaml` 切到 semantic embedding + semantic collection。
- `configs/local.hash.yaml` 保留 hash baseline rollback：collection=`enzyme_immobilization_literature`，embedding=`hash_v1`。
- `configs/local.semantic.yaml` 保留为显式 semantic alias，用于 benchmark/rebuild 命令兼容。
- Web 前端默认不再发送 collection override，跟随 API runtime；如需强制覆盖，可设置 `window.ENZYME_COLLECTION`。
- LaunchAgents ingestion 默认 `INGESTION_COLLECTION=""`，跟随 `ENZYME_RUNTIME_CONFIG`；只有回滚或实验时才显式设置。
- hash collection 必须保留为 rollback baseline，不删除、不重建覆盖。

运行态验证：

- 已同步当前 `src/`、`scripts/`、`web/`、`configs/` 到 LaunchAgent 使用的安装副本：`~/Library/Application Support/Shengji/app/`。
- 已重启 `com.shengji.api` 和 `com.shengji.ingestion-worker`；Qdrant、MinerU、Web 未重启。
- `/api/health` 当前返回 semantic collection：`enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1`。
- `/api/dashboard/summary` 当前 Qdrant 状态：`green`，points=`8263`，indexed_docs=`95`。
- `/api/search/evidence` 查询 `BCL-ZIF-8 biodiesel synthesis temperature 40 C yield 93.4 solvent-free ethanol soybean oil` 时，top hit 为 B10 `table_comparison_row`，citation=`B10.pdf:p9`，embedding=`sentence:BAAI/bge-base-en-v1.5`。

## P0 Governance Update 260525

新增治理闭环：

- 新增 curated evidence overlay：人工审核动作写入 `artifacts/evidence/<doc>/curation_decisions.jsonl`，重建产物为 `curated_evidence_records.jsonl`。
- 原始 `evidence_records.jsonl` 继续作为 first-pass extraction，不直接修改；curated record 使用新的 `cur_*` evidence id，并保留 `source_evidence_id`、reviewer、reason、reviewed_at。
- Qdrant indexing 自动读取 `curated_evidence_records.jsonl`，将人工确认后的记录作为 `candidate_source=curated_evidence`、`usable_for_ranking=true` 的 evidence point 入库。
- 新增 CLI：`scripts/curate_evidence.py`，支持 `accept/edit/reject/rebuild/summary`。
- 新增 API：`POST /api/evidence/{document_id}/{evidence_id}/curate`，用于后续前端人工复核入口。
- dashboard summary 新增 `curated_evidence_records`。

失败 PDF 入队：

- 新增 `scripts/queue_pdf_fallback_ingestion.py`，读取 `artifacts/pdf_raster_fallback/<doc>/fallback_manifest.json`，校验页数保真、render OK 后，把 `*.raster-ocr.pdf` 作为同一 `document_id` 的 fallback source 写回 registry 并创建 queued job。
- 该脚本不绕过 MinerU/RAG/Qdrant，也不直接把 fallback PDF 写入 collection；placeholder pages 仍由 post-MinerU QA gate 禁止进入 ranking。

部署验证：

- 新增 `deploy/local/sync_runtime.sh`，将 workspace 的 `src/web/configs/schemas/scripts/artifacts/.local/.venv/.venv-mineru/PDF corpus` 同步到 LaunchAgent runtime mirror。
- 新增 `scripts/verify_local_runtime.py`，检查 workspace config、runtime mirror config、API health collection、dashboard collection/Qdrant status，可选运行 retrieval benchmark。

## P1 Retrieval Rerank Update 260525

已完成：

- `src/enzyme_recommender/rag/retrieval.py` 在现有 dense multi-route 召回后加入 lightweight lexical score。
- lexical score 使用 domain/material token、numeric token、unit token、phrase overlap 和 number-word normalization；用于把 `700 mg / 30 min / pH 7.5`、`ten cycles`、`ZIF-8` 等 exact evidence 提到前面。
- lexical score 已补充 rare material / `enzyme@material` construct signal，并对 MinerU OCR split（`Lipa se@NKMOF-101-Mn`）做归一化；`lipase_nkmof101_mn_activity` 从 failed top-8 恢复为 rank=1。
- rerank 后增加 result diversity，对同一 `parent_source_id` / `table_id` 的重复候选递增降权，避免 fallback 新入库文档中同表多行 `table_comparison_row` 占满 top-k。
- 保持 QA/ranking 硬边界：`usable_for_ranking=false`、`requires_review=true`、`qa_status=fail`、placeholder/bad-table flags 不会因 lexical 分被重新提升为可用证据。

验证：

- `PYTHONPATH=src .venv/bin/python -m compileall src scripts tests` 通过。
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_core_contracts.py -q`：53 passed。
- `benchmarks/retrieval_smoke.json` 语义 live collection：62/62，通过率 1.000，positive recall@k 1.000，overall MRR 0.920，positive MRR 0.941，PlanAcc 0.984。
- API runtime 已 code/config sync 并重启 `com.shengji.api`；`scripts/verify_local_runtime.py --json` 返回 ok，collection 仍为 semantic live。
- API 查询 `best ZIF-8 lipase immobilization for biodiesel production and reuse cycles` 时，A35 同一表多行不再占满 top8，B10/A55 等跨文档结果可进入前列。

当前运行态：

- 本次只执行 code/config sync，未 sync artifacts；只重启 `com.shengji.api`，未重启 Qdrant、MinerU、worker。
- 验证时 dashboard：indexed_docs=95，indexed_pages=1004，qdrant_points=8263，Qdrant green。

## Qdrant Payload Index Update 260525

已完成：

- 新增 `QdrantRestClient.create_payload_index()`、`ensure_payload_indexes()`、`list_payload_schema()`。
- 新增 `scripts/ensure_qdrant_payload_indexes.py`，按 runtime config 对当前 collection 创建检索过滤常用 payload indexes。
- live semantic collection 已创建 `point_type`、`record_type`、`document_id`、`source_pdf`、`candidate_source`、`curation_status`、`qa_status`、`usable_for_ranking`、`requires_review` indexes。

验证：

- payload index 脚本返回 `all_present=true`。
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_core_contracts.py -q`：52 passed。
- `benchmarks/retrieval_smoke.json` 语义 live collection：62/62，MRR 0.948，PlanAcc 0.984。
- 已 code/config sync 到 LaunchAgent runtime mirror 并重启 `com.shengji.api`；未重启 worker，未同步 artifacts。
