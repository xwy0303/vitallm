from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Quantity(StrictBaseModel):
    value: Optional[float] = None
    unit: Optional[str] = None

    @model_validator(mode="after")
    def require_unit_when_value_exists(self) -> "Quantity":
        if self.value is not None and not self.unit:
            raise ValueError("unit is required when value is provided")
        return self


class TimeQuantity(Quantity):
    pass


class TemperatureQuantity(Quantity):
    pass


class Concentration(Quantity):
    pass


class ImmobilizationMethod(str, Enum):
    adsorption = "adsorption"
    covalent_binding = "covalent_binding"
    crosslinking = "crosslinking"
    entrapment = "entrapment"
    encapsulation = "encapsulation"
    affinity_binding = "affinity_binding"
    clea = "CLEA"
    sol_gel = "sol_gel"
    layer_by_layer = "layer_by_layer"
    magnetic_nanoparticle_binding = "magnetic_nanoparticle_binding"


class EvidenceType(str, Enum):
    direct_experimental_result = "direct_experimental_result"
    comparative_experiment = "comparative_experiment"
    review_claim = "review_claim"
    inferred_from_related_enzyme = "inferred_from_related_enzyme"
    model_prediction = "model_prediction"
    user_provided_claim = "user_provided_claim"


class ConfidenceLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class EnzymeIdentity(StrictBaseModel):
    enzyme_id: str
    canonical_name: str
    ec_number: Optional[str] = None
    synonyms: List[str] = Field(default_factory=list)
    source_organism: Optional[str] = None
    enzyme_form: Optional[str] = None
    sequence_or_uniprot: Optional[str] = None
    molecular_weight_kda: Optional[float] = None
    notes: Optional[str] = None


class Carrier(StrictBaseModel):
    name: str
    material_class: Optional[str] = None
    properties: List[str] = Field(default_factory=list)


class Reagent(StrictBaseModel):
    name: str
    concentration: Optional[Concentration] = None
    role: Optional[str] = None


class ImmobilizationStrategy(StrictBaseModel):
    strategy_id: str
    immobilization_method: ImmobilizationMethod
    method_family: Optional[str] = None
    carrier: Optional[Carrier] = None
    crosslinker: Optional[Reagent] = None
    spacer_or_ligand: Optional[Reagent] = None
    matrix_or_encapsulant: Optional[Reagent] = None
    surface_activation: Optional[str] = None
    toxicity_or_safety_notes: Optional[str] = None


class EnzymeAmount(StrictBaseModel):
    enzyme_id: str
    amount: Optional[Quantity] = None


class Additive(StrictBaseModel):
    name: str
    concentration: Optional[Concentration] = None
    role: Optional[str] = None


class BufferCondition(StrictBaseModel):
    name: Optional[str] = None
    concentration: Optional[Concentration] = None
    pH: Optional[float] = None


class ImmobilizationConditions(StrictBaseModel):
    temperature: Optional[TemperatureQuantity] = None
    time: Optional[TimeQuantity] = None
    agitation: Optional[Quantity] = None
    notes: Optional[str] = None


class Formulation(StrictBaseModel):
    formulation_id: str
    enzyme: EnzymeAmount
    strategy_id: Optional[str] = None
    carrier_amount: Optional[Quantity] = None
    enzyme_to_carrier_ratio: Optional[Quantity] = None
    additives: List[Additive] = Field(default_factory=list)
    buffer: Optional[BufferCondition] = None
    immobilization_conditions: Optional[ImmobilizationConditions] = None
    notes: Optional[str] = None


class Substrate(StrictBaseModel):
    name: str
    concentration: Optional[Concentration] = None


class AssayConditions(StrictBaseModel):
    pH: Optional[float] = None
    temperature: Optional[TemperatureQuantity] = None
    time: Optional[TimeQuantity] = None
    notes: Optional[str] = None


class ThermalStabilityTest(StrictBaseModel):
    temperature: Optional[TemperatureQuantity] = None
    duration: Optional[TimeQuantity] = None


class StressConditions(StrictBaseModel):
    thermal_stability_test: Optional[ThermalStabilityTest] = None
    organic_solvent: Optional[str] = None
    pH_stress: Optional[str] = None
    notes: Optional[str] = None


class ReuseProtocol(StrictBaseModel):
    cycle_count: Optional[int] = None
    wash_method: Optional[str] = None
    cycle_duration: Optional[TimeQuantity] = None
    notes: Optional[str] = None


class EvaluationContext(StrictBaseModel):
    evaluation_context_id: str
    application: Optional[str] = None
    substrate: Optional[Substrate] = None
    reaction_medium: Optional[str] = None
    assay_conditions: Optional[AssayConditions] = None
    stress_conditions: Optional[StressConditions] = None
    reuse_protocol: Optional[ReuseProtocol] = None


class MetricValue(StrictBaseModel):
    value: Optional[float] = None
    unit: Optional[str] = None
    cycle: Optional[int] = None
    temperature: Optional[TemperatureQuantity] = None
    duration: Optional[TimeQuantity] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def require_unit_when_value_exists(self) -> "MetricValue":
        if self.value is not None and not self.unit:
            raise ValueError("unit is required when metric value is provided")
        return self


class PerformanceMetricSet(StrictBaseModel):
    immobilization_yield: Optional[MetricValue] = None
    activity_recovery: Optional[MetricValue] = None
    relative_activity: Optional[MetricValue] = None
    residual_activity_after_reuse: Optional[MetricValue] = None
    reuse_cycles: Optional[MetricValue] = None
    thermal_stability: Optional[MetricValue] = None
    thermal_stability_half_life: Optional[MetricValue] = None
    pH_stability: Optional[MetricValue] = None
    storage_stability: Optional[MetricValue] = None
    km: Optional[MetricValue] = None
    vmax: Optional[MetricValue] = None
    leaching_rate: Optional[MetricValue] = None

    @model_validator(mode="after")
    def require_at_least_one_metric(self) -> "PerformanceMetricSet":
        if not any(value is not None for value in self.model_dump().values()):
            raise ValueError("at least one performance metric is required")
        return self


class PerformanceMetrics(StrictBaseModel):
    metric_id: str
    formulation_id: str
    evaluation_context_id: str
    metrics: PerformanceMetricSet


class EvidenceRecord(StrictBaseModel):
    evidence_id: str
    source_type: Literal["paper", "patent", "dataset", "user_input", "other"] = "paper"
    title: Optional[str] = None
    doi: Optional[str] = None
    year: Optional[int] = None
    journal: Optional[str] = None
    page: Optional[str] = None
    table_or_figure: Optional[str] = None
    quoted_span: str
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    evidence_type: EvidenceType
    evidence_quality: ConfidenceLevel
    limitations: List[str] = Field(default_factory=list)
    source_file: Optional[str] = None
    source_sha256: Optional[str] = None
    mineru_task_id: Optional[str] = None

    @field_validator("quoted_span")
    @classmethod
    def quoted_span_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("quoted_span is required for traceability")
        return value


class ExtractionRecord(StrictBaseModel):
    record_id: str
    enzyme: EnzymeIdentity
    immobilization_strategy: ImmobilizationStrategy
    formulation: Formulation
    evaluation_context: EvaluationContext
    performance_metrics: PerformanceMetrics
    evidence_records: List[EvidenceRecord] = Field(min_length=1)
    extraction_notes: Optional[str] = None

    @model_validator(mode="after")
    def check_cross_references(self) -> "ExtractionRecord":
        if self.formulation.enzyme.enzyme_id != self.enzyme.enzyme_id:
            raise ValueError("formulation.enzyme.enzyme_id must match enzyme.enzyme_id")
        if self.formulation.strategy_id and self.formulation.strategy_id != self.immobilization_strategy.strategy_id:
            raise ValueError("formulation.strategy_id must match immobilization_strategy.strategy_id")
        if self.performance_metrics.formulation_id != self.formulation.formulation_id:
            raise ValueError("performance_metrics.formulation_id must match formulation.formulation_id")
        if self.performance_metrics.evaluation_context_id != self.evaluation_context.evaluation_context_id:
            raise ValueError(
                "performance_metrics.evaluation_context_id must match evaluation_context.evaluation_context_id"
            )
        return self


class Objective(StrictBaseModel):
    primary: str
    secondary: List[str] = Field(default_factory=list)


class ApplicationContext(StrictBaseModel):
    substrate: Optional[str] = None
    reaction_medium: Optional[str] = None
    temperature: Optional[TemperatureQuantity] = None
    pH: Optional[float] = None


class RecommendationConstraints(StrictBaseModel):
    food_grade_required: bool = False
    avoid_toxic_crosslinker: bool = False
    max_temperature: Optional[TemperatureQuantity] = None
    available_materials: List[str] = Field(default_factory=list)
    disallowed_materials: List[str] = Field(default_factory=list)


class RecommendationInput(StrictBaseModel):
    query_type: Literal["recommend_immobilization_agent", "optimize_formulation"]
    enzyme_name: str
    enzyme_source: Optional[str] = None
    objective: Objective
    application_context: Optional[ApplicationContext] = None
    constraints: RecommendationConstraints = Field(default_factory=RecommendationConstraints)
    user_formulation: Optional[Dict[str, Any]] = None


class RecommendedConditions(StrictBaseModel):
    enzyme_to_carrier_ratio: Optional[str] = None
    pH: Optional[float] = None
    temperature: Optional[str] = None
    time: Optional[str] = None
    additives: List[str] = Field(default_factory=list)


class CandidateRecommendation(StrictBaseModel):
    rank: int = Field(ge=1)
    strategy_summary: str
    carrier: Optional[str] = None
    crosslinker: Optional[str] = None
    recommended_conditions: RecommendedConditions = Field(default_factory=RecommendedConditions)
    expected_benefits: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(min_length=1)
    confidence: ConfidenceLevel


class ExperimentSuggestion(StrictBaseModel):
    variable: str
    range: List[str] = Field(default_factory=list)
    metric: str


class RecommendationOutput(StrictBaseModel):
    recommendation_id: str
    answer_type: Literal["ranked_candidates", "abstention"]
    target_enzyme: str
    objective: str
    candidates: List[CandidateRecommendation] = Field(default_factory=list)
    abstention_reason: Optional[str] = None
    next_experiment_suggestions: List[ExperimentSuggestion] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_answer_shape(self) -> "RecommendationOutput":
        if self.answer_type == "ranked_candidates" and not self.candidates:
            raise ValueError("ranked_candidates output requires at least one candidate")
        if self.answer_type == "abstention" and not self.abstention_reason:
            raise ValueError("abstention output requires abstention_reason")
        return self

