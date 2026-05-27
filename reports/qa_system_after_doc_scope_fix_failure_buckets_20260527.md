# QA Benchmark Failure Buckets After Chinese Alias / Document Scope Fix

生成日期：2026-05-27

## 220 Benchmark

- 结果：172/220 passed，failed=48
- pass_rate：0.782

### Failure Bucket Counts

| Bucket | Count |
| --- | ---: |
| evidence_miss | 39 |
| answer_fact_miss | 15 |
| plan_intent | 14 |
| condition_type | 1 |

### Failure Combo Counts

| Combo | Count |
| --- | ---: |
| evidence_miss | 18 |
| plan_intent+evidence_miss | 12 |
| evidence_miss+answer_fact_miss | 9 |
| answer_fact_miss | 6 |
| plan_intent | 2 |
| condition_type | 1 |

### Failed By Kind

| Kind | Count |
| --- | ---: |
| answer_quality | 23 |
| positive | 21 |
| formulation | 4 |

### Failed By Endpoint

| Endpoint | Count |
| --- | ---: |
| recommend | 22 |
| search_evidence | 21 |
| optimize | 4 |
| recommend_stream | 1 |

### Concentrated Document Mentions

| Document | Failed Case Count |
| --- | ---: |
| A15 | 13 |
| A12 | 12 |
| A11 | 11 |
| A28 | 1 |
| A29 | 1 |
| A14 | 1 |
| A23 | 1 |

### Failed Case IDs

- `rq_user_like_temperature_not_always_higher` [positive/search_evidence/hard] evidence_miss - ZIF8 固定化脂肪酶做生物柴油时温度是不是越高越好？
- `rq_lit_strategy_003_a15` [positive/search_evidence/easy] evidence_miss - A15 lipase immobilized on ZIF-8 immobilization strategy
- `rq_lit_strategy_004_a15` [positive/search_evidence/easy] evidence_miss - A15 lipase immobilized on ZIF-8 immobilization strategy
- `rq_lit_strategy_020_a28` [positive/search_evidence/easy] evidence_miss - A28 lipase immobilized on ZIF-8 immobilization strategy
- `rq_lit_strategy_023_a29` [positive/search_evidence/easy] evidence_miss - A29 lipase immobilized on ZIF-8 immobilization strategy
- `rq_user_paraphrase_071_a11` [positive/search_evidence/medium] plan_intent+evidence_miss - ZIF-8 这种载体和普通吸附相比，有没有更适合先试的理由？
- `rq_user_paraphrase_072_a12` [positive/search_evidence/medium] plan_intent - 这个 A12 里面的 ZIF-8 固定化脂肪酶，主要是什么策略？
- `rq_user_paraphrase_073_a15` [positive/search_evidence/medium] evidence_miss - A15 那个脂肪酶材料能复用几次，稳定性数据在哪？
- `rq_user_paraphrase_074_a15` [positive/search_evidence/medium] plan_intent+evidence_miss - 我想复现实验，A15 的 lipase 固定化 pH、温度、时间怎么设？
- `rq_user_paraphrase_075_a15` [positive/search_evidence/medium] plan_intent+evidence_miss - ZIF-8 这种载体和普通吸附相比，有没有更适合先试的理由？
- `rq_user_paraphrase_076_a15` [positive/search_evidence/medium] plan_intent+evidence_miss - 这个 A15 里面的 ZIF-8 固定化脂肪酶，主要是什么策略？
- `rq_user_paraphrase_077_a15` [positive/search_evidence/medium] evidence_miss - A15 那个脂肪酶材料能复用几次，稳定性数据在哪？
- `rq_user_paraphrase_078_a15` [positive/search_evidence/medium] plan_intent+evidence_miss - 我想复现实验，A15 的 lipase 固定化 pH、温度、时间怎么设？
- `rq_user_paraphrase_079_a15` [positive/search_evidence/medium] plan_intent+evidence_miss - ZIF-8 这种载体和普通吸附相比，有没有更适合先试的理由？
- `rq_user_paraphrase_080_a15` [positive/search_evidence/medium] plan_intent+evidence_miss - 这个 A15 里面的 ZIF-8 固定化脂肪酶，主要是什么策略？
- `rq_user_paraphrase_081_a11` [positive/search_evidence/medium] plan_intent - A11 那个脂肪酶材料能复用几次，稳定性数据在哪？
- `rq_user_paraphrase_083_a11` [positive/search_evidence/medium] plan_intent+evidence_miss - MOF/载体 这种载体和普通吸附相比，有没有更适合先试的理由？
- `rq_user_paraphrase_084_a11` [positive/search_evidence/medium] plan_intent+evidence_miss - 这个 A11 里面的 MOF/载体 固定化脂肪酶，主要是什么策略？
- `rq_user_paraphrase_085_a11` [positive/search_evidence/medium] plan_intent+evidence_miss - A11 那个脂肪酶材料能复用几次，稳定性数据在哪？
- `rq_user_paraphrase_087_a11` [positive/search_evidence/medium] plan_intent+evidence_miss - MOF/载体 这种载体和普通吸附相比，有没有更适合先试的理由？
- `rq_user_paraphrase_088_a12` [positive/search_evidence/medium] plan_intent+evidence_miss - 这个 A12 里面的 MOF/载体 固定化脂肪酶，主要是什么策略？
- `aq_zrmof_condition_type` [answer_quality/recommend/hard] condition_type - Zr-MOF 固定化脂肪酶时最佳 pH 和温度是多少？
- `aq_stream_no_contradiction_bcl` [answer_quality/recommend_stream/medium] evidence_miss+answer_fact_miss - 伯克霍尔德菌脂肪酶做生物柴油用啥载体更稳？
- `aq_curated_001_a11_formulation_condition` [answer_quality/recommend/medium] answer_fact_miss - A11 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_003_a11_formulation_condition` [answer_quality/recommend/medium] evidence_miss+answer_fact_miss - A11 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_004_a11_formulation_condition` [answer_quality/recommend/hard] answer_fact_miss - A11 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_005_a11_formulation_condition` [answer_quality/recommend/medium] answer_fact_miss - A11 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_007_a11_formulation_condition` [answer_quality/recommend/medium] evidence_miss+answer_fact_miss - A11 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_008_a12_formulation_condition` [answer_quality/recommend/hard] answer_fact_miss - A12 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_010_a12_formulation_condition` [answer_quality/recommend/medium] evidence_miss+answer_fact_miss - A12 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_011_a12_formulation_condition` [answer_quality/recommend/medium] evidence_miss - A12 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_012_a12_formulation_condition` [answer_quality/recommend/hard] evidence_miss+answer_fact_miss - A12 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_013_a12_formulation_condition` [answer_quality/recommend/medium] evidence_miss+answer_fact_miss - A12 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_015_a12_formulation_condition` [answer_quality/recommend/medium] evidence_miss+answer_fact_miss - A12 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_016_a12_formulation_condition` [answer_quality/recommend/hard] answer_fact_miss - A12 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_018_a14_performance_metric` [answer_quality/recommend/medium] answer_fact_miss - A14 的固定化脂肪酶复用/稳定性结果是什么？
- `aq_curated_024_a23_performance_metric` [answer_quality/recommend/hard] evidence_miss - A23 的固定化脂肪酶复用/稳定性结果是什么？
- `aq_curated_039_a11_immobilization_strategy` [answer_quality/recommend/medium] evidence_miss+answer_fact_miss - A11 文献推荐的脂肪酶固定化载体/方法是什么？
- `aq_curated_040_a12_immobilization_strategy` [answer_quality/recommend/hard] evidence_miss+answer_fact_miss - A12 文献推荐的脂肪酶固定化载体/方法是什么？
- `aq_curated_041_a15_immobilization_strategy` [answer_quality/recommend/medium] evidence_miss - A15 文献推荐的脂肪酶固定化载体/方法是什么？
- `aq_curated_042_a15_immobilization_strategy` [answer_quality/recommend/medium] evidence_miss - A15 文献推荐的脂肪酶固定化载体/方法是什么？
- `aq_curated_043_a15_immobilization_strategy` [answer_quality/recommend/medium] evidence_miss - A15 文献推荐的脂肪酶固定化载体/方法是什么？
- `aq_curated_044_a15_immobilization_strategy` [answer_quality/recommend/hard] evidence_miss - A15 文献推荐的脂肪酶固定化载体/方法是什么？
- `aq_curated_045_a15_immobilization_strategy` [answer_quality/recommend/medium] evidence_miss - A15 文献推荐的脂肪酶固定化载体/方法是什么？
- `fo_curated_002_a11` [formulation/optimize/medium] evidence_miss - A11 lipase 固定化配方 starting point：carrier=ZIF-8, pH 7.0, 25 C, 60 min。
- `fo_curated_007_a11` [formulation/optimize/medium] evidence_miss - A11 lipase 固定化配方 starting point：carrier=ZIF-8, pH 7.0, 25 C, 60 min。
- `fo_curated_009_a12` [formulation/optimize/hard] evidence_miss - A12 lipase 固定化配方 starting point：carrier=ZIF-8, pH 7.0, 25 C, 60 min。
- `fo_curated_012_a12` [formulation/optimize/hard] evidence_miss - A12 lipase 固定化配方 starting point：carrier=ZIF-8, pH 7.0, 25 C, 60 min。

## 232 Benchmark

- 结果：183/232 passed，failed=49
- pass_rate：0.789

### Failure Bucket Counts

| Bucket | Count |
| --- | ---: |
| evidence_miss | 39 |
| answer_fact_miss | 15 |
| plan_intent | 14 |
| condition_type | 1 |
| citation_grounding | 1 |

### Failure Combo Counts

| Combo | Count |
| --- | ---: |
| evidence_miss | 18 |
| plan_intent+evidence_miss | 12 |
| evidence_miss+answer_fact_miss | 9 |
| answer_fact_miss | 6 |
| plan_intent | 2 |
| condition_type | 1 |
| citation_grounding | 1 |

### Failed By Kind

| Kind | Count |
| --- | ---: |
| answer_quality | 23 |
| positive | 21 |
| formulation | 5 |

### Failed By Endpoint

| Endpoint | Count |
| --- | ---: |
| recommend | 22 |
| search_evidence | 21 |
| optimize | 5 |
| recommend_stream | 1 |

### Concentrated Document Mentions

| Document | Failed Case Count |
| --- | ---: |
| A15 | 13 |
| A12 | 12 |
| A11 | 11 |
| A28 | 1 |
| A29 | 1 |
| A14 | 1 |
| A23 | 1 |

### Failed Case IDs

- `rq_user_like_temperature_not_always_higher` [positive/search_evidence/hard] evidence_miss - ZIF8 固定化脂肪酶做生物柴油时温度是不是越高越好？
- `rq_lit_strategy_003_a15` [positive/search_evidence/easy] evidence_miss - A15 lipase immobilized on ZIF-8 immobilization strategy
- `rq_lit_strategy_004_a15` [positive/search_evidence/easy] evidence_miss - A15 lipase immobilized on ZIF-8 immobilization strategy
- `rq_lit_strategy_020_a28` [positive/search_evidence/easy] evidence_miss - A28 lipase immobilized on ZIF-8 immobilization strategy
- `rq_lit_strategy_023_a29` [positive/search_evidence/easy] evidence_miss - A29 lipase immobilized on ZIF-8 immobilization strategy
- `rq_user_paraphrase_071_a11` [positive/search_evidence/medium] plan_intent+evidence_miss - ZIF-8 这种载体和普通吸附相比，有没有更适合先试的理由？
- `rq_user_paraphrase_072_a12` [positive/search_evidence/medium] plan_intent - 这个 A12 里面的 ZIF-8 固定化脂肪酶，主要是什么策略？
- `rq_user_paraphrase_073_a15` [positive/search_evidence/medium] evidence_miss - A15 那个脂肪酶材料能复用几次，稳定性数据在哪？
- `rq_user_paraphrase_074_a15` [positive/search_evidence/medium] plan_intent+evidence_miss - 我想复现实验，A15 的 lipase 固定化 pH、温度、时间怎么设？
- `rq_user_paraphrase_075_a15` [positive/search_evidence/medium] plan_intent+evidence_miss - ZIF-8 这种载体和普通吸附相比，有没有更适合先试的理由？
- `rq_user_paraphrase_076_a15` [positive/search_evidence/medium] plan_intent+evidence_miss - 这个 A15 里面的 ZIF-8 固定化脂肪酶，主要是什么策略？
- `rq_user_paraphrase_077_a15` [positive/search_evidence/medium] evidence_miss - A15 那个脂肪酶材料能复用几次，稳定性数据在哪？
- `rq_user_paraphrase_078_a15` [positive/search_evidence/medium] plan_intent+evidence_miss - 我想复现实验，A15 的 lipase 固定化 pH、温度、时间怎么设？
- `rq_user_paraphrase_079_a15` [positive/search_evidence/medium] plan_intent+evidence_miss - ZIF-8 这种载体和普通吸附相比，有没有更适合先试的理由？
- `rq_user_paraphrase_080_a15` [positive/search_evidence/medium] plan_intent+evidence_miss - 这个 A15 里面的 ZIF-8 固定化脂肪酶，主要是什么策略？
- `rq_user_paraphrase_081_a11` [positive/search_evidence/medium] plan_intent - A11 那个脂肪酶材料能复用几次，稳定性数据在哪？
- `rq_user_paraphrase_083_a11` [positive/search_evidence/medium] plan_intent+evidence_miss - MOF/载体 这种载体和普通吸附相比，有没有更适合先试的理由？
- `rq_user_paraphrase_084_a11` [positive/search_evidence/medium] plan_intent+evidence_miss - 这个 A11 里面的 MOF/载体 固定化脂肪酶，主要是什么策略？
- `rq_user_paraphrase_085_a11` [positive/search_evidence/medium] plan_intent+evidence_miss - A11 那个脂肪酶材料能复用几次，稳定性数据在哪？
- `rq_user_paraphrase_087_a11` [positive/search_evidence/medium] plan_intent+evidence_miss - MOF/载体 这种载体和普通吸附相比，有没有更适合先试的理由？
- `rq_user_paraphrase_088_a12` [positive/search_evidence/medium] plan_intent+evidence_miss - 这个 A12 里面的 MOF/载体 固定化脂肪酶，主要是什么策略？
- `aq_zrmof_condition_type` [answer_quality/recommend/hard] condition_type - Zr-MOF 固定化脂肪酶时最佳 pH 和温度是多少？
- `aq_stream_no_contradiction_bcl` [answer_quality/recommend_stream/medium] evidence_miss+answer_fact_miss - 伯克霍尔德菌脂肪酶做生物柴油用啥载体更稳？
- `aq_curated_001_a11_formulation_condition` [answer_quality/recommend/medium] answer_fact_miss - A11 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_003_a11_formulation_condition` [answer_quality/recommend/medium] evidence_miss+answer_fact_miss - A11 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_004_a11_formulation_condition` [answer_quality/recommend/hard] answer_fact_miss - A11 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_005_a11_formulation_condition` [answer_quality/recommend/medium] answer_fact_miss - A11 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_007_a11_formulation_condition` [answer_quality/recommend/medium] evidence_miss+answer_fact_miss - A11 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_008_a12_formulation_condition` [answer_quality/recommend/hard] answer_fact_miss - A12 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_010_a12_formulation_condition` [answer_quality/recommend/medium] evidence_miss+answer_fact_miss - A12 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_011_a12_formulation_condition` [answer_quality/recommend/medium] evidence_miss - A12 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_012_a12_formulation_condition` [answer_quality/recommend/hard] evidence_miss+answer_fact_miss - A12 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_013_a12_formulation_condition` [answer_quality/recommend/medium] evidence_miss+answer_fact_miss - A12 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_015_a12_formulation_condition` [answer_quality/recommend/medium] evidence_miss+answer_fact_miss - A12 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_016_a12_formulation_condition` [answer_quality/recommend/hard] answer_fact_miss - A12 这篇里脂肪酶固定化条件怎么设？请回答关键 pH、温度、时间或用量。
- `aq_curated_018_a14_performance_metric` [answer_quality/recommend/medium] answer_fact_miss - A14 的固定化脂肪酶复用/稳定性结果是什么？
- `aq_curated_024_a23_performance_metric` [answer_quality/recommend/hard] evidence_miss - A23 的固定化脂肪酶复用/稳定性结果是什么？
- `aq_curated_039_a11_immobilization_strategy` [answer_quality/recommend/medium] evidence_miss+answer_fact_miss - A11 文献推荐的脂肪酶固定化载体/方法是什么？
- `aq_curated_040_a12_immobilization_strategy` [answer_quality/recommend/hard] evidence_miss+answer_fact_miss - A12 文献推荐的脂肪酶固定化载体/方法是什么？
- `aq_curated_041_a15_immobilization_strategy` [answer_quality/recommend/medium] evidence_miss - A15 文献推荐的脂肪酶固定化载体/方法是什么？
- `aq_curated_042_a15_immobilization_strategy` [answer_quality/recommend/medium] evidence_miss - A15 文献推荐的脂肪酶固定化载体/方法是什么？
- `aq_curated_043_a15_immobilization_strategy` [answer_quality/recommend/medium] evidence_miss - A15 文献推荐的脂肪酶固定化载体/方法是什么？
- `aq_curated_044_a15_immobilization_strategy` [answer_quality/recommend/hard] evidence_miss - A15 文献推荐的脂肪酶固定化载体/方法是什么？
- `aq_curated_045_a15_immobilization_strategy` [answer_quality/recommend/medium] evidence_miss - A15 文献推荐的脂肪酶固定化载体/方法是什么？
- `fo_curated_002_a11` [formulation/optimize/medium] evidence_miss - A11 lipase 固定化配方 starting point：carrier=ZIF-8, pH 7.0, 25 C, 60 min。
- `fo_curated_007_a11` [formulation/optimize/medium] evidence_miss - A11 lipase 固定化配方 starting point：carrier=ZIF-8, pH 7.0, 25 C, 60 min。
- `fo_curated_009_a12` [formulation/optimize/hard] evidence_miss - A12 lipase 固定化配方 starting point：carrier=ZIF-8, pH 7.0, 25 C, 60 min。
- `fo_curated_012_a12` [formulation/optimize/hard] evidence_miss - A12 lipase 固定化配方 starting point：carrier=ZIF-8, pH 7.0, 25 C, 60 min。
- `fo_cn_alias_rml_table_context` [formulation/optimize/medium] citation_grounding - 米根霉脂肪酶 固定化条件怎么优化？关注 sunflower oil 和 methanol。

