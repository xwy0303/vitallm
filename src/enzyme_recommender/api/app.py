from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from enzyme_recommender.api.models import (
    HealthResponse,
    OptimizeFormulationApiRequest,
    RecommendByEnzymeApiRequest,
    SearchEvidenceApiRequest,
)
from enzyme_recommender.rag.retrieval import PointType
from enzyme_recommender.recommendation import (
    EnzymeRecommendationRequest,
    FormulationOptimizationRequest,
    FormulationOptimizationService,
    RecommendationService,
)
from enzyme_recommender.runtime import RuntimeServices
from enzyme_recommender.runtime.config import RuntimeConfigError


T = TypeVar("T")


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
        runtime = runtime_with_collection(get_runtime(app), payload.collection)
        service = RecommendationService(runtime)
        response = service.recommend_by_enzyme(
            EnzymeRecommendationRequest(
                enzyme_name=payload.enzyme_name,
                objective=payload.objective,
                application_context=payload.application_context,
                constraints=payload.constraints,
                top_k=payload.top_k,
            )
        )
        return response.model_dump(mode="json")

    @app.post("/api/optimize/formulation")
    def optimize_formulation(payload: OptimizeFormulationApiRequest) -> dict[str, Any]:
        runtime = runtime_with_collection(get_runtime(app), payload.collection)
        service = FormulationOptimizationService(runtime)
        response = service.optimize_formulation(
            FormulationOptimizationRequest(
                enzyme_name=payload.enzyme_name,
                user_formulation=payload.user_formulation,
                objective=payload.objective,
                application_context=payload.application_context,
                constraints=payload.constraints,
                top_k=payload.top_k,
            )
        )
        return response.model_dump(mode="json")

    @app.post("/api/search/evidence")
    def search_evidence(payload: SearchEvidenceApiRequest) -> dict[str, Any]:
        runtime = runtime_with_collection(get_runtime(app), payload.collection)
        response = runtime.retriever().retrieve(
            query=payload.query,
            top_k=payload.top_k or runtime.config.retrieval.top_k,
            point_type=validate_point_type(payload.point_type),
            usable_only=runtime.config.retrieval.usable_only if payload.usable_only is None else payload.usable_only,
        )
        return response.model_dump(mode="json")


def get_runtime(app: FastAPI) -> RuntimeServices:
    runtime = getattr(app.state, "runtime", None)
    if not isinstance(runtime, RuntimeServices):
        raise HTTPException(status_code=500, detail=error_payload("runtime_error", "runtime is not initialized"))
    return runtime


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


def error_payload(code: str, message: Any) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


app = create_app()
