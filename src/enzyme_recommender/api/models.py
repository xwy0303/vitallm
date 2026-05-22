from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RecommendByEnzymeApiRequest(ApiBaseModel):
    enzyme_name: str
    objective: str = "recommend_best_immobilization_agent"
    application_context: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)
    collection: Optional[str] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=100)

    @field_validator("enzyme_name")
    @classmethod
    def enzyme_name_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("enzyme_name must not be empty")
        return value.strip()


class OptimizeFormulationApiRequest(ApiBaseModel):
    enzyme_name: str
    user_formulation: Dict[str, Any]
    objective: str = "optimize_formulation"
    application_context: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)
    collection: Optional[str] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=100)

    @field_validator("enzyme_name")
    @classmethod
    def enzyme_name_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("enzyme_name must not be empty")
        return value.strip()

    @field_validator("user_formulation")
    @classmethod
    def formulation_must_not_be_empty(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not value:
            raise ValueError("user_formulation must not be empty")
        return value


class SearchEvidenceApiRequest(ApiBaseModel):
    query: str
    collection: Optional[str] = None
    point_type: Optional[str] = None
    usable_only: Optional[bool] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=100)

    @field_validator("query")
    @classmethod
    def query_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be empty")
        return value.strip()


class HealthResponse(ApiBaseModel):
    status: str
    generator_provider: str
    vector_store: str
    collection: str
