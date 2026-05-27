# QA Benchmark Summary - 2026-05-27T14:47:21.322909+00:00

- Generation mode: `mock`
- Collection: `enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1`
- Passed: 183/232 (0.789)

## Metrics

| Group | Metric | Value |
| --- | --- | ---: |
| retrieval | cases | 199 |
| retrieval | recall_at_3 | 0.719 |
| retrieval | recall_at_5 | 0.774 |
| retrieval | recall_at_8 | 0.804 |
| retrieval | mrr_at_3 | 0.639 |
| retrieval | mrr_at_5 | 0.652 |
| retrieval | mrr_at_8 | 0.656 |
| retrieval | ndcg_at_5 | 0.680 |
| retrieval | forbidden_hit_rate | 0.000 |
| retrieval | plan_accuracy | 0.940 |
| no_answer | cases | 30 |
| no_answer | no_answer_accuracy | 1.000 |
| no_answer | false_retrieval_rate | 0.000 |
| no_answer | unexpected_candidate_rate | 0.000 |
| no_answer | unexpected_citation_rate | 0.000 |
| answer_quality | cases | 54 |
| answer_quality | citation_accuracy | 1.000 |
| answer_quality | faithfulness | 1.000 |
| answer_quality | answer_relevancy | 0.722 |
| answer_quality | unsupported_claim_count_per_answer | 0.000 |
| answer_quality | condition_type_accuracy | 0.981 |
| answer_quality | stream_final_consistency | 1.000 |
| formulation | cases | 23 |
| formulation | field_recommendation_precision | 1.000 |
| formulation | evidence_backed_change_rate | 0.957 |
| formulation | unsafe_global_optimum_claim_count | 0 |

## Acceptance Targets

| Target | Actual | Status |
| --- | ---: | --- |
| Recall@5 >= 0.95 | 0.774 | FAIL |
| MRR@5 >= 0.85 | 0.652 | FAIL |
| Forbidden Hit Rate = 0 | 0.000 | PASS |
| NoAnswer Accuracy = 1.00 | 1.000 | PASS |
| Unexpected Candidate Rate = 0 | 0.000 | PASS |
| Unexpected Citation Rate = 0 | 0.000 | PASS |
| Citation Accuracy >= 0.90 | 1.000 | PASS |
| Unsupported Claim Count <= 0.10 / answer | 0.000 | PASS |
| Condition Type Accuracy >= 0.90 | 0.981 | PASS |
| Stream/Final Consistency >= 0.98 | 1.000 | PASS |
| Evidence-backed Change Rate >= 0.90 | 0.957 | PASS |
| Unsafe Global Optimum Claim Count = 0 | 0.000 | PASS |

## Failed Cases

| Benchmark | ID | Kind | Endpoint | Failed Checks | First Hits / Counts |
| --- | --- | --- | --- | --- | --- |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_like_temperature_not_always_higher | positive | search_evidence | overall_ok, evidence_ok | 1:A65:formulation_condition, 2:B19:formulation_condition, 3:A15:formulation_condition |
| enzyme_immobilization_retrieval_quality_v1 | rq_lit_strategy_003_a15 | positive | search_evidence | overall_ok, evidence_ok | 1:A15:immobilization_strategy, 2:A15:immobilization_strategy, 3:A15:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_lit_strategy_004_a15 | positive | search_evidence | overall_ok, evidence_ok | 1:A15:immobilization_strategy, 2:A15:immobilization_strategy, 3:A15:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_lit_strategy_020_a28 | positive | search_evidence | overall_ok, evidence_ok | 1:A28:immobilization_strategy, 2:A28:immobilization_strategy, 3:A28:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_lit_strategy_023_a29 | positive | search_evidence | overall_ok, evidence_ok | 1:A29:immobilization_strategy, 2:A29:immobilization_strategy, 3:A29:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_071_a11 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A29:immobilization_strategy, 2:A19:immobilization_strategy, 3:A77:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_072_a12 | positive | search_evidence | overall_ok, plan_ok | 1:A12:immobilization_strategy, 2:A12:immobilization_strategy, 3:A12:- |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_073_a15 | positive | search_evidence | overall_ok, evidence_ok | 1:A15:immobilization_strategy, 2:A15:immobilization_strategy, 3:A15:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_074_a15 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A15:formulation_condition, 2:A15:formulation_condition, 3:A15:formulation_condition |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_075_a15 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A29:immobilization_strategy, 2:A19:immobilization_strategy, 3:A77:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_076_a15 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A15:immobilization_strategy, 2:A15:immobilization_strategy, 3:A15:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_077_a15 | positive | search_evidence | overall_ok, evidence_ok | 1:A15:immobilization_strategy, 2:A15:immobilization_strategy, 3:A15:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_078_a15 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A15:formulation_condition, 2:A15:formulation_condition, 3:A15:formulation_condition |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_079_a15 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A29:immobilization_strategy, 2:A19:immobilization_strategy, 3:A77:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_080_a15 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A15:immobilization_strategy, 2:A15:immobilization_strategy, 3:A15:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_081_a11 | positive | search_evidence | overall_ok, plan_ok | 1:A11:performance_metric, 2:A11:immobilization_strategy, 3:A11:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_083_a11 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A28:immobilization_strategy, 2:A16:immobilization_strategy, 3:B9:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_084_a11 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A11:immobilization_strategy, 2:A11:enzyme_identity, 3:A11:enzyme_identity |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_085_a11 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A11:performance_metric, 2:A11:immobilization_strategy, 3:A11:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_087_a11 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A28:immobilization_strategy, 2:A16:immobilization_strategy, 3:B9:immobilization_strategy |
| enzyme_immobilization_retrieval_quality_v1 | rq_user_paraphrase_088_a12 | positive | search_evidence | overall_ok, evidence_ok, plan_ok | 1:A12:immobilization_strategy, 2:A12:immobilization_strategy, 3:A12:enzyme_identity |
| enzyme_immobilization_answer_quality_v1 | aq_zrmof_condition_type | answer_quality | recommend | overall_ok, condition_type_ok | 1:A68:formulation_condition, 2:A28:formulation_condition, 3:B7:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_stream_no_contradiction_bcl | answer_quality | recommend_stream | overall_ok, evidence_ok, facts_ok | 1:B10:table_comparison_row, 2:A60:enzyme_identity, 3:A77:table_comparison_row |
| enzyme_immobilization_answer_quality_v1 | aq_curated_001_a11_formulation_condition | answer_quality | recommend | overall_ok, facts_ok | 1:A11:formulation_condition, 2:A11:formulation_condition, 3:A11:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_003_a11_formulation_condition | answer_quality | recommend | overall_ok, evidence_ok, facts_ok | 1:A11:formulation_condition, 2:A11:formulation_condition, 3:A11:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_004_a11_formulation_condition | answer_quality | recommend | overall_ok, facts_ok | 1:A11:formulation_condition, 2:A11:formulation_condition, 3:A11:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_005_a11_formulation_condition | answer_quality | recommend | overall_ok, facts_ok | 1:A11:formulation_condition, 2:A11:formulation_condition, 3:A11:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_007_a11_formulation_condition | answer_quality | recommend | overall_ok, evidence_ok, facts_ok | 1:A11:formulation_condition, 2:A11:formulation_condition, 3:A11:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_008_a12_formulation_condition | answer_quality | recommend | overall_ok, facts_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_010_a12_formulation_condition | answer_quality | recommend | overall_ok, evidence_ok, facts_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_011_a12_formulation_condition | answer_quality | recommend | overall_ok, evidence_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_012_a12_formulation_condition | answer_quality | recommend | overall_ok, evidence_ok, facts_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_013_a12_formulation_condition | answer_quality | recommend | overall_ok, evidence_ok, facts_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_015_a12_formulation_condition | answer_quality | recommend | overall_ok, evidence_ok, facts_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_016_a12_formulation_condition | answer_quality | recommend | overall_ok, facts_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_018_a14_performance_metric | answer_quality | recommend | overall_ok, facts_ok | 1:A14:performance_metric, 2:A14:enzyme_identity, 3:A14:immobilization_strategy |
| enzyme_immobilization_answer_quality_v1 | aq_curated_024_a23_performance_metric | answer_quality | recommend | overall_ok, evidence_ok | 1:A23:immobilization_strategy, 2:A23:immobilization_strategy, 3:A23:immobilization_strategy |
| enzyme_immobilization_answer_quality_v1 | aq_curated_039_a11_immobilization_strategy | answer_quality | recommend | overall_ok, evidence_ok, facts_ok | 1:A11:formulation_condition, 2:A11:formulation_condition, 3:A11:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_040_a12_immobilization_strategy | answer_quality | recommend | overall_ok, evidence_ok, facts_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_041_a15_immobilization_strategy | answer_quality | recommend | overall_ok, evidence_ok | 1:A15:formulation_condition, 2:A15:formulation_condition, 3:A15:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_042_a15_immobilization_strategy | answer_quality | recommend | overall_ok, evidence_ok | 1:A15:formulation_condition, 2:A15:formulation_condition, 3:A15:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_043_a15_immobilization_strategy | answer_quality | recommend | overall_ok, evidence_ok | 1:A15:formulation_condition, 2:A15:formulation_condition, 3:A15:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_044_a15_immobilization_strategy | answer_quality | recommend | overall_ok, evidence_ok | 1:A15:formulation_condition, 2:A15:formulation_condition, 3:A15:formulation_condition |
| enzyme_immobilization_answer_quality_v1 | aq_curated_045_a15_immobilization_strategy | answer_quality | recommend | overall_ok, evidence_ok | 1:A15:formulation_condition, 2:A15:formulation_condition, 3:A15:formulation_condition |
| enzyme_immobilization_formulation_optimizer_v1 | fo_curated_002_a11 | formulation | optimize | overall_ok, evidence_ok | 1:A11:formulation_condition, 2:A11:formulation_condition, 3:A11:formulation_condition |
| enzyme_immobilization_formulation_optimizer_v1 | fo_curated_007_a11 | formulation | optimize | overall_ok, evidence_ok | 1:A11:formulation_condition, 2:A11:formulation_condition, 3:A11:formulation_condition |
| enzyme_immobilization_formulation_optimizer_v1 | fo_curated_009_a12 | formulation | optimize | overall_ok, evidence_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_formulation_optimizer_v1 | fo_curated_012_a12 | formulation | optimize | overall_ok, evidence_ok | 1:A12:formulation_condition, 2:A12:formulation_condition, 3:A12:formulation_condition |
| enzyme_immobilization_formulation_optimizer_v1 | fo_cn_alias_rml_table_context | formulation | optimize | overall_ok, citation_ok | 1:A26:formulation_condition, 2:A20:formulation_condition, 3:A28:formulation_condition |
