from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, TypeVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import ValidationError

from enzyme_recommender.api.models import (
    HealthResponse,
    OptimizeFormulationApiRequest,
    RecommendByEnzymeApiRequest,
    SearchEvidenceApiRequest,
)
from enzyme_recommender.rag.retrieval import PointType
from enzyme_recommender.rag.retrieval import RetrievalHit, RetrievalResponse
from enzyme_recommender.recommendation import (
    EnzymeRecommendationRequest,
    FormulationOptimizationRequest,
    FormulationOptimizationService,
    RecommendationService,
)
from enzyme_recommender.generators import GenerationResponse
from enzyme_recommender.runtime import RuntimeServices
from enzyme_recommender.runtime.config import RuntimeConfigError


T = TypeVar("T")
PROJECT_DIR = Path(__file__).resolve().parents[3]
PDF_DIR = PROJECT_DIR / "MOF固定化脂肪酶文献调研"
RAG_INPUT_DIR = PROJECT_DIR / "artifacts" / "rag_inputs"


def create_app(config_path: Optional[str | Path] = None) -> FastAPI:
    runtime = RuntimeServices.from_config_file(resolve_config_path(config_path))
    app = FastAPI(
        title="生机大模型 API",
        version="0.1.0",
        description="Evidence-first enzyme immobilization recommendation API.",
    )
    app.state.runtime = runtime

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
        return enrich_retrieval_response(response).model_dump(mode="json")

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
    response = service.recommend_by_enzyme(make_enzyme_recommendation_request(payload))
    response.evidence_hits = enrich_retrieval_hits(response.evidence_hits)
    return response


def optimize_formulation_response(runtime: RuntimeServices, payload: OptimizeFormulationApiRequest):
    runtime = runtime_with_collection(runtime, payload.collection)
    service = FormulationOptimizationService(runtime)
    response = service.optimize_formulation(make_formulation_optimization_request(payload))
    response.evidence_hits = enrich_retrieval_hits(response.evidence_hits)
    return response


def runtime_with_collection(runtime: RuntimeServices, collection: Optional[str]) -> RuntimeServices:
    if not collection:
        return runtime
    cloned_config = deepcopy(runtime.config)
    cloned_config.vector_store.collection = collection
    return RuntimeServices(config=cloned_config)


def validate_point_type(value: Optional[str]) -> Optional[PointType]:
    if value is None:
        return None
    if value not in {"rag_chunk", "table_record", "evidence_record"}:
        raise HTTPException(status_code=422, detail=error_payload("invalid_point_type", value))
    return value  # type: ignore[return-value]


def enrich_retrieval_response(response: RetrievalResponse) -> RetrievalResponse:
    response.hits = enrich_retrieval_hits(response.hits)
    return response


def enrich_retrieval_hits(hits: list[RetrievalHit]) -> list[RetrievalHit]:
    reference_cache: dict[str, dict[str, str]] = {}
    for hit in hits:
        if hit.source_chunk_text:
            continue
        source_id = hit.parent_source_id or hit.source_id
        document_id = hit.document_id
        if not source_id or not document_id:
            continue
        if document_id not in reference_cache:
            reference_cache[document_id] = load_reference_texts(document_id)
        reference_text = reference_cache[document_id].get(source_id)
        if reference_text:
            hit.source_chunk_text = reference_text
    return hits


def load_reference_texts(document_id: str) -> dict[str, str]:
    document_dir = RAG_INPUT_DIR / Path(document_id).name
    references: dict[str, str] = {}
    load_reference_jsonl(document_dir / "rag_chunks.jsonl", id_field="chunk_id", text_field="text", output=references)
    load_reference_jsonl(document_dir / "table_records.jsonl", id_field="table_id", text_field="text", output=references)
    return references


def load_reference_jsonl(path: Path, id_field: str, text_field: str, output: dict[str, str]) -> None:
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
                output[source_id] = text


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

    requested_stem = Path(requested).stem.strip()
    candidates = []
    if PDF_DIR.is_dir():
        for candidate in PDF_DIR.glob("*.pdf"):
            if candidate.name.strip() == requested or candidate.stem.strip() == requested_stem:
                candidates.append(candidate)
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: (len(path.name), path.name))[0]


def stream_recommendation_events(
    service: RecommendationService,
    request: EnzymeRecommendationRequest,
) -> Iterator[str]:
    try:
        yield ndjson_event({"event": "status", "stage": "retrieval_start", "message": "retrieving evidence"})
        retrieval = service.retrieve_evidence(request)
        yield ndjson_event(
            {
                "event": "retrieval",
                "stage": "retrieval_done",
                "hits_count": len(retrieval.hits),
                "collection": retrieval.collection,
                "embedding_model": retrieval.embedding_model,
            }
        )
        yield ndjson_event({"event": "status", "stage": "generation_start", "message": "generating recommendation"})
        generation_request = service.build_generation_request(request, retrieval)
        generator = service.runtime.generator()
        content = ""
        finish_reason = None
        usage: dict[str, Any] = {}
        stream_method = getattr(generator, "stream_generate", None)
        if callable(stream_method):
            for chunk in stream_method(generation_request):
                if chunk.delta:
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
            for delta in chunk_text(content):
                yield ndjson_event({"event": "delta", "delta": delta})

        generation = GenerationResponse(
            provider=getattr(generator, "provider", "unknown"),
            model=generation_request.model,
            content=content,
            finish_reason=finish_reason,
            usage=usage,
        )
        response = service.build_response(request, retrieval, generation)
        response.evidence_hits = enrich_retrieval_hits(response.evidence_hits)
        yield ndjson_event(
            {
                "event": "final",
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
        yield ndjson_event({"event": "status", "stage": "retrieval_start", "message": "retrieving evidence"})
        retrieval = service.retrieve_evidence(request)
        yield ndjson_event(
            {
                "event": "retrieval",
                "stage": "retrieval_done",
                "hits_count": len(retrieval.hits),
                "collection": retrieval.collection,
                "embedding_model": retrieval.embedding_model,
            }
        )
        yield ndjson_event({"event": "status", "stage": "generation_start", "message": "generating optimization"})
        generation_request = service.build_generation_request(request, retrieval)
        generator = service.runtime.generator()
        content = ""
        finish_reason = None
        usage: dict[str, Any] = {}
        stream_method = getattr(generator, "stream_generate", None)
        if callable(stream_method):
            for chunk in stream_method(generation_request):
                if chunk.delta:
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
            for delta in chunk_text(content):
                yield ndjson_event({"event": "delta", "delta": delta})

        generation = GenerationResponse(
            provider=getattr(generator, "provider", "unknown"),
            model=generation_request.model,
            content=content,
            finish_reason=finish_reason,
            usage=usage,
        )
        response = service.build_response(request, retrieval, generation)
        response.evidence_hits = enrich_retrieval_hits(response.evidence_hits)
        yield ndjson_event(
            {
                "event": "final",
                "data": response.model_dump(mode="json"),
            }
        )
    except Exception as exc:
        yield ndjson_event({"event": "error", "message": str(exc)})


def chunk_text(value: str, chunk_size: int = 120) -> Iterator[str]:
    for start in range(0, len(value), chunk_size):
        yield value[start : start + chunk_size]


def ndjson_event(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def error_payload(code: str, message: Any) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


app = create_app()
