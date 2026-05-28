# QA Failure Debug

- Total: 197/232 passed
- Failed: 35
- Pass rate: 0.849

## By Bucket

| Bucket | Count |
| --- | ---: |
| document_hit_source_missing | 16 |
| plan_mismatch | 9 |
| document_missing | 6 |
| evidence_mismatch | 2 |
| response_selection_mismatch | 1 |
| citation_mismatch | 1 |

## By Benchmark

| Benchmark | Count |
| --- | ---: |
| enzyme_immobilization_retrieval_quality_v1 | 21 |
| enzyme_immobilization_answer_quality_v1 | 9 |
| enzyme_immobilization_formulation_optimizer_v1 | 5 |

## By Endpoint

| Endpoint | Count |
| --- | ---: |
| search_evidence | 21 |
| recommend | 9 |
| optimize | 5 |

## By Expected Document

| Document | Count |
| --- | ---: |
| A15 | 11 |
| A11 | 10 |
| A12 | 9 |
| B10 | 2 |
| A29 | 1 |
| B19 | 1 |
| B16 | 1 |
| B18 | 1 |

## Failed Cases

| Case | Endpoint | Bucket | Failed checks | Expected doc in Top-8 | Expected source in Top-8 |
| --- | --- | --- | --- | --- | --- |
| rq_user_like_temperature_not_always_higher | search_evidence | document_missing | overall_ok, evidence_ok | False |  |
| rq_lit_strategy_004_a15 | search_evidence | document_hit_source_missing | overall_ok, evidence_ok | True | False |
| rq_lit_strategy_023_a29 | search_evidence | document_hit_source_missing | overall_ok, evidence_ok | True | False |
| rq_user_paraphrase_071_a11 | search_evidence | document_missing | overall_ok, evidence_ok | False | False |
| rq_user_paraphrase_072_a12 | search_evidence | plan_mismatch | overall_ok, plan_ok | True | True |
| rq_user_paraphrase_073_a15 | search_evidence | document_hit_source_missing | overall_ok, evidence_ok | True | False |
| rq_user_paraphrase_074_a15 | search_evidence | plan_mismatch | overall_ok, evidence_ok, plan_ok | True | False |
| rq_user_paraphrase_075_a15 | search_evidence | document_missing | overall_ok, evidence_ok | False | False |
| rq_user_paraphrase_076_a15 | search_evidence | plan_mismatch | overall_ok, evidence_ok, plan_ok | True | False |
| rq_user_paraphrase_077_a15 | search_evidence | document_hit_source_missing | overall_ok, evidence_ok | True | False |
| rq_user_paraphrase_078_a15 | search_evidence | plan_mismatch | overall_ok, evidence_ok, plan_ok | True | False |
| rq_user_paraphrase_079_a15 | search_evidence | document_missing | overall_ok, evidence_ok | False | False |
| rq_user_paraphrase_080_a15 | search_evidence | plan_mismatch | overall_ok, evidence_ok, plan_ok | True | False |
| rq_user_paraphrase_081_a11 | search_evidence | plan_mismatch | overall_ok, plan_ok | True | True |
| rq_user_paraphrase_083_a11 | search_evidence | document_missing | overall_ok, evidence_ok, plan_ok | False | False |
| rq_user_paraphrase_084_a11 | search_evidence | plan_mismatch | overall_ok, evidence_ok, plan_ok | True | False |
| rq_user_paraphrase_085_a11 | search_evidence | plan_mismatch | overall_ok, evidence_ok, plan_ok | True | False |
| rq_user_paraphrase_087_a11 | search_evidence | document_missing | overall_ok, evidence_ok, plan_ok | False | False |
| rq_user_paraphrase_088_a12 | search_evidence | plan_mismatch | overall_ok, evidence_ok, plan_ok | True | False |
| rq_cross_zif8_reuse_sds_bcl | search_evidence | evidence_mismatch | overall_ok, evidence_ok | True |  |
| rq_cross_uio66_pfl_ays | search_evidence | evidence_mismatch | overall_ok, evidence_ok | True |  |
| aq_curated_002_a11_formulation_condition | recommend | document_hit_source_missing | overall_ok, evidence_ok | True | False |
| aq_curated_003_a11_formulation_condition | recommend | document_hit_source_missing | overall_ok, evidence_ok | True | False |
| aq_curated_010_a12_formulation_condition | recommend | response_selection_mismatch | overall_ok, facts_ok | True | True |
| aq_curated_012_a12_formulation_condition | recommend | document_hit_source_missing | overall_ok, evidence_ok, facts_ok | True | False |
| aq_curated_013_a12_formulation_condition | recommend | document_hit_source_missing | overall_ok, evidence_ok, facts_ok | True | False |
| aq_curated_014_a12_formulation_condition | recommend | document_hit_source_missing | overall_ok, evidence_ok | True | False |
| aq_curated_016_a12_formulation_condition | recommend | document_hit_source_missing | overall_ok, evidence_ok, facts_ok | True | False |
| aq_curated_042_a15_immobilization_strategy | recommend | document_hit_source_missing | overall_ok, evidence_ok | True | False |
| aq_curated_044_a15_immobilization_strategy | recommend | document_hit_source_missing | overall_ok, evidence_ok | True | False |
| fo_curated_006_a11 | optimize | document_hit_source_missing | overall_ok, evidence_ok | True | False |
| fo_curated_007_a11 | optimize | document_hit_source_missing | overall_ok, evidence_ok | True | False |
| fo_curated_009_a12 | optimize | document_hit_source_missing | overall_ok, evidence_ok | True | False |
| fo_curated_012_a12 | optimize | document_hit_source_missing | overall_ok, evidence_ok | True | False |
| fo_cn_alias_rml_table_context | optimize | citation_mismatch | overall_ok, citation_ok |  |  |
