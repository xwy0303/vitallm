from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, TypeVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import ValidationError
from pypdf import PdfReader

from enzyme_recommender.api.models import (
    DashboardSummaryResponse,
    EvidenceCurationRequest,
    EvidenceCurationResponse,
    HealthResponse,
    IngestionBatchDetail,
    IngestionDocumentDetail,
    IngestionDocumentSummary,
    IngestionJobSummary,
    IngestionSummaryResponse,
    IngestionUploadRequest,
    IngestionUploadResponse,
    OptimizeFormulationApiRequest,
    RecommendByEnzymeApiRequest,
    SearchEvidenceApiRequest,
)
from enzyme_recommender.evidence.curation import append_curation_decision, rebuild_curated_evidence
from enzyme_recommender.ingestion.pipeline import IngestionPipeline, IngestionPipelineOptions, IngestionRunResult
from enzyme_recommender.ingestion.registry import IngestionDocument, IngestionJob, IngestionRegistry
from enzyme_recommender.rag.indexing import resolve_collection_name
from enzyme_recommender.rag.qdrant import QdrantRestClient
from enzyme_recommender.rag.retrieval import PointType
from enzyme_recommender.rag.retrieval import RetrievalHit, RetrievalResponse
from enzyme_recommender.recommendation import (
    EnzymeRecommendationRequest,
    FormulationOptimizationRequest,
    FormulationOptimizationService,
    RecommendationService,
)
from enzyme_recommender.recommendation.enzyme import deterministic_no_answer_generation, retrieval_guard_reason
from enzyme_recommender.generators import GenerationResponse
from enzyme_recommender.runtime import RuntimeServices
from enzyme_recommender.runtime.config import RuntimeConfigError


T = TypeVar("T")
PROJECT_DIR = Path(__file__).resolve().parents[3]
PDF_DIR = PROJECT_DIR / "MOF固定化脂肪酶文献调研"
ARTIFACT_ROOT = PROJECT_DIR / "artifacts"
RAG_INPUT_DIR = PROJECT_DIR / "artifacts" / "rag_inputs"
EVIDENCE_DIR = PROJECT_DIR / "artifacts" / "evidence"
REFERENCE_NEIGHBOR_WINDOW = 1
QDRANT_SCROLL_BATCH_SIZE = 256
DASHBOARD_SUMMARY_CACHE_TTL_SECONDS = 60.0
logger = logging.getLogger(__name__)
logging.getLogger("pypdf").setLevel(logging.ERROR)


def create_app(config_path: Optional[str | Path] = None) -> FastAPI:
    runtime = RuntimeServices.from_config_file(resolve_config_path(config_path))
    app = FastAPI(
        title="生机大模型 API",
        version="0.1.0",
        description="Evidence-first enzyme immobilization recommendation API.",
    )
    app.state.runtime = runtime
    app.state.dashboard_summary_cache = {}
    app.state.dashboard_summary_cache_lock = threading.Lock()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=parse_cors_origins(os.environ.get("ENZYME_API_CORS_ORIGINS")),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    register_routes(app)
    return app


def resolve_config_path(config_path: Optional[str | Path]) -> Path:
    value = config_path or os.environ.get("ENZYME_RUNTIME_CONFIG") or "configs/local.yaml"
    return Path(value).expanduser().resolve()


def parse_cors_origins(value: Optional[str]) -> list[str]:
    if not value:
        return [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:8001",
            "http://localhost:8001",
        ]
    return [item.strip() for item in value.split(",") if item.strip()]


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RuntimeConfigError)
    async def runtime_config_error_handler(_request: Request, exc: RuntimeConfigError) -> JSONResponse:
        return JSONResponse(status_code=500, content=error_payload("runtime_config_error", str(exc)))

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(_request: Request, exc: RuntimeError) -> JSONResponse:
        message = str(exc)
        status_code = 503 if "cannot connect" in message or "failed" in message else 500
        return JSONResponse(status_code=status_code, content=error_payload("runtime_error", message))

    @app.exception_handler(ValidationError)
    async def validation_error_handler(_request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content=error_payload("validation_error", exc.errors()))


def register_routes(app: FastAPI) -> None:
    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        runtime = get_runtime(app)
        return HealthResponse(
            status="ok",
            generator_provider=runtime.config.generator.provider,
            vector_store=runtime.config.vector_store.provider,
            collection=runtime.config.vector_store.collection,
        )

    @app.get("/api/dashboard/summary", response_model=DashboardSummaryResponse)
    def dashboard_summary() -> DashboardSummaryResponse:
        runtime = get_runtime(app)
        return get_cached_dashboard_summary(app, runtime)

    @app.post("/api/recommend/by-enzyme")
    def recommend_by_enzyme(payload: RecommendByEnzymeApiRequest) -> dict[str, Any]:
        response = recommend_by_enzyme_response(get_runtime(app), payload)
        return response.model_dump(mode="json")

    @app.post("/api/recommend/by-enzyme/stream")
    def recommend_by_enzyme_stream(payload: RecommendByEnzymeApiRequest) -> StreamingResponse:
        runtime = runtime_with_collection(get_runtime(app), payload.collection)
        service = RecommendationService(runtime)
        request = make_enzyme_recommendation_request(payload)
        return StreamingResponse(
            stream_recommendation_events(service, request),
            media_type="application/x-ndjson",
        )

    @app.post("/api/optimize/formulation")
    def optimize_formulation(payload: OptimizeFormulationApiRequest) -> dict[str, Any]:
        response = optimize_formulation_response(get_runtime(app), payload)
        return response.model_dump(mode="json")

    @app.post("/api/optimize/formulation/stream")
    def optimize_formulation_stream(payload: OptimizeFormulationApiRequest) -> StreamingResponse:
        runtime = runtime_with_collection(get_runtime(app), payload.collection)
        service = FormulationOptimizationService(runtime)
        request = make_formulation_optimization_request(payload)
        return StreamingResponse(
            stream_optimization_events(service, request),
            media_type="application/x-ndjson",
        )

    @app.post("/api/search/evidence")
    def search_evidence(payload: SearchEvidenceApiRequest) -> dict[str, Any]:
        runtime = runtime_with_collection(get_runtime(app), payload.collection)
        response = runtime.retriever().retrieve(
            query=payload.query,
            top_k=payload.top_k or runtime.config.retrieval.top_k,
            point_type=validate_point_type(payload.point_type),
            usable_only=runtime.config.retrieval.usable_only if payload.usable_only is None else payload.usable_only,
        )
        return enrich_retrieval_response(runtime, response).model_dump(mode="json")

    @app.get("/api/ingestion/summary", response_model=IngestionSummaryResponse)
    def ingestion_summary() -> IngestionSummaryResponse:
        registry = get_ingestion_registry()
        return build_ingestion_summary(registry)

    @app.post("/api/ingestion/uploads", response_model=IngestionUploadResponse)
    def ingestion_upload(payload: IngestionUploadRequest) -> IngestionUploadResponse:
        if not payload.files and not payload.paths:
            raise HTTPException(status_code=422, detail=error_payload("no_ingestion_inputs", "provide files or paths"))
        registry = get_ingestion_registry()
        registered = []
        for file_payload in payload.files:
            try:
                registered.append(
                    registry.register_pdf_bytes(
                        file_payload.filename,
                        file_payload.decode(),
                        uploaded_by=payload.uploaded_by,
                    )
                )
            except Exception as exc:
                raise HTTPException(status_code=422, detail=error_payload("invalid_pdf_upload", str(exc))) from exc
        for raw_path in payload.paths:
            try:
                registered.append(registry.register_pdf_path(Path(raw_path), uploaded_by=payload.uploaded_by))
            except Exception as exc:
                raise HTTPException(status_code=422, detail=error_payload("invalid_pdf_path", str(exc))) from exc

        batch = registry.create_batch(registered, uploaded_by=payload.uploaded_by)
        response_documents: list[IngestionDocumentSummary] = []
        for item in registered:
            document = registry.get_document(item.document.document_id) or item.document
            job = None
            if not item.duplicate or payload.run_pipeline:
                job = registry.create_job(document, metadata={"queued_by": "upload_api", "duplicate": item.duplicate})
            if payload.run_pipeline:
                assert job is not None
                try:
                    result = run_ingestion_pipeline(get_runtime(app), registry, document.document_id, job=job)
                    document = result.document
                    job = result.job
                except Exception as exc:
                    logger.exception("ingestion pipeline failed for %s", document.document_id)
                    document = registry.get_document(document.document_id) or document
                    job = registry.load_jobs().get(job.job_id, job)
                    if not document.last_error_message:
                        document = registry.update_document(
                            document,
                            last_error_code="pipeline_failed",
                            last_error_message=str(exc),
                        )
            response_documents.append(
                ingestion_document_summary(document, duplicate=item.duplicate, job_id=job.job_id if job else None)
            )
        return IngestionUploadResponse(batch_id=batch.batch_id, documents=response_documents)

    @app.post("/api/ingestion/uploads/raw", response_model=IngestionUploadResponse)
    async def ingestion_upload_raw(request: Request) -> IngestionUploadResponse:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/pdf":
            raise HTTPException(status_code=415, detail=error_payload("unsupported_media_type", "send application/pdf"))
        filename = request.headers.get("x-filename") or "uploaded.pdf"
        content = await request.body()
        registry = get_ingestion_registry()
        try:
            registered = [registry.register_pdf_bytes(filename, content, uploaded_by="api")]
        except Exception as exc:
            raise HTTPException(status_code=422, detail=error_payload("invalid_pdf_upload", str(exc))) from exc
        batch = registry.create_batch(registered, uploaded_by="api")
        documents = []
        for item in registered:
            document = registry.get_document(item.document.document_id) or item.document
            job = None
            if not item.duplicate:
                job = registry.create_job(document, metadata={"queued_by": "raw_upload_api", "duplicate": item.duplicate})
            documents.append(
                ingestion_document_summary(document, duplicate=item.duplicate, job_id=job.job_id if job else None)
            )
        return IngestionUploadResponse(batch_id=batch.batch_id, documents=documents)

    @app.get("/api/ingestion/batches/{batch_id}", response_model=IngestionBatchDetail)
    def ingestion_batch(batch_id: str) -> IngestionBatchDetail:
        registry = get_ingestion_registry()
        batch = registry.load_batch(batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail=error_payload("batch_not_found", batch_id))
        documents = registry.load_documents()
        return IngestionBatchDetail(
            batch_id=batch.batch_id,
            created_at=batch.created_at,
            uploaded_by=batch.uploaded_by,
            documents=[
                ingestion_document_summary(documents[document_id])
                for document_id in batch.document_ids
                if document_id in documents
            ],
        )

    @app.get("/api/ingestion/documents/{document_id}", response_model=IngestionDocumentDetail)
    def ingestion_document(document_id: str) -> IngestionDocumentDetail:
        registry = get_ingestion_registry()
        document = registry.get_document(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail=error_payload("document_not_found", document_id))
        jobs = sorted(registry.list_jobs_for_document(document_id), key=lambda item: item.created_at)
        return IngestionDocumentDetail(
            document=document.model_dump(mode="json"),
            jobs=[ingestion_job_summary(job) for job in jobs],
        )

    @app.post("/api/evidence/{document_id}/{evidence_id}/curate", response_model=EvidenceCurationResponse)
    def curate_evidence(
        document_id: str,
        evidence_id: str,
        payload: EvidenceCurationRequest,
    ) -> EvidenceCurationResponse:
        evidence_dir = EVIDENCE_DIR / Path(document_id).name
        if not evidence_dir.is_dir():
            raise HTTPException(status_code=404, detail=error_payload("evidence_dir_not_found", document_id))
        try:
            decision = append_curation_decision(
                evidence_dir=evidence_dir,
                evidence_id=evidence_id,
                action=payload.action,
                reviewer=payload.reviewer,
                reason=payload.reason,
                edited_record=payload.edited_record,
                allow_severe=payload.allow_severe,
            )
            curated_records = len(rebuild_curated_evidence(evidence_dir))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=error_payload("invalid_curation_decision", str(exc))) from exc
        return EvidenceCurationResponse(decision=decision, curated_records=curated_records)

    @app.post("/api/ingestion/documents/{document_id}/retry", response_model=IngestionDocumentDetail)
    def ingestion_retry(document_id: str) -> IngestionDocumentDetail:
        registry = get_ingestion_registry()
        document = registry.get_document(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail=error_payload("document_not_found", document_id))
        job = registry.create_job(document, metadata={"queued_by": "retry_api"})
        try:
            run_ingestion_pipeline(get_runtime(app), registry, document_id, job=job)
        except Exception:
            logger.exception("ingestion retry failed for %s", document_id)
        document = registry.get_document(document_id) or document
        jobs = sorted(registry.list_jobs_for_document(document_id), key=lambda item: item.created_at)
        return IngestionDocumentDetail(
            document=document.model_dump(mode="json"),
            jobs=[ingestion_job_summary(item) for item in jobs],
        )

    @app.post("/api/ingestion/documents/{document_id}/reindex", response_model=IngestionDocumentDetail)
    def ingestion_reindex(document_id: str) -> IngestionDocumentDetail:
        registry = get_ingestion_registry()
        document = registry.get_document(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail=error_payload("document_not_found", document_id))
        job = registry.create_job(document, metadata={"queued_by": "reindex_api"})
        try:
            run_ingestion_pipeline(get_runtime(app), registry, document_id, job=job, reindex_only=True)
        except Exception:
            logger.exception("ingestion reindex failed for %s", document_id)
        document = registry.get_document(document_id) or document
        jobs = sorted(registry.list_jobs_for_document(document_id), key=lambda item: item.created_at)
        return IngestionDocumentDetail(
            document=document.model_dump(mode="json"),
            jobs=[ingestion_job_summary(item) for item in jobs],
        )

    @app.get("/api/pdfs/{pdf_name}")
    def get_pdf(pdf_name: str) -> FileResponse:
        path = resolve_pdf_file(pdf_name)
        if path is None:
            raise HTTPException(status_code=404, detail=error_payload("pdf_not_found", pdf_name))
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=path.name,
            content_disposition_type="inline",
        )


def get_runtime(app: FastAPI) -> RuntimeServices:
    runtime = getattr(app.state, "runtime", None)
    if not isinstance(runtime, RuntimeServices):
        raise HTTPException(status_code=500, detail=error_payload("runtime_error", "runtime is not initialized"))
    return runtime


def get_ingestion_registry() -> IngestionRegistry:
    return IngestionRegistry(ARTIFACT_ROOT)


def run_ingestion_pipeline(
    runtime: RuntimeServices,
    registry: IngestionRegistry,
    document_id: str,
    job: Optional[IngestionJob] = None,
    reindex_only: bool = False,
) -> IngestionRunResult:
    pipeline = IngestionPipeline(
        runtime=runtime,
        registry=registry,
        options=IngestionPipelineOptions(
            artifact_root=ARTIFACT_ROOT,
            reindex_only=reindex_only,
            delete_existing_points=reindex_only,
        ),
    )
    return pipeline.run_document(document_id, job=job, reindex_only=reindex_only)


def build_ingestion_summary(registry: IngestionRegistry) -> IngestionSummaryResponse:
    documents = registry.load_documents()
    jobs = registry.load_jobs()
    status_counts = Counter(document.current_status for document in documents.values())
    job_status_counts = Counter(job.status for job in jobs.values())
    failed_documents = sum(count for status, count in status_counts.items() if status.startswith("failed_"))
    return IngestionSummaryResponse(
        total_documents=len(documents),
        queued_jobs=job_status_counts.get("queued", 0),
        running_jobs=job_status_counts.get("running", 0),
        failed_documents=failed_documents,
        searchable_documents=status_counts.get("searchable", 0),
        needs_review_documents=status_counts.get("needs_review", 0),
        status_counts=dict(status_counts),
    )


def ingestion_document_summary(
    document: IngestionDocument,
    duplicate: bool = False,
    job_id: Optional[str] = None,
) -> IngestionDocumentSummary:
    return IngestionDocumentSummary(
        document_id=document.document_id,
        source_pdf=document.source_pdf,
        sha256=document.sha256,
        page_count=document.page_count,
        status=document.current_status,
        duplicate=duplicate,
        job_id=job_id,
        collection=document.active_collection,
        updated_at=document.updated_at,
        last_error_code=document.last_error_code,
        last_error_message=document.last_error_message,
    )


def ingestion_job_summary(job: IngestionJob) -> IngestionJobSummary:
    return IngestionJobSummary(
        job_id=job.job_id,
        document_id=job.document_id,
        stage=job.stage,
        status=job.status,
        attempt=job.attempt,
        created_at=job.created_at,
        updated_at=job.updated_at,
        error_code=job.error_code,
        error_message=job.error_message,
    )


def make_enzyme_recommendation_request(payload: RecommendByEnzymeApiRequest) -> EnzymeRecommendationRequest:
    return EnzymeRecommendationRequest(
        enzyme_name=payload.enzyme_name,
        objective=payload.objective,
        application_context=payload.application_context,
        constraints=payload.constraints,
        top_k=payload.top_k,
    )


def make_formulation_optimization_request(payload: OptimizeFormulationApiRequest) -> FormulationOptimizationRequest:
    return FormulationOptimizationRequest(
        enzyme_name=payload.enzyme_name,
        user_formulation=payload.user_formulation,
        objective=payload.objective,
        application_context=payload.application_context,
        constraints=payload.constraints,
        top_k=payload.top_k,
    )


def recommend_by_enzyme_response(runtime: RuntimeServices, payload: RecommendByEnzymeApiRequest):
    runtime = runtime_with_collection(runtime, payload.collection)
    service = RecommendationService(runtime)
    request = make_enzyme_recommendation_request(payload)
    retrieval = service.retrieve_evidence(request)
    retrieval.hits = enrich_retrieval_hits(runtime, retrieval.hits)
    generation = (
        deterministic_no_answer_generation(retrieval)
        if retrieval_guard_reason(retrieval)
        else service.runtime.generator().generate(service.build_generation_request(request, retrieval))
    )
    response = service.build_response(request, retrieval, generation)
    return response


def optimize_formulation_response(runtime: RuntimeServices, payload: OptimizeFormulationApiRequest):
    runtime = runtime_with_collection(runtime, payload.collection)
    service = FormulationOptimizationService(runtime)
    request = make_formulation_optimization_request(payload)
    retrieval = service.retrieve_evidence(request)
    retrieval.hits = enrich_retrieval_hits(runtime, retrieval.hits)
    generation = service.runtime.generator().generate(service.build_generation_request(request, retrieval))
    response = service.build_response(request, retrieval, generation)
    return response


def runtime_with_collection(runtime: RuntimeServices, collection: Optional[str]) -> RuntimeServices:
    if not collection:
        return runtime
    cloned_config = deepcopy(runtime.config)
    cloned_config.vector_store.collection = resolve_collection_name(
        runtime.embedding_model(),
        collection=collection,
    )
    return RuntimeServices(config=cloned_config)


def validate_point_type(value: Optional[str]) -> Optional[PointType]:
    if value is None:
        return None
    if value not in {"rag_chunk", "table_record", "evidence_record"}:
        raise HTTPException(status_code=422, detail=error_payload("invalid_point_type", value))
    return value  # type: ignore[return-value]


def get_cached_dashboard_summary(app: FastAPI, runtime: RuntimeServices) -> DashboardSummaryResponse:
    cache = getattr(app.state, "dashboard_summary_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        app.state.dashboard_summary_cache = cache
    lock = getattr(app.state, "dashboard_summary_cache_lock", None)
    if not hasattr(lock, "acquire") or not hasattr(lock, "release"):
        lock = threading.Lock()
        app.state.dashboard_summary_cache_lock = lock

    collection = runtime.qdrant_config().collection
    now = time.monotonic()
    cached = get_dashboard_summary_cache_entry(cache, collection, now)
    if cached is not None:
        return cached

    with lock:
        now = time.monotonic()
        cached = get_dashboard_summary_cache_entry(cache, collection, now)
        if cached is not None:
            return cached
        response = build_dashboard_summary(runtime)
        cache[collection] = (now, response)
        return response


def get_dashboard_summary_cache_entry(
    cache: dict[str, tuple[float, DashboardSummaryResponse]],
    collection: str,
    now: float,
) -> Optional[DashboardSummaryResponse]:
    cached = cache.get(collection)
    if not isinstance(cached, tuple) or len(cached) != 2:
        return None
    cached_at, response = cached
    if not isinstance(cached_at, (int, float)) or now - cached_at > DASHBOARD_SUMMARY_CACHE_TTL_SECONDS:
        return None
    if not isinstance(response, DashboardSummaryResponse):
        return None
    return response


def build_dashboard_summary(runtime: RuntimeServices) -> DashboardSummaryResponse:
    artifact_stats = collect_artifact_stats()
    source_pdf_stats = collect_source_pdf_stats()
    source_pdf_count = source_pdf_stats["source_pdf_count"]
    qdrant_stats = collect_qdrant_dashboard_stats(runtime)
    collection = runtime.qdrant_config().collection
    indexed_docs = int_or_zero(qdrant_stats.get("indexed_docs")) if qdrant_stats else 0
    indexed_pages = int_or_zero(qdrant_stats.get("indexed_pages")) if qdrant_stats else 0
    parser_docs = source_pdf_count or artifact_stats["processed_docs"] or indexed_docs
    parser_pages = source_pdf_stats["source_pdf_pages"]
    if not parser_pages and artifact_stats["processed_docs"] >= parser_docs:
        parser_pages = artifact_stats["processed_pages"]
    if not parser_pages:
        parser_pages = indexed_pages or artifact_stats["processed_pages"]

    if qdrant_stats:
        return DashboardSummaryResponse(
            source_pdf_count=source_pdf_count,
            processed_docs=parser_docs,
            processed_pages=parser_pages,
            indexed_docs=indexed_docs,
            indexed_pages=indexed_pages,
            rag_chunks=qdrant_stats["rag_chunks"] or artifact_stats["rag_chunks"],
            table_records=qdrant_stats["table_records"] or artifact_stats["table_records"],
            evidence_records=qdrant_stats["evidence_records"] or artifact_stats["evidence_records"],
            curated_evidence_records=qdrant_stats["curated_evidence_records"]
            or artifact_stats["curated_evidence_records"],
            review_items=qdrant_stats["review_items"] or artifact_stats["review_items"],
            qdrant_points=qdrant_stats["qdrant_points"],
            qdrant_status=qdrant_stats["qdrant_status"],
            stats_source="qdrant+pdf_inventory" if source_pdf_count else "qdrant",
            collection=collection,
        )

    return DashboardSummaryResponse(
        source_pdf_count=source_pdf_count,
        processed_docs=parser_docs,
        processed_pages=parser_pages,
        indexed_docs=0,
        indexed_pages=0,
        rag_chunks=artifact_stats["rag_chunks"],
        table_records=artifact_stats["table_records"],
        evidence_records=artifact_stats["evidence_records"],
        curated_evidence_records=artifact_stats["curated_evidence_records"],
        review_items=artifact_stats["review_items"],
        qdrant_points=None,
        qdrant_status=None,
        stats_source="artifacts",
        collection=collection,
    )


def count_source_pdfs(pdf_dir: Path = PDF_DIR) -> int:
    return collect_source_pdf_stats(pdf_dir)["source_pdf_count"]


def collect_source_pdf_stats(pdf_dir: Path = PDF_DIR) -> dict[str, int]:
    stats = {
        "source_pdf_count": 0,
        "source_pdf_pages": 0,
        "source_pdf_page_failures": 0,
    }
    if not pdf_dir.is_dir():
        return stats
    for path in sorted(pdf_dir.glob("*.pdf")):
        if not path.is_file():
            continue
        stats["source_pdf_count"] += 1
        page_count = count_pdf_pages(path)
        if page_count is None:
            stats["source_pdf_page_failures"] += 1
            continue
        stats["source_pdf_pages"] += page_count
    return stats


def count_pdf_pages(path: Path) -> Optional[int]:
    try:
        return len(PdfReader(str(path)).pages)
    except Exception as exc:
        logger.warning("failed to count PDF pages for %s: %s", path, exc)
        return None


def collect_artifact_stats(
    rag_input_dir: Path = RAG_INPUT_DIR,
    evidence_dir: Path = EVIDENCE_DIR,
) -> dict[str, int]:
    stats = {
        "processed_docs": 0,
            "processed_pages": 0,
            "rag_chunks": 0,
            "table_records": 0,
            "evidence_records": 0,
            "curated_evidence_records": 0,
            "review_items": 0,
        }
    if rag_input_dir.is_dir():
        for manifest_path in sorted(rag_input_dir.glob("*/document_manifest.json")):
            try:
                with manifest_path.open("r", encoding="utf-8") as handle:
                    manifest = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(manifest, dict):
                continue
            counts = manifest.get("counts")
            if not isinstance(counts, dict):
                continue
            stats["processed_docs"] += 1
            stats["processed_pages"] += int_or_zero(counts.get("pages"))
            stats["rag_chunks"] += int_or_zero(counts.get("rag_chunks"))
            stats["table_records"] += int_or_zero(counts.get("table_records"))

        if evidence_dir.is_dir():
            for evidence_path in sorted(evidence_dir.glob("*/evidence_records.jsonl")):
                stats["evidence_records"] += count_jsonl_rows(evidence_path)
            for curated_path in sorted(evidence_dir.glob("*/curated_evidence_records.jsonl")):
                stats["curated_evidence_records"] += count_jsonl_rows(curated_path)
            for review_path in sorted(evidence_dir.glob("*/review_queue.jsonl")):
                stats["review_items"] += count_jsonl_rows(review_path)
    return stats


def collect_qdrant_dashboard_stats(runtime: RuntimeServices) -> Optional[dict[str, Any]]:
    try:
        with QdrantRestClient(runtime.qdrant_config()) as client:
            collection_info = client.get_collection_info()
            if collection_info is None:
                return None
            payloads = client.scroll_all_payloads(
                limit=QDRANT_SCROLL_BATCH_SIZE,
                with_payload=[
                    "document_id",
                    "source_pdf",
                    "page_start",
                    "page_end",
                    "page_idx",
                    "point_type",
                    "candidate_source",
                    "requires_review",
                ],
            )
    except RuntimeError:
        return None

    return summarize_qdrant_payloads(payloads, collection_info)


def summarize_qdrant_payloads(
    payloads: list[dict[str, Any]],
    collection_info: dict[str, Any],
) -> dict[str, Any]:
    document_max_pages: dict[str, int] = {}
    point_type_counts = {
        "rag_chunks": 0,
        "table_records": 0,
        "evidence_records": 0,
        "curated_evidence_records": 0,
        "review_items": 0,
    }

    for payload in payloads:
        point_type = str(payload.get("point_type") or "")
        if point_type == "rag_chunk":
            point_type_counts["rag_chunks"] += 1
        elif point_type == "table_record":
            point_type_counts["table_records"] += 1
        elif point_type == "evidence_record":
            point_type_counts["evidence_records"] += 1
            if payload.get("candidate_source") == "curated_evidence":
                point_type_counts["curated_evidence_records"] += 1
        if bool(payload.get("requires_review")):
            point_type_counts["review_items"] += 1

        document_id = payload.get("document_id") or Path(str(payload.get("source_pdf") or "")).stem
        if not document_id:
            continue
        max_page_index = max_page_index_from_payload(payload)
        if max_page_index is None:
            document_max_pages.setdefault(str(document_id), 0)
            continue
        document_max_pages[str(document_id)] = max(document_max_pages.get(str(document_id), 0), max_page_index + 1)

    return {
        "processed_docs": len(document_max_pages),
        "processed_pages": sum(document_max_pages.values()),
        "indexed_docs": len(document_max_pages),
        "indexed_pages": sum(document_max_pages.values()),
        "rag_chunks": point_type_counts["rag_chunks"],
        "table_records": point_type_counts["table_records"],
        "evidence_records": point_type_counts["evidence_records"],
        "curated_evidence_records": point_type_counts["curated_evidence_records"],
        "review_items": point_type_counts["review_items"],
        "qdrant_points": int_or_none(collection_info.get("points_count")),
        "qdrant_status": str(collection_info.get("status") or "") or None,
    }


def max_page_index_from_payload(payload: dict[str, Any]) -> Optional[int]:
    page_values = [payload.get("page_start"), payload.get("page_end"), payload.get("page_idx")]
    normalized = [value for value in (int_or_none(value) for value in page_values) if value is not None]
    return max(normalized) if normalized else None


def count_jsonl_rows(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def int_or_zero(value: Any) -> int:
    number = int_or_none(value)
    return number if number is not None else 0


def int_or_none(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def enrich_retrieval_response(runtime: RuntimeServices, response: RetrievalResponse) -> RetrievalResponse:
    response.hits = enrich_retrieval_hits(runtime, response.hits)
    return response


def enrich_retrieval_hits(runtime: RuntimeServices, hits: list[RetrievalHit]) -> list[RetrievalHit]:
    reference_cache: dict[str, dict[str, dict[str, Any]]] = {}
    qdrant_reference_cache: dict[tuple[str, str], str] = {}
    for hit in hits:
        if hit.source_chunk_text:
            continue
        source_id = hit.parent_source_id or hit.source_id
        document_id = hit.document_id
        if not source_id or not document_id:
            continue
        if document_id not in reference_cache:
            reference_cache[document_id] = load_reference_texts(document_id)
        reference_text = build_local_reference_context(reference_cache[document_id], source_id)
        if not reference_text:
            cache_key = (document_id, source_id)
            if cache_key not in qdrant_reference_cache:
                qdrant_reference_cache[cache_key] = load_qdrant_reference_context(runtime, hit, source_id)
            reference_text = qdrant_reference_cache[cache_key]
        if reference_text:
            hit.source_chunk_text = reference_text
    return hits


def load_reference_texts(document_id: str) -> dict[str, dict[str, Any]]:
    document_dir = RAG_INPUT_DIR / Path(document_id).name
    references: dict[str, dict[str, Any]] = {}
    load_reference_jsonl(document_dir / "rag_chunks.jsonl", id_field="chunk_id", text_field="text", output=references)
    load_reference_jsonl(document_dir / "table_records.jsonl", id_field="table_id", text_field="text", output=references)
    return references


def load_reference_jsonl(path: Path, id_field: str, text_field: str, output: dict[str, dict[str, Any]]) -> None:
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            source_id = row.get(id_field)
            text = row.get(text_field)
            if isinstance(source_id, str) and isinstance(text, str):
                output[source_id] = row


def build_local_reference_context(references: dict[str, dict[str, Any]], source_id: str) -> str:
    row = references.get(source_id)
    if not row:
        return ""
    if row.get("chunk_type") != "text":
        return str(row.get("text") or "")

    rows = [item for item in neighboring_chunk_rows(references, source_id)]
    if not rows:
        rows = [row]
    return join_reference_rows(rows)


def load_qdrant_reference_context(runtime: RuntimeServices, hit: RetrievalHit, source_id: str) -> str:
    payloads = qdrant_reference_payloads(runtime, hit, source_id)
    if not payloads:
        return ""
    return join_reference_rows(payloads)


def qdrant_reference_payloads(runtime: RuntimeServices, hit: RetrievalHit, source_id: str) -> list[dict[str, Any]]:
    if not hit.document_id:
        return []
    rows: list[dict[str, Any]] = []
    try:
        with QdrantRestClient(runtime.qdrant_config()) as client:
            for candidate_id in neighboring_source_ids(source_id):
                rows.extend(
                    client.scroll_payloads(
                        {
                            "must": [
                                {"key": "document_id", "match": {"value": hit.document_id}},
                                {"key": "source_id", "match": {"value": candidate_id}},
                            ]
                        },
                        limit=1,
                    )
                )
    except RuntimeError:
        return []
    return sorted(
        dedupe_reference_rows(rows),
        key=lambda row: (row.get("page_start") is None, row.get("page_start") or 0, str(row.get("source_id") or "")),
    )


def neighboring_chunk_rows(references: dict[str, dict[str, Any]], source_id: str) -> Iterator[dict[str, Any]]:
    for candidate_id in neighboring_source_ids(source_id):
        row = references.get(candidate_id)
        if row:
            yield row


def neighboring_source_ids(source_id: str) -> list[str]:
    prefix, index = split_chunk_id(source_id)
    if prefix is None or index is None:
        return [source_id]
    return [f"{prefix}{candidate:04d}" for candidate in range(max(index - REFERENCE_NEIGHBOR_WINDOW, 0), index + REFERENCE_NEIGHBOR_WINDOW + 1)]


def split_chunk_id(source_id: str) -> tuple[str | None, int | None]:
    marker = "_chunk_"
    if marker not in source_id:
        return None, None
    prefix, raw_index = source_id.rsplit(marker, 1)
    if not raw_index.isdigit():
        return None, None
    return f"{prefix}{marker}", int(raw_index)


def join_reference_rows(rows: list[dict[str, Any]]) -> str:
    texts = []
    for row in dedupe_reference_rows(rows):
        text = str(row.get("text") or "").strip()
        if text:
            texts.append(text)
    return "\n\n".join(texts)


def dedupe_reference_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("source_id") or row.get("chunk_id") or row.get("table_id") or row.get("text") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(row)
    return deduped


def resolve_pdf_file(pdf_name: str) -> Optional[Path]:
    raw_requested = pdf_name.strip()
    if not raw_requested:
        return None
    if "/" in raw_requested or "\\" in raw_requested:
        return None
    requested = Path(raw_requested).name.strip()
    if not requested.lower().endswith(".pdf"):
        requested = f"{requested}.pdf"

    exact = PDF_DIR / requested
    if exact.is_file():
        return exact
    uploaded = resolve_uploaded_pdf(requested)
    if uploaded is not None:
        return uploaded

    requested_stem = Path(requested).stem.strip()
    candidates = []
    if PDF_DIR.is_dir():
        for candidate in PDF_DIR.glob("*.pdf"):
            if candidate.name.strip() == requested or candidate.stem.strip() == requested_stem:
                candidates.append(candidate)
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: (len(path.name), path.name))[0]


def resolve_uploaded_pdf(requested: str) -> Optional[Path]:
    registry = get_ingestion_registry()
    requested_stem = Path(requested).stem.strip()
    for document in registry.load_documents().values():
        if document.source_pdf.strip() != requested and Path(document.source_pdf).stem.strip() != requested_stem:
            continue
        path = Path(document.raw_pdf_path)
        if path.is_file():
            return path
    return None


def stream_recommendation_events(
    service: RecommendationService,
    request: EnzymeRecommendationRequest,
) -> Iterator[str]:
    try:
        started_at = time.perf_counter()
        yield ndjson_event({"event": "status", "stage": "retrieval_start", "message": "retrieving evidence"})
        retrieval = service.retrieve_evidence(request)
        retrieval_ms = elapsed_ms(started_at)
        yield ndjson_event(
            {
                "event": "retrieval",
                "stage": "retrieval_done",
                "hits_count": len(retrieval.hits),
                "collection": retrieval.collection,
                "embedding_model": retrieval.embedding_model,
                "elapsed_ms": retrieval_ms,
            }
        )
        yield ndjson_event(
            {
                "event": "preview",
                "stage": "evidence_preview",
                "delta": build_evidence_preview(retrieval, title="证据预览"),
                "elapsed_ms": elapsed_ms(started_at),
            }
        )
        if retrieval_guard_reason(retrieval):
            retrieval.hits = enrich_retrieval_hits(service.runtime, retrieval.hits)
            generation = deterministic_no_answer_generation(retrieval)
            response = service.build_response(request, retrieval, generation)
            yield ndjson_event(
                {
                    "event": "status",
                    "stage": "generation_skipped",
                    "message": "retrieval guard returned deterministic no-answer",
                    "elapsed_ms": elapsed_ms(started_at),
                }
            )
            yield ndjson_event({"event": "delta", "delta": generation.content})
            yield ndjson_event(
                {
                    "event": "final",
                    "elapsed_ms": elapsed_ms(started_at),
                    "data": response.model_dump(mode="json"),
                }
            )
            return
        yield ndjson_event({"event": "status", "stage": "generation_start", "message": "generating recommendation"})
        generation_request = service.build_stream_generation_request(request, retrieval)
        generator = service.runtime.generator()
        content = ""
        finish_reason = None
        usage: dict[str, Any] = {}
        first_delta_ms: Optional[float] = None
        reasoning_seen = False
        stream_method = getattr(generator, "stream_generate", None)
        if callable(stream_method):
            for chunk in stream_method(generation_request):
                if chunk.reasoning_delta and not reasoning_seen:
                    reasoning_seen = True
                    yield ndjson_event(
                        {
                            "event": "status",
                            "stage": "model_reasoning",
                            "message": "model reasoning started",
                            "elapsed_ms": elapsed_ms(started_at),
                        }
                    )
                if chunk.delta:
                    if first_delta_ms is None:
                        first_delta_ms = elapsed_ms(started_at)
                        yield ndjson_event(
                            {
                                "event": "status",
                                "stage": "first_delta",
                                "message": "first visible token received",
                                "elapsed_ms": first_delta_ms,
                            }
                        )
                    content += chunk.delta
                    yield ndjson_event({"event": "delta", "delta": chunk.delta})
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
                if chunk.usage:
                    usage.update(chunk.usage)
        else:
            response = generator.generate(generation_request)
            content = response.content
            finish_reason = response.finish_reason
            usage = dict(response.usage)
            first_delta_ms = elapsed_ms(started_at)
            yield ndjson_event(
                {
                    "event": "status",
                    "stage": "first_delta",
                    "message": "first visible token received",
                    "elapsed_ms": first_delta_ms,
                }
            )
            for delta in chunk_text(content):
                yield ndjson_event({"event": "delta", "delta": delta})

        generation = GenerationResponse(
            provider=getattr(generator, "provider", "unknown"),
            model=generation_request.model,
            content=content,
            finish_reason=finish_reason,
            usage=usage,
        )
        retrieval.hits = enrich_retrieval_hits(service.runtime, retrieval.hits)
        response = service.build_response(request, retrieval, generation)
        yield ndjson_event(
            {
                "event": "final",
                "elapsed_ms": elapsed_ms(started_at),
                "data": response.model_dump(mode="json"),
            }
        )
    except Exception as exc:
        yield ndjson_event({"event": "error", "message": str(exc)})


def stream_optimization_events(
    service: FormulationOptimizationService,
    request: FormulationOptimizationRequest,
) -> Iterator[str]:
    try:
        started_at = time.perf_counter()
        yield ndjson_event({"event": "status", "stage": "retrieval_start", "message": "retrieving evidence"})
        retrieval = service.retrieve_evidence(request)
        retrieval_ms = elapsed_ms(started_at)
        yield ndjson_event(
            {
                "event": "retrieval",
                "stage": "retrieval_done",
                "hits_count": len(retrieval.hits),
                "collection": retrieval.collection,
                "embedding_model": retrieval.embedding_model,
                "elapsed_ms": retrieval_ms,
            }
        )
        yield ndjson_event(
            {
                "event": "preview",
                "stage": "evidence_preview",
                "delta": build_evidence_preview(retrieval, title="配方证据预览"),
                "elapsed_ms": elapsed_ms(started_at),
            }
        )
        yield ndjson_event({"event": "status", "stage": "generation_start", "message": "generating optimization"})
        generation_request = service.build_stream_generation_request(request, retrieval)
        generator = service.runtime.generator()
        content = ""
        finish_reason = None
        usage: dict[str, Any] = {}
        first_delta_ms: Optional[float] = None
        reasoning_seen = False
        stream_method = getattr(generator, "stream_generate", None)
        if callable(stream_method):
            for chunk in stream_method(generation_request):
                if chunk.reasoning_delta and not reasoning_seen:
                    reasoning_seen = True
                    yield ndjson_event(
                        {
                            "event": "status",
                            "stage": "model_reasoning",
                            "message": "model reasoning started",
                            "elapsed_ms": elapsed_ms(started_at),
                        }
                    )
                if chunk.delta:
                    if first_delta_ms is None:
                        first_delta_ms = elapsed_ms(started_at)
                        yield ndjson_event(
                            {
                                "event": "status",
                                "stage": "first_delta",
                                "message": "first visible token received",
                                "elapsed_ms": first_delta_ms,
                            }
                        )
                    content += chunk.delta
                    yield ndjson_event({"event": "delta", "delta": chunk.delta})
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
                if chunk.usage:
                    usage.update(chunk.usage)
        else:
            response = generator.generate(generation_request)
            content = response.content
            finish_reason = response.finish_reason
            usage = dict(response.usage)
            first_delta_ms = elapsed_ms(started_at)
            yield ndjson_event(
                {
                    "event": "status",
                    "stage": "first_delta",
                    "message": "first visible token received",
                    "elapsed_ms": first_delta_ms,
                }
            )
            for delta in chunk_text(content):
                yield ndjson_event({"event": "delta", "delta": delta})

        generation = GenerationResponse(
            provider=getattr(generator, "provider", "unknown"),
            model=generation_request.model,
            content=content,
            finish_reason=finish_reason,
            usage=usage,
        )
        retrieval.hits = enrich_retrieval_hits(service.runtime, retrieval.hits)
        response = service.build_response(request, retrieval, generation)
        yield ndjson_event(
            {
                "event": "final",
                "elapsed_ms": elapsed_ms(started_at),
                "data": response.model_dump(mode="json"),
            }
        )
    except Exception as exc:
        yield ndjson_event({"event": "error", "message": str(exc)})


def chunk_text(value: str, chunk_size: int = 120) -> Iterator[str]:
    for start in range(0, len(value), chunk_size):
        yield value[start : start + chunk_size]


def build_evidence_preview(retrieval: RetrievalResponse, title: str) -> str:
    if not retrieval.hits:
        return f"{title}：未检索到 usable evidence，模型将基于空证据边界说明不足。\n\n"
    lines = [f"{title}：已检索 {len(retrieval.hits)} 条 usable evidence，先给你可追溯预览："]
    for index, hit in enumerate(retrieval.hits[:3], start=1):
        citation = hit.citation or hit.source_id or f"hit {index}"
        record_type = hit.record_type or hit.point_type or "evidence"
        preview = compact_preview(hit.text, limit=96)
        lines.append(f"- [{index}] {citation} / {record_type}: {preview}")
    lines.append("\n模型建议生成中...\n\n")
    return "\n".join(lines)


def compact_preview(value: str, limit: int = 96) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return "无文本摘要"
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 1)


def ndjson_event(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def error_payload(code: str, message: Any) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


app = create_app()
