from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from enzyme_recommender.rag.qdrant import QdrantConfig, QdrantRestClient


DOCUMENT_ID_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]\d{1,3})(?:\s*\.?\s*pdf)?(?![A-Za-z0-9])", re.I)
EXPLICIT_DOCUMENT_HINT_RE = re.compile(
    r"\b(?:document_id|doc_id|doc|paper|source_pdf|pdf)\s*[:=]\s*([A-Z]\d{1,3})(?:\s*\.?\s*pdf)?\b",
    re.I,
)
DOCUMENT_CATALOG_PAYLOAD_FIELDS = [
    "document_id",
    "source_pdf",
    "source_id",
    "point_type",
    "page_start",
    "page_end",
    "section",
    "text",
    "qa_status",
    "qa_flags",
    "quality_flags",
    "requires_review",
]
TITLE_SECTION_TERMS = {"title", "abstract"}
TITLE_STOPWORDS = {
    "and",
    "article",
    "for",
    "from",
    "how",
    "immobilization",
    "immobilized",
    "in",
    "of",
    "on",
    "paper",
    "process",
    "study",
    "the",
    "this",
    "to",
    "what",
    "which",
    "with",
    "论文",
    "文章",
    "这篇",
    "优化",
    "过程",
    "怎么样",
}


class DocumentCatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    source_pdf: str
    title_candidate: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)
    indexed_points: int = 0
    qa_summary: dict[str, Any] = Field(default_factory=dict)


class DocumentResolveResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    document: Optional[DocumentCatalogItem] = None
    candidates: List[DocumentCatalogItem] = Field(default_factory=list)
    reason: str = ""
    explicit: bool = False


class _RetrievalDocumentState:
    def __init__(self, document: DocumentCatalogItem) -> None:
        self.document = document
        self.total_score = 0.0
        self.best_score = 0.0
        self.hit_count = 0
        self.rank_bonus = 0.0

    @property
    def score(self) -> float:
        count_bonus = min(0.8, 0.12 * self.hit_count)
        return self.total_score + self.best_score + self.rank_bonus + count_bonus


def build_document_catalog(
    qdrant_config: QdrantConfig,
    rag_input_dir: Optional[Path] = None,
    limit: int = 256,
) -> List[DocumentCatalogItem]:
    payloads = qdrant_document_payloads(qdrant_config, limit=limit)
    items = build_document_catalog_from_payloads(payloads)
    if rag_input_dir is not None:
        items = merge_local_document_metadata(items, rag_input_dir)
    return sorted(items, key=lambda item: natural_document_sort_key(item.document_id, item.source_pdf))


def qdrant_document_payloads(qdrant_config: QdrantConfig, limit: int = 256) -> List[dict[str, Any]]:
    try:
        with QdrantRestClient(qdrant_config) as client:
            return client.scroll_all_payloads(limit=limit, with_payload=DOCUMENT_CATALOG_PAYLOAD_FIELDS)
    except RuntimeError:
        return []


def build_document_catalog_from_payloads(payloads: Sequence[dict[str, Any]]) -> List[DocumentCatalogItem]:
    grouped: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        document_id = str(payload.get("document_id") or Path(str(payload.get("source_pdf") or "")).stem).strip()
        source_pdf = str(payload.get("source_pdf") or f"{document_id}.pdf").strip()
        if not document_id and not source_pdf:
            continue
        key = document_id or Path(source_pdf).stem
        state = grouped.setdefault(
            key,
            {
                "document_id": document_id or key,
                "source_pdf": source_pdf or f"{key}.pdf",
                "indexed_points": 0,
                "qa_status": Counter(),
                "qa_flags": Counter(),
                "quality_flags": Counter(),
                "requires_review": 0,
                "title_rows": [],
            },
        )
        state["indexed_points"] += 1
        if payload.get("source_pdf"):
            state["source_pdf"] = str(payload["source_pdf"])
        if payload.get("document_id"):
            state["document_id"] = str(payload["document_id"])
        qa_status = payload.get("qa_status")
        if qa_status:
            state["qa_status"][str(qa_status)] += 1
        if payload.get("requires_review"):
            state["requires_review"] += 1
        for flag in payload.get("qa_flags") or []:
            state["qa_flags"][str(flag)] += 1
        for flag in payload.get("quality_flags") or []:
            state["quality_flags"][str(flag)] += 1
        maybe_add_title_row(state["title_rows"], payload)

    return [catalog_item_from_state(state) for state in grouped.values()]


def maybe_add_title_row(rows: list[tuple[int, int, str]], payload: dict[str, Any]) -> None:
    text = compact_text(str(payload.get("text") or ""))
    if len(text) < 20:
        return
    page = int_or_large(payload.get("page_start"))
    section = str(payload.get("section") or "").lower()
    point_type = str(payload.get("point_type") or "")
    priority = 20
    if page == 0:
        priority -= 8
    if any(term in section for term in TITLE_SECTION_TERMS):
        priority -= 6
    if point_type == "rag_chunk":
        priority -= 2
    rows.append((priority, page, text[:260]))


def catalog_item_from_state(state: dict[str, Any]) -> DocumentCatalogItem:
    title_candidate = best_title_candidate(state.get("title_rows") or [])
    document_id = str(state["document_id"])
    source_pdf = str(state["source_pdf"])
    aliases = dedupe_strings(
        [
            document_id,
            source_pdf,
            Path(source_pdf).stem,
            title_candidate or "",
        ]
    )
    qa_summary = {
        "qa_status": dict(state["qa_status"]),
        "qa_flags": dict(state["qa_flags"]),
        "quality_flags": dict(state["quality_flags"]),
        "requires_review": int(state["requires_review"]),
    }
    return DocumentCatalogItem(
        document_id=document_id,
        source_pdf=source_pdf,
        title_candidate=title_candidate,
        aliases=aliases,
        indexed_points=int(state["indexed_points"]),
        qa_summary=qa_summary,
    )


def best_title_candidate(rows: Sequence[tuple[int, int, str]]) -> Optional[str]:
    if not rows:
        return None
    return sorted(rows, key=lambda item: (item[0], item[1], len(item[2])))[0][2]


def merge_local_document_metadata(items: Sequence[DocumentCatalogItem], rag_input_dir: Path) -> List[DocumentCatalogItem]:
    by_document_id = {item.document_id: item for item in items}
    for document_dir in sorted(rag_input_dir.glob("*")) if rag_input_dir.is_dir() else []:
        if not document_dir.is_dir():
            continue
        document_id = document_dir.name
        local_title = local_title_candidate(document_dir)
        if not local_title and document_id in by_document_id:
            continue
        existing = by_document_id.get(document_id)
        if existing is None:
            source_pdf = f"{document_id}.pdf"
            by_document_id[document_id] = DocumentCatalogItem(
                document_id=document_id,
                source_pdf=source_pdf,
                title_candidate=local_title,
                aliases=dedupe_strings([document_id, source_pdf, local_title or ""]),
                indexed_points=0,
                qa_summary={},
            )
            continue
        title = existing.title_candidate or local_title
        aliases = dedupe_strings([*existing.aliases, local_title or ""])
        by_document_id[document_id] = existing.model_copy(update={"title_candidate": title, "aliases": aliases})
    return list(by_document_id.values())


def local_title_candidate(document_dir: Path) -> Optional[str]:
    manifest_title = local_manifest_title(document_dir / "document_manifest.json")
    if manifest_title:
        return manifest_title
    chunks_path = document_dir / "rag_chunks.jsonl"
    if not chunks_path.is_file():
        return None
    candidates: list[tuple[int, int, str]] = []
    try:
        with chunks_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                maybe_add_title_row(candidates, row)
                if len(candidates) >= 12:
                    break
    except (OSError, json.JSONDecodeError):
        return None
    return best_title_candidate(candidates)


def local_manifest_title(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for key in ["title", "document_title", "pdf_title"]:
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, str) and value.strip():
            return compact_text(value)
    return None


def resolve_document_reference(query: str, catalog: Sequence[DocumentCatalogItem]) -> DocumentResolveResult:
    text = query or ""
    explicit_id = explicit_document_id(text)
    if explicit_id:
        document = find_document_by_id(explicit_id, catalog)
        if document is not None:
            return DocumentResolveResult(status="resolved", document=document, reason="explicit_document_id", explicit=True)
        source_pdf = f"{explicit_id.upper()}.pdf"
        return DocumentResolveResult(
            status="resolved",
            document=DocumentCatalogItem(
                document_id=explicit_id.upper(),
                source_pdf=source_pdf,
                aliases=[explicit_id.upper(), source_pdf],
                indexed_points=0,
                qa_summary={},
            ),
            reason="explicit_document_id_without_catalog",
            explicit=True,
        )

    scored = sorted(
        ((document_title_score(text, item), item) for item in catalog),
        key=lambda pair: pair[0],
        reverse=True,
    )
    scored = [(score, item) for score, item in scored if score > 0]
    if not scored:
        return DocumentResolveResult(status="unresolved", reason="no_document_reference")

    best_score, best_item = scored[0]
    close_candidates = [item for score, item in scored[:5] if best_score - score <= 0.08]
    if best_score < 0.42:
        return DocumentResolveResult(status="unresolved", candidates=[item for _, item in scored[:5]], reason="low_title_match")
    if len(close_candidates) > 1:
        return DocumentResolveResult(status="ambiguous", candidates=close_candidates, reason="ambiguous_title_match")
    return DocumentResolveResult(status="resolved", document=best_item, candidates=[best_item], reason="title_match")


def resolve_document_reference_from_hits(
    query: str,
    catalog: Sequence[DocumentCatalogItem],
    hits: Sequence[Any],
) -> DocumentResolveResult:
    """Resolve a document by aggregating broad retrieval hits.

    This is intentionally read-only and uses only existing hit metadata. It
    handles title-fragment questions when catalog title candidates are weak.
    """

    states: dict[str, _RetrievalDocumentState] = {}
    by_id = {normalize_document_id(item.document_id): item for item in catalog}
    by_source_pdf = {normalize_document_id(item.source_pdf): item for item in catalog}
    query_tokens = title_tokens(strip_explicit_document_terms(query))
    if not query_tokens:
        return DocumentResolveResult(status="unresolved", reason="no_resolver_query_tokens")

    for rank, hit in enumerate(hits, start=1):
        document_id = hit_field(hit, "document_id")
        source_pdf = hit_field(hit, "source_pdf")
        if not document_id and not source_pdf:
            continue
        key = normalize_document_id(document_id or source_pdf)
        document = by_id.get(key) or by_source_pdf.get(normalize_document_id(source_pdf or ""))
        if document is None:
            fallback_id = normalize_document_id(document_id or source_pdf)
            if not fallback_id:
                continue
            fallback_pdf = str(source_pdf or f"{fallback_id}.pdf")
            document = DocumentCatalogItem(
                document_id=str(document_id or Path(fallback_pdf).stem or fallback_id),
                source_pdf=fallback_pdf,
                aliases=dedupe_strings([str(document_id or ""), fallback_pdf, Path(fallback_pdf).stem]),
                indexed_points=0,
                qa_summary={},
            )
        state_key = normalize_document_id(document.document_id)
        state = states.setdefault(state_key, _RetrievalDocumentState(document))
        text_score = retrieval_hit_text_score(query_tokens, hit)
        if text_score <= 0:
            continue
        vector_score = safe_float(hit_field(hit, "rerank_score"), safe_float(hit_field(hit, "score"), 0.0))
        contribution = max(0.0, vector_score) * 0.45 + text_score * 1.6
        state.total_score += contribution
        state.best_score = max(state.best_score, contribution)
        state.rank_bonus += min(0.4, 0.7 / max(rank, 1))
        state.hit_count += 1

    ranked = sorted(states.values(), key=lambda state: state.score, reverse=True)
    ranked = [state for state in ranked if state.hit_count > 0 and state.score > 0]
    if not ranked:
        return DocumentResolveResult(status="unresolved", reason="no_retrieval_document_match")
    best = ranked[0]
    candidates = [state.document for state in ranked[:5]]
    if best.score < 1.25:
        return DocumentResolveResult(status="unresolved", candidates=candidates, reason="low_retrieval_document_match")
    if len(ranked) > 1:
        runner_up = ranked[1]
        margin = best.score - runner_up.score
        if margin <= max(0.45, best.score * 0.14):
            return DocumentResolveResult(status="ambiguous", candidates=candidates, reason="ambiguous_retrieval_document_match")
    return DocumentResolveResult(
        status="resolved",
        document=best.document,
        candidates=[best.document],
        reason="retrieval_document_match",
    )


def retrieval_hit_text_score(query_tokens: set[str], hit: Any) -> float:
    text = " ".join(
        [
            str(hit_field(hit, "section") or ""),
            str(hit_field(hit, "record_type") or ""),
            str(hit_field(hit, "text") or ""),
            str(hit_field(hit, "source_chunk_text") or ""),
            json.dumps(hit_field(hit, "extracted") or {}, ensure_ascii=False, sort_keys=True),
            json.dumps(hit_field(hit, "metrics") or [], ensure_ascii=False, sort_keys=True),
        ]
    )
    hit_tokens = title_tokens(text)
    if not hit_tokens:
        return 0.0
    overlap = len(query_tokens & hit_tokens)
    if not overlap:
        return 0.0
    query_ratio = overlap / len(query_tokens)
    hit_ratio = overlap / max(len(hit_tokens), 1)
    return 0.8 * query_ratio + 0.2 * min(1.0, hit_ratio * 4)


def hit_field(hit: Any, key: str) -> Any:
    if isinstance(hit, dict):
        payload = hit.get("payload") if isinstance(hit.get("payload"), dict) else hit
        return payload.get(key)
    return getattr(hit, key, None)


def safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def explicit_document_id(text: str) -> Optional[str]:
    hint = EXPLICIT_DOCUMENT_HINT_RE.search(text or "")
    if hint:
        return hint.group(1).upper()
    match = DOCUMENT_ID_RE.search(text or "")
    if match:
        return match.group(1).upper()
    return None


def find_document_by_id(document_id: str, catalog: Sequence[DocumentCatalogItem]) -> Optional[DocumentCatalogItem]:
    normalized = normalize_document_id(document_id)
    for item in catalog:
        aliases = [item.document_id, item.source_pdf, Path(item.source_pdf).stem, *item.aliases]
        if any(normalize_document_id(alias) == normalized for alias in aliases):
            return item
    return None


def document_title_score(query: str, item: DocumentCatalogItem) -> float:
    query_tokens = title_tokens(strip_explicit_document_terms(query))
    if not query_tokens:
        return 0.0
    best = 0.0
    for alias in item.aliases:
        alias_tokens = title_tokens(alias)
        if not alias_tokens:
            continue
        overlap = len(query_tokens & alias_tokens)
        if overlap == 0:
            continue
        query_ratio = overlap / len(query_tokens)
        alias_ratio = overlap / len(alias_tokens)
        substring_bonus = 0.12 if normalize_title_text(alias) in normalize_title_text(query) else 0.0
        best = max(best, 0.65 * query_ratio + 0.35 * alias_ratio + substring_bonus)
    return min(1.0, best)


def strip_explicit_document_terms(text: str) -> str:
    value = re.sub(r"\b[A-Z]\d{1,3}(?:\.pdf)?\b", " ", text or "", flags=re.I)
    value = re.sub(r"\b(?:paper|article|study)\b|论文|文章|这篇", " ", value, flags=re.I)
    return value


def title_tokens(text: str) -> set[str]:
    normalized = normalize_title_text(text)
    tokens = set(re.findall(r"[a-z0-9][a-z0-9\-]{1,}|[\u4e00-\u9fff]{2,}", normalized))
    return {token for token in tokens if token not in TITLE_STOPWORDS and len(token) >= 2}


def normalize_title_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def normalize_document_id(value: str) -> str:
    text = Path(str(value or "").strip()).stem.upper()
    return re.sub(r"[^A-Z0-9]", "", text)


def natural_document_sort_key(document_id: str, source_pdf: str) -> tuple[str, int, str]:
    match = re.match(r"([A-Z]+)(\d+)$", normalize_document_id(document_id))
    if match:
        return (match.group(1), int(match.group(2)), source_pdf)
    return (normalize_document_id(document_id), 0, source_pdf)


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def dedupe_strings(values: Iterable[str]) -> List[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = compact_text(value)
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def int_or_large(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 9999
