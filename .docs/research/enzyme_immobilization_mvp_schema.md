# 生物酶固定化推荐 MVP Schema

## 定位

本 schema 面向 enzyme immobilization 配方推荐 MVP。底层数据模型不围绕“酶名 -> 固化剂”单表设计，而围绕：

```text
enzyme + immobilization strategy + formulation + evaluation context + metric + evidence
```

推荐系统必须在指定 enzyme、application context、objective 和约束条件下输出候选方案；不能把“最佳固化剂”表达为无条件全局最优。

## 核心原则

- LLM 负责理解、抽取、解释和报告生成；结构化数据负责事实、比较、排序和约束。
- 所有推荐必须连接 evidence records。
- 所有数值字段必须保留 unit。
- 缺失值使用 `null`，不得由模型静默补全。
- 必须区分 immobilization conditions、assay conditions、application conditions。
- ranking 由 objective 驱动，不由 LLM 直接拍脑袋。

## 1. Enzyme Identity

用于标准化用户输入的酶名称。

```json
{
  "enzyme_id": "enz_lipase_ec_3_1_1_3",
  "canonical_name": "lipase",
  "ec_number": "3.1.1.3",
  "synonyms": ["triacylglycerol lipase"],
  "source_organism": "Candida rugosa",
  "enzyme_form": "free enzyme",
  "sequence_or_uniprot": null,
  "molecular_weight_kda": null,
  "notes": null
}
```

关键字段：

- `canonical_name`
- `ec_number`
- `synonyms`
- `source_organism`
- `enzyme_form`
- `sequence_or_uniprot`

## 2. Immobilization Strategy

描述固定化方法和材料体系。底层 schema 不使用单一 `curing_agent` 字段，而拆分为 carrier、crosslinker、spacer_or_ligand、matrix_or_encapsulant 和 additives。

```json
{
  "strategy_id": "imm_001",
  "immobilization_method": "covalent_binding",
  "method_family": "surface_attachment",
  "carrier": {
    "name": "chitosan beads",
    "material_class": "biopolymer",
    "properties": ["porous", "biocompatible"]
  },
  "crosslinker": {
    "name": "glutaraldehyde",
    "concentration": {
      "value": 2.5,
      "unit": "% v/v"
    }
  },
  "spacer_or_ligand": null,
  "matrix_or_encapsulant": null,
  "surface_activation": "glutaraldehyde activation",
  "toxicity_or_safety_notes": "glutaraldehyde residue risk"
}
```

`immobilization_method` 推荐枚举：

```text
adsorption
covalent_binding
crosslinking
entrapment
encapsulation
affinity_binding
CLEA
sol_gel
layer_by_layer
magnetic_nanoparticle_binding
```

## 3. Formulation

描述实际配方和固定化过程参数。

```json
{
  "formulation_id": "form_001",
  "enzyme": {
    "enzyme_id": "enz_lipase_ec_3_1_1_3",
    "amount": {
      "value": 10,
      "unit": "mg"
    }
  },
  "carrier_amount": {
    "value": 1,
    "unit": "g"
  },
  "enzyme_to_carrier_ratio": {
    "value": 10,
    "unit": "mg/g"
  },
  "additives": [
    {
      "name": "BSA",
      "concentration": {
        "value": 1,
        "unit": "mg/mL"
      },
      "role": "stabilizer"
    }
  ],
  "buffer": {
    "name": "phosphate buffer",
    "concentration": {
      "value": 50,
      "unit": "mM"
    },
    "pH": 7.0
  },
  "immobilization_conditions": {
    "temperature": {
      "value": 25,
      "unit": "degC"
    },
    "time": {
      "value": 4,
      "unit": "h"
    },
    "agitation": {
      "value": 150,
      "unit": "rpm"
    }
  }
}
```

高价值字段：

- `enzyme.amount`
- `carrier_amount`
- `enzyme_to_carrier_ratio`
- `additives`
- `buffer`
- `immobilization_conditions.temperature`
- `immobilization_conditions.time`
- `immobilization_conditions.agitation`

## 4. Evaluation Context

描述 assay、application 和外部 stress 条件。同一个 formulation 在不同 evaluation context 下不能直接比较。

```json
{
  "evaluation_context_id": "eval_001",
  "application": "biodiesel production",
  "substrate": {
    "name": "olive oil",
    "concentration": {
      "value": 10,
      "unit": "% v/v"
    }
  },
  "reaction_medium": "aqueous buffer",
  "assay_conditions": {
    "pH": 7.5,
    "temperature": {
      "value": 37,
      "unit": "degC"
    },
    "time": {
      "value": 30,
      "unit": "min"
    }
  },
  "stress_conditions": {
    "thermal_stability_test": {
      "temperature": {
        "value": 60,
        "unit": "degC"
      },
      "duration": {
        "value": 2,
        "unit": "h"
      }
    },
    "organic_solvent": null
  },
  "reuse_protocol": {
    "cycle_count": 10,
    "wash_method": "buffer wash",
    "cycle_duration": {
      "value": 30,
      "unit": "min"
    }
  }
}
```

## 5. Performance Metrics

用于推荐排序和证据比较。

```json
{
  "metric_id": "metric_001",
  "formulation_id": "form_001",
  "evaluation_context_id": "eval_001",
  "metrics": {
    "immobilization_yield": {
      "value": 82.4,
      "unit": "%"
    },
    "activity_recovery": {
      "value": 76.1,
      "unit": "%"
    },
    "relative_activity": {
      "value": 135,
      "unit": "% vs free enzyme"
    },
    "residual_activity_after_reuse": {
      "value": 68,
      "unit": "%",
      "cycle": 10
    },
    "thermal_stability_half_life": {
      "value": 5.2,
      "unit": "h",
      "temperature": {
        "value": 60,
        "unit": "degC"
      }
    },
    "storage_stability": {
      "value": 80,
      "unit": "%",
      "duration": {
        "value": 30,
        "unit": "day"
      }
    },
    "km": null,
    "vmax": null,
    "leaching_rate": null
  }
}
```

第一版重点抽取指标：

```text
immobilization_yield
activity_recovery
relative_activity
residual_activity_after_reuse
reuse_cycles
thermal_stability
pH_stability
storage_stability
Km
Vmax
leaching_rate
```

## 6. Evidence Record

用于追溯推荐依据和限制模型幻觉。

```json
{
  "evidence_id": "ev_001",
  "source_type": "paper",
  "title": "Immobilization of lipase on chitosan beads...",
  "doi": "10.xxxx/xxxxx",
  "year": 2021,
  "journal": "Biochemical Engineering Journal",
  "page": "5",
  "table_or_figure": "Table 2",
  "quoted_span": "The immobilized enzyme retained 68% activity after 10 cycles...",
  "extraction_confidence": 0.87,
  "evidence_type": "direct_experimental_result",
  "evidence_quality": "medium",
  "limitations": [
    "single enzyme source",
    "no industrial-scale validation",
    "substrate differs from user target"
  ]
}
```

`evidence_type` 推荐枚举：

```text
direct_experimental_result
comparative_experiment
review_claim
inferred_from_related_enzyme
model_prediction
user_provided_claim
```

高置信推荐只应主要依赖：

- `direct_experimental_result`
- `comparative_experiment`

## 最小核心表

第一版数据库至少包含：

```text
enzymes
immobilization_strategies
formulations
evaluation_contexts
performance_metrics
evidence_records
recommendation_cases
```

关系：

```text
enzyme 1 -- n formulation
immobilization_strategy 1 -- n formulation
formulation 1 -- n performance_metrics
performance_metrics n -- 1 evaluation_context
formulation n -- n evidence_records
recommendation_case n -- n formulation
```

## Recommendation Input Schema

用户请求必须包含或推断 objective。若用户只给 enzyme name，系统应追问目标函数。

```json
{
  "query_type": "recommend_immobilization_agent",
  "enzyme_name": "lipase",
  "enzyme_source": "Candida rugosa",
  "objective": {
    "primary": "maximize_reuse_stability",
    "secondary": ["maintain_activity", "low_toxicity"]
  },
  "application_context": {
    "substrate": "olive oil",
    "reaction_medium": "aqueous",
    "temperature": {
      "value": 40,
      "unit": "degC"
    },
    "pH": 7.5
  },
  "constraints": {
    "food_grade_required": false,
    "avoid_toxic_crosslinker": false,
    "max_temperature": null,
    "available_materials": []
  }
}
```

当 objective 缺失时，优先追问：

```text
你希望优化哪个目标：activity recovery、thermal stability、reuse cycles、organic solvent tolerance、food-grade safety，还是 cost？
```

## Recommendation Output Schema

```json
{
  "recommendation_id": "rec_001",
  "answer_type": "ranked_candidates",
  "target_enzyme": "lipase",
  "objective": "maximize_reuse_stability",
  "candidates": [
    {
      "rank": 1,
      "strategy_summary": "chitosan beads activated by glutaraldehyde",
      "carrier": "chitosan beads",
      "crosslinker": "glutaraldehyde",
      "recommended_conditions": {
        "enzyme_to_carrier_ratio": "10 mg/g",
        "pH": 7.0,
        "temperature": "25 degC",
        "time": "4 h"
      },
      "expected_benefits": [
        "higher reuse stability",
        "good activity recovery"
      ],
      "risks": [
        "glutaraldehyde residue risk",
        "possible activity loss from excessive crosslinking"
      ],
      "evidence_ids": ["ev_001", "ev_002"],
      "confidence": "medium"
    }
  ],
  "abstention_reason": null,
  "next_experiment_suggestions": [
    {
      "variable": "glutaraldehyde concentration",
      "range": ["0.5%", "1.0%", "2.5%"],
      "metric": "activity recovery and reuse residual activity"
    }
  ]
}
```

## MVP 必须保留字段

```text
enzyme_name
ec_number
source_organism
immobilization_method
carrier
crosslinker
enzyme_to_carrier_ratio
additives
pH
temperature
time
substrate
application
activity_recovery
immobilization_yield
residual_activity_after_reuse
reuse_cycles
thermal_stability
storage_stability
doi
evidence_span
evidence_type
confidence
limitations
```

## MVP 下一步

推荐实现顺序：

1. 定义 Pydantic models / JSON Schema，锁定数据契约。
2. 建立 paper ingestion pipeline，先处理 10-30 篇论文。
3. 做 evidence extraction prompt，输出严格 JSON。
4. 建立本地结构化库和向量索引。
5. 实现 objective-driven ranking。
6. 实现推荐报告生成，强制引用 evidence ids。
