from __future__ import annotations

import base64
from typing import Any, Dict, List, Literal, Optional

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


class DashboardSummaryResponse(ApiBaseModel):
    source_pdf_count: int = 0
    processed_docs: int = 0
    processed_pages: int = 0
    indexed_docs: int = 0
    indexed_pages: int = 0
    rag_chunks: int = 0
    table_records: int = 0
    evidence_records: int = 0
    curated_evidence_records: int = 0
    review_items: int = 0
    qdrant_points: Optional[int] = None
    qdrant_status: Optional[str] = None
    stats_source: str
    collection: str


class IngestionFileUpload(ApiBaseModel):
    filename: str
    content_base64: str

    @field_validator("filename")
    @classmethod
    def filename_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("filename must not be empty")
        return value.strip()

    @field_validator("content_base64")
    @classmethod
    def content_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content_base64 must not be empty")
        return value.strip()

    def decode(self) -> bytes:
        return base64.b64decode(self.content_base64, validate=True)


class IngestionUploadRequest(ApiBaseModel):
    files: List[IngestionFileUpload] = Field(default_factory=list)
    paths: List[str] = Field(default_factory=list)
    uploaded_by: str = "api"
    run_pipeline: bool = False

    @field_validator("uploaded_by")
    @classmethod
    def uploaded_by_must_not_be_empty(cls, value: str) -> str:
        return value.strip() or "api"


class IngestionDocumentSummary(ApiBaseModel):
    document_id: str
    source_pdf: str
    sha256: str
    page_count: int
    status: str
    duplicate: bool = False
    job_id: Optional[str] = None
    collection: Optional[str] = None
    updated_at: str
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None


class IngestionUploadResponse(ApiBaseModel):
    batch_id: str
    documents: List[IngestionDocumentSummary]


class IngestionJobSummary(ApiBaseModel):
    job_id: str
    document_id: str
    stage: str
    status: str
    attempt: int
    created_at: str
    updated_at: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class IngestionDocumentDetail(ApiBaseModel):
    document: Dict[str, Any]
    jobs: List[IngestionJobSummary]


class IngestionBatchDetail(ApiBaseModel):
    batch_id: str
    created_at: str
    uploaded_by: str
    documents: List[IngestionDocumentSummary]


class IngestionSummaryResponse(ApiBaseModel):
    total_documents: int = 0
    queued_jobs: int = 0
    running_jobs: int = 0
    failed_documents: int = 0
    searchable_documents: int = 0
    needs_review_documents: int = 0
    status_counts: Dict[str, int] = Field(default_factory=dict)


class EvidenceCurationRequest(ApiBaseModel):
    action: Literal["accept", "edit", "reject"]
    reviewer: str = "manual"
    reason: str = ""
    edited_record: Optional[Dict[str, Any]] = None
    allow_severe: bool = False

    @field_validator("reviewer")
    @classmethod
    def reviewer_must_not_be_empty(cls, value: str) -> str:
        return value.strip() or "manual"


class EvidenceCurationResponse(ApiBaseModel):
    decision: Dict[str, Any]
    curated_records: int
