# QA Benchmark Summary - 2026-05-28T02:17:21.776811+00:00

- Generation mode: `mock`
- Collection: `enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1`
- Passed: 197/232 (0.849)

## Metrics

| Group | Metric | Value |
| --- | --- | ---: |
| retrieval | cases | 199 |
| retrieval | recall_at_3 | 0.774 |
| retrieval | recall_at_5 | 0.824 |
| retrieval | recall_at_8 | 0.854 |
| retrieval | mrr_at_3 | 0.683 |
| retrieval | mrr_at_5 | 0.695 |
| retrieval | mrr_at_8 | 0.699 |
| retrieval | ndcg_at_5 | 0.723 |
| retrieval | forbidden_hit_rate | 0.000 |
| retrieval | plan_accuracy | 0.953 |
| no_answer | cases | 30 |
| no_answer | no_answer_accuracy | 1.000 |
| no_answer | false_retrieval_rate | 0.000 |
| no_answer | unexpected_candidate_rate | 0.000 |
| no_answer | unexpected_citation_rate | 0.000 |
| answer_quality | cases | 54 |
| answer_quality | citation_accuracy | 1.000 |
| answer_quality | faithfulness | 1.000 |
| answer_quality | answer_relevancy | 0.926 |
| answer_quality | unsupported_claim_count_per_answer | 0.000 |
| answer_quality | condition_type_accuracy | 1.000 |
| answer_quality | stream_final_consistency | 1.000 |
| formulation | cases | 23 |
| formulation | field_recommendation_precision | 1.000 |
| formulation | evidence_backed_change_rate | 0.957 |
| formulation | unsafe_global_optimum_claim_count | 0 |

## Acceptance Targets

| Target | Actual | Status |
| --- | ---: | --- |
| Recall@5 >= 0.95 | 0.824 | FAIL |
| MRR@5 >= 0.85 | 0.695 | FAIL |
| Forbidden Hit Rate = 0 | 0.000 | PASS |
| NoAnswer Accuracy = 1.00 | 1.000 | PASS |
| Unexpected Candidate Rate = 0 | 0.000 | PASS |
| Unexpected Citation Rate = 0 | 0.000 | PASS |
| Citation Accuracy >= 0.90 | 1.000 | PASS |
| Unsupported Claim Count <= 0.10 / answer | 0.000 | PASS |
| Condition Type Accuracy >= 0.90 | 1.000 | PASS |
| Stream/Final Consistency >= 0.98 | 1.000 | PASS |
| Evidence-backed Change Rate >= 0.90 | 0.957 | PASS |
| Unsafe Global Optimum Claim Count = 0 | 0.000 | PASS |

## Failed Cases

| Benchmark | ID | Kind | Endpoint | Failed Checks | First Hits / Counts |
| --- | --- | --- | --- | --- | --- |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_like_temperature_not_always_higher | positive | search_evidence | overall_ok, evidence_ok | 1:B19:formulation_condition, 2:A65:formulation_condition, 3:A15:formulation_condition |
| enzyme_immobilization_retrieval_quality_v1 | rq_lit_strategy_004_a15 | positive | search_evidence | overall_ok, evidence_ok | 1:A15:immobilization_strategy, 2:A15:immobilization_strategy, 3:A15:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_lit_strategy_023_a29 | positive | search_evidence | overall_ok, evidence_ok | 1:A29:immobilization_strategy, 2:A29:immobilization_strategy, 3:A29:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_071_a11 | positive | search_evidence | overall_ok, evidence_ok | 1:A29:immobilization_strategy, 2:A19:immobilization_strategy, 3:A77:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_072_a12 | positive | search_evidence | overall_ok, plan_ok | 1:A12:immobilization_strategy, 2:A12:immobilization_strategy, 3:A12:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_073_a15 | positive | search_evidence | overall_ok, evidence_ok | 1:A15:immobilization_strategy, 2:A15:immobilization_strategy, 3:A15:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_074_a15 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A15:formulation_condition, 2:A15:formulation_condition, 3:A15:formulation_condition |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_075_a15 | positive | search_evidence | overall_ok, evidence_ok | 1:A29:immobilization_strategy, 2:A19:immobilization_strategy, 3:A77:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_076_a15 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A15:immobilization_strategy, 2:A15:immobilization_strategy, 3:A15:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_077_a15 | positive | search_evidence | overall_ok, evidence_ok | 1:A15:immobilization_strategy, 2:A15:immobilization_strategy, 3:A15:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_078_a15 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A15:formulation_condition, 2:A15:formulation_condition, 3:A15:formulation_condition |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_079_a15 | positive | search_evidence | overall_ok, evidence_ok | 1:A29:immobilization_strategy, 2:A19:immobilization_strategy, 3:A77:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_080_a15 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A15:immobilization_strategy, 2:A15:immobilization_strategy, 3:A15:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_081_a11 | positive | search_evidence | overall_ok, plan_ok | 1:A11:performance_metric, 2:A11:immobilization_strategy, 3:A11:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_083_a11 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A28:immobilization_strategy, 2:A16:immobilization_strategy, 3:B9:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_084_a11 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A11:immobilization_strategy, 2:A11:immobilization_strategy, 3:A11:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_085_a11 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A11:performance_metric, 2:A11:immobilization_strategy, 3:A11:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_087_a11 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A28:immobilization_strategy, 2:A16:immobilization_strategy, 3:B9:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_088_a12 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A12:immobilization_strategy, 2:A12:immobilization_strategy, 3:A12:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_cross_zif8_reuse_sds_bcl | positive | search_evidence | overall_ok, evidence_ok | 1:B10:performance_metric, 2:B10:immobilization_strategy, 3:B10:table_comparison_row |
| enzyme_immobilization_retrieval_quality_v1 | rq_cross_uio66_pfl_ays | positive | search_evidence | overall_ok, evidence_ok | 1:B16:performance_metric, 2:B16:enzyme_identity, 3:B16:enzyme_identity |
| enzyme_immobilization_answer_quality_v1 | aq_curated_002_a11_formulation_condition | answer_quality | recommend | overall_ok, evidence_ok | 1:A11:formulation_condition, 2:A11:formulation_condition, 3:A11:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_003_a11_formulation_condition | answer_quality | recommend | overall_ok, evidence_ok | 1:A11:formulation_condition, 2:A11:formulation_condition, 3:A11:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_010_a12_formulation_condition | answer_quality | recommend | overall_ok, facts_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_012_a12_formulation_condition | answer_quality | recommend | overall_ok, evidence_ok, facts_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_013_a12_formulation_condition | answer_quality | recommend | overall_ok, evidence_ok, facts_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_014_a12_formulation_condition | answer_quality | recommend | overall_ok, evidence_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_016_a12_formulation_condition | answer_quality | recommend | overall_ok, evidence_ok, facts_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_042_a15_immobilization_strategy | answer_quality | recommend | overall_ok, evidence_ok | 1:A15:immobilization_strategy, 2:A15:immobilization_strategy, 3:A15:immobilization_strategy |
| enzyme_immobilization_answer_quality_v1 | aq_curated_044_a15_immobilization_strategy | answer_quality | recommend | overall_ok, evidence_ok | 1:A15:immobilization_strategy, 2:A15:immobilization_strategy, 3:A15:immobilization_strategy |
| enzyme_immobilization_formulation_optimizer_v1 | fo_curated_006_a11 | formulation | optimize | overall_ok, evidence_ok | 1:A11:formulation_condition, 2:A11:formulation_condition, 3:A11:formulation_condition |
| enzyme_immobilization_formulation_optimizer_v1 | fo_curated_007_a11 | formulation | optimize | overall_ok, evidence_ok | 1:A11:formulation_condition, 2:A11:formulation_condition, 3:A11:formulation_condition |
| enzyme_immobilization_formulation_optimizer_v1 | fo_curated_009_a12 | formulation | optimize | overall_ok, evidence_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_formulation_optimizer_v1 | fo_curated_012_a12 | formulation | optimize | overall_ok, evidence_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_formulation_optimizer_v1 | fo_cn_alias_rml_table_context | formulation | optimize | overall_ok, citation_ok | 1:A26:formulation_condition, 2:A11:formulation_condition, 3:B17:formulation_condition |
