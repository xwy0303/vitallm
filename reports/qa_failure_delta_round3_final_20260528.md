# QA 232 Round3 Final Failure Delta

## Summary

- Before: 190/232 pass_rate=0.819
- After: 197/232 pass_rate=0.849
- Fixed cases: 13
- New regressions: 6
- Still failed: 29

## Retrieval Metrics

- recall_at_5: 0.774 -> 0.824
- mrr_at_5: 0.652 -> 0.695
- ndcg_at_5: 0.680 -> 0.723
- plan_accuracy: 0.940 -> 0.953
- forbidden_hit_rate: 0.000 -> 0.000

## Safety / Grounding Metrics

- no_answer.no_answer_accuracy: 1.000 -> 1.000
- no_answer.unexpected_candidate_rate: 0.000 -> 0.000
- no_answer.unexpected_citation_rate: 0.000 -> 0.000
- answer_quality.citation_accuracy: 1.000 -> 1.000
- answer_quality.faithfulness: 1.000 -> 1.000
- answer_quality.stream_final_consistency: 1.000 -> 1.000
- formulation.evidence_backed_change_rate: 0.957 -> 0.957
- formulation.unsafe_global_optimum_claim_count: 0.000 -> 0.000

## Bucket Delta

| Bucket | Before | After | Delta |
| --- | ---: | ---: | ---: |
| citation_mismatch | 1 | 1 | +0 |
| document_hit_source_missing | 17 | 16 | -1 |
| document_missing | 5 | 6 | +1 |
| evidence_mismatch | 2 | 2 | +0 |
| plan_mismatch | 9 | 9 | +0 |
| record_type_mismatch | 8 | 0 | -8 |
| response_selection_mismatch | 0 | 1 | +1 |

## Fixed Cases

- `rq_lit_strategy_003_a15` (search_evidence): document_hit_source_missing
- `rq_lit_strategy_020_a28` (search_evidence): document_hit_source_missing
- `aq_stream_no_contradiction_bcl` (recommend_stream): evidence_mismatch
- `aq_curated_007_a11_formulation_condition` (recommend): document_hit_source_missing
- `aq_curated_011_a12_formulation_condition` (recommend): document_hit_source_missing
- `aq_curated_015_a12_formulation_condition` (recommend): document_hit_source_missing
- `aq_curated_024_a23_performance_metric` (recommend): record_type_mismatch
- `aq_curated_039_a11_immobilization_strategy` (recommend): record_type_mismatch
- `aq_curated_040_a12_immobilization_strategy` (recommend): record_type_mismatch
- `aq_curated_041_a15_immobilization_strategy` (recommend): record_type_mismatch
- `aq_curated_043_a15_immobilization_strategy` (recommend): record_type_mismatch
- `aq_curated_045_a15_immobilization_strategy` (recommend): record_type_mismatch
- `fo_curated_002_a11` (optimize): document_hit_source_missing

## New Regressions

- `rq_cross_zif8_reuse_sds_bcl` (search_evidence): evidence_mismatch / overall_ok, evidence_ok
- `rq_cross_uio66_pfl_ays` (search_evidence): evidence_mismatch / overall_ok, evidence_ok
- `aq_curated_002_a11_formulation_condition` (recommend): document_hit_source_missing / overall_ok, evidence_ok
- `aq_curated_014_a12_formulation_condition` (recommend): document_hit_source_missing / overall_ok, evidence_ok
- `aq_curated_016_a12_formulation_condition` (recommend): document_hit_source_missing / overall_ok, evidence_ok, facts_ok
- `fo_curated_006_a11` (optimize): document_hit_source_missing / overall_ok, evidence_ok
