from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Set


DOCUMENT_STATUSES: Set[str] = {
    "uploaded",
    "deduplicated",
    "mineru_submitted",
    "mineru_succeeded",
    "rag_built",
    "evidence_extracted",
    "indexed",
    "retrieval_verified",
    "searchable",
    "needs_review",
    "failed_upload_validation",
    "failed_mineru",
    "failed_rag_build",
    "failed_evidence",
    "failed_indexing",
    "failed_retrieval_verification",
}

JOB_STAGES: Set[str] = {
    "upload_validation",
    "mineru_parse",
    "rag_build",
    "evidence_extract",
    "qdrant_index",
    "retrieval_verify",
    "complete",
}

TERMINAL_DOCUMENT_STATUSES: Set[str] = {"searchable", "needs_review"}
FAILED_DOCUMENT_STATUSES: Set[str] = {status for status in DOCUMENT_STATUSES if status.startswith("failed_")}

STAGE_SUCCESS_STATUS: Dict[str, str] = {
    "upload_validation": "deduplicated",
    "mineru_parse": "mineru_succeeded",
    "rag_build": "rag_built",
    "evidence_extract": "evidence_extracted",
    "qdrant_index": "indexed",
    "retrieval_verify": "retrieval_verified",
}

STAGE_FAILURE_STATUS: Dict[str, str] = {
    "upload_validation": "failed_upload_validation",
    "mineru_parse": "failed_mineru",
    "rag_build": "failed_rag_build",
    "evidence_extract": "failed_evidence",
    "qdrant_index": "failed_indexing",
    "retrieval_verify": "failed_retrieval_verification",
}

STAGE_ORDER = [
    "upload_validation",
    "mineru_parse",
    "rag_build",
    "evidence_extract",
    "qdrant_index",
    "retrieval_verify",
]

STATUS_TO_RESUME_STAGE: Dict[str, str] = {
    "uploaded": "upload_validation",
    "deduplicated": "mineru_parse",
    "mineru_submitted": "mineru_parse",
    "mineru_succeeded": "rag_build",
    "rag_built": "evidence_extract",
    "evidence_extracted": "qdrant_index",
    "indexed": "retrieval_verify",
    "retrieval_verified": "retrieval_verify",
    "failed_upload_validation": "upload_validation",
    "failed_mineru": "mineru_parse",
    "failed_rag_build": "rag_build",
    "failed_evidence": "evidence_extract",
    "failed_indexing": "qdrant_index",
    "failed_retrieval_verification": "retrieval_verify",
}

NORMAL_TRANSITIONS: Dict[str, Set[str]] = {
    "uploaded": {"deduplicated", "failed_upload_validation"},
    "deduplicated": {"mineru_submitted", "failed_mineru"},
    "mineru_submitted": {"mineru_succeeded", "failed_mineru"},
    "mineru_succeeded": {"rag_built", "failed_rag_build"},
    "rag_built": {"evidence_extracted", "failed_evidence"},
    "evidence_extracted": {"indexed", "failed_indexing"},
    "indexed": {"retrieval_verified", "searchable", "needs_review", "failed_retrieval_verification"},
    "retrieval_verified": {"searchable", "needs_review", "failed_retrieval_verification"},
}

RECOVERY_TRANSITIONS: Dict[str, Set[str]] = {
    "deduplicated": {
        "mineru_succeeded",
        "rag_built",
        "evidence_extracted",
        "indexed",
        "retrieval_verified",
        "searchable",
        "needs_review",
    },
    "mineru_submitted": {"mineru_succeeded"},
    "mineru_succeeded": {"rag_built", "evidence_extracted", "indexed"},
    "rag_built": {"evidence_extracted", "indexed"},
    "evidence_extracted": {"indexed"},
    "searchable": {"mineru_submitted", "rag_built", "evidence_extracted", "indexed", "retrieval_verified"},
    "needs_review": {"mineru_submitted", "rag_built", "evidence_extracted", "indexed", "retrieval_verified"},
    "failed_upload_validation": {"deduplicated", "mineru_submitted"},
    "failed_mineru": {
        "deduplicated",
        "mineru_submitted",
        "mineru_succeeded",
        "rag_built",
        "evidence_extracted",
        "indexed",
        "retrieval_verified",
        "searchable",
        "needs_review",
    },
    "failed_rag_build": {"mineru_submitted", "mineru_succeeded", "rag_built", "evidence_extracted", "indexed"},
    "failed_evidence": {"mineru_submitted", "mineru_succeeded", "rag_built", "evidence_extracted", "indexed"},
    "failed_indexing": {"mineru_submitted", "mineru_succeeded", "rag_built", "evidence_extracted", "indexed"},
    "failed_retrieval_verification": {
        "mineru_submitted",
        "rag_built",
        "evidence_extracted",
        "indexed",
        "retrieval_verified",
        "searchable",
        "needs_review",
    },
}


@dataclass(frozen=True)
class TransitionResult:
    allowed: bool
    reason: str = ""


def validate_transition(
    current_status: str,
    next_status: str,
    *,
    allow_recovery: bool = False,
) -> TransitionResult:
    if current_status not in DOCUMENT_STATUSES:
        return TransitionResult(False, f"unknown current status: {current_status}")
    if next_status not in DOCUMENT_STATUSES:
        return TransitionResult(False, f"unknown next status: {next_status}")
    if current_status == next_status:
        return TransitionResult(True)
    if next_status in NORMAL_TRANSITIONS.get(current_status, set()):
        return TransitionResult(True)
    if next_status in FAILED_DOCUMENT_STATUSES:
        return TransitionResult(True)
    if allow_recovery or current_status in FAILED_DOCUMENT_STATUSES:
        if next_status in RECOVERY_TRANSITIONS.get(current_status, set()):
            return TransitionResult(True)
    return TransitionResult(False, f"illegal document status transition: {current_status} -> {next_status}")


def assert_transition(
    current_status: str,
    next_status: str,
    *,
    allow_recovery: bool = False,
) -> None:
    result = validate_transition(current_status, next_status, allow_recovery=allow_recovery)
    if not result.allowed:
        raise ValueError(result.reason)


def failure_status_for_stage(stage: str) -> str:
    try:
        return STAGE_FAILURE_STATUS[stage]
    except KeyError as exc:
        raise ValueError(f"unknown ingestion stage: {stage}") from exc


def next_stage_after_status(status: str) -> Optional[str]:
    if status in TERMINAL_DOCUMENT_STATUSES:
        return None
    return STATUS_TO_RESUME_STAGE.get(status)


def stage_index(stage: str) -> int:
    try:
        return STAGE_ORDER.index(stage)
    except ValueError as exc:
        raise ValueError(f"unknown ingestion stage: {stage}") from exc


def stages_from(start_stage: str) -> Iterable[str]:
    start = stage_index(start_stage)
    return STAGE_ORDER[start:]
