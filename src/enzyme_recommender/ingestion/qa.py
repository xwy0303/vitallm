from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


PLACEHOLDER_TEXT_RE = re.compile(r"\bUNRECOVERABLE PAGE PLACEHOLDER\b", re.I)
NUMERIC_RE = re.compile(r"\d+(?:\.\d+)?")
SEVERE_FLAGS = {
    "unrecoverable_page_placeholder",
    "table_parse_empty",
    "table_header_suspect",
    "table_too_sparse",
    "table_ragged_rows",
    "bad_table_structure",
    "rotated_or_wide_table_suspected",
}


@dataclass(frozen=True)
class MinerUQAGateConfig:
    placeholder_pages: frozenset[int] = frozenset()
    fallback_manifest_path: Optional[Path] = None
    min_table_rows: int = 1
    min_table_columns: int = 2
    sparse_table_min_fill_ratio: float = 0.35
    ragged_row_ratio: float = 0.45


@dataclass(frozen=True)
class QAGateSummary:
    status: str
    placeholder_pages: List[int] = field(default_factory=list)
    flag_counts: Dict[str, int] = field(default_factory=dict)
    flagged_chunks: int = 0
    flagged_tables: int = 0
    fallback_manifest_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "placeholder_pages": self.placeholder_pages,
            "flag_counts": self.flag_counts,
            "flagged_chunks": self.flagged_chunks,
            "flagged_tables": self.flagged_tables,
            "fallback_manifest_path": self.fallback_manifest_path,
        }


def build_qa_config(
    document_id: Optional[str],
    artifact_root: Path = Path("artifacts"),
    fallback_manifest_path: Optional[Path] = None,
    auto_resolve_fallback_manifest: bool = False,
) -> MinerUQAGateConfig:
    manifest_path = None
    if fallback_manifest_path is not None or auto_resolve_fallback_manifest:
        manifest_path = resolve_fallback_manifest(document_id, artifact_root, fallback_manifest_path)
    placeholder_pages: set[int] = set()
    if manifest_path is not None:
        manifest = load_json(manifest_path)
        placeholder_pages = {
            int(page) - 1
            for page in manifest.get("placeholder_pages", [])
            if isinstance(page, int) or str(page).isdigit()
        }
    return MinerUQAGateConfig(
        placeholder_pages=frozenset(placeholder_pages),
        fallback_manifest_path=manifest_path,
    )


def resolve_fallback_manifest(
    document_id: Optional[str],
    artifact_root: Path,
    fallback_manifest_path: Optional[Path],
) -> Optional[Path]:
    if fallback_manifest_path is not None:
        path = fallback_manifest_path.expanduser()
        return path if path.is_file() else None
    if not document_id:
        return None
    candidate = artifact_root / "pdf_raster_fallback" / Path(document_id).name / "fallback_manifest.json"
    return candidate if candidate.is_file() else None


def apply_qa_gate(
    rag_chunks: Sequence[Dict[str, Any]],
    table_records: Sequence[Dict[str, Any]],
    config: MinerUQAGateConfig,
) -> QAGateSummary:
    flag_counts: Dict[str, int] = {}
    flagged_chunks = 0
    flagged_tables = 0

    for chunk in rag_chunks:
        ensure_qa_defaults(chunk)
        flags = chunk_quality_flags(chunk, config)
        if flags:
            flagged_chunks += 1
            mark_for_review(chunk, flags)
            increment_counts(flag_counts, flags)

    for table in table_records:
        ensure_qa_defaults(table)
        flags = table_quality_flags(table, config)
        if flags:
            flagged_tables += 1
            mark_for_review(table, flags)
            increment_counts(flag_counts, flags)

    status = "pass"
    if flagged_chunks or flagged_tables:
        status = "warning"
    if SEVERE_FLAGS & set(flag_counts):
        status = "fail"
    return QAGateSummary(
        status=status,
        placeholder_pages=[page + 1 for page in sorted(config.placeholder_pages)],
        flag_counts=flag_counts,
        flagged_chunks=flagged_chunks,
        flagged_tables=flagged_tables,
        fallback_manifest_path=str(config.fallback_manifest_path) if config.fallback_manifest_path else None,
    )


def chunk_quality_flags(chunk: Dict[str, Any], config: MinerUQAGateConfig) -> List[str]:
    flags: List[str] = []
    text = str(chunk.get("text") or "")
    if page_range_overlaps_placeholders(chunk.get("page_start"), chunk.get("page_end"), config.placeholder_pages):
        flags.append("unrecoverable_page_placeholder")
    if PLACEHOLDER_TEXT_RE.search(text):
        flags.append("unrecoverable_page_placeholder")
    if chunk.get("chunk_type") == "table" and not text.strip():
        flags.append("empty_table_chunk")
    return sorted(set(flags))


def table_quality_flags(table: Dict[str, Any], config: MinerUQAGateConfig) -> List[str]:
    flags: List[str] = []
    page_idx = coerce_int(table.get("page_idx"))
    if page_idx in config.placeholder_pages:
        flags.append("unrecoverable_page_placeholder")

    columns = [str(column or "").strip() for column in (table.get("columns") or [])]
    rows = [row for row in (table.get("rows") or []) if isinstance(row, list)]
    if not columns or len(columns) < config.min_table_columns:
        flags.append("table_header_suspect")
    if len(rows) < config.min_table_rows:
        flags.append("table_parse_empty")
    if rows and columns:
        fill_ratio = table_fill_ratio(rows)
        if fill_ratio < config.sparse_table_min_fill_ratio:
            flags.append("table_too_sparse")
        mismatched = sum(1 for row in rows if len(row) != len(columns))
        if mismatched / max(len(rows), 1) >= config.ragged_row_ratio:
            flags.append("table_ragged_rows")

    bbox = table.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        width = safe_float(bbox[2]) - safe_float(bbox[0])
        height = safe_float(bbox[3]) - safe_float(bbox[1])
        if width > 0 and height > 0 and width / height > 4.5 and len(columns) >= 8:
            flags.append("rotated_or_wide_table_suspected")

    table_text = " ".join([str(table.get("caption") or ""), str(table.get("text") or "")])
    if PLACEHOLDER_TEXT_RE.search(table_text):
        flags.append("unrecoverable_page_placeholder")
    if looks_like_flattened_table(columns, rows):
        flags.append("bad_table_structure")
    return sorted(set(flags))


def page_range_overlaps_placeholders(start: Any, end: Any, placeholder_pages: Iterable[int]) -> bool:
    placeholders = set(placeholder_pages)
    if not placeholders:
        return False
    page_start = coerce_int(start)
    page_end = coerce_int(end)
    if page_start is None and page_end is None:
        return False
    page_start = page_start if page_start is not None else page_end
    page_end = page_end if page_end is not None else page_start
    assert page_start is not None and page_end is not None
    return any(page_start <= page <= page_end for page in placeholders)


def looks_like_flattened_table(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> bool:
    if not columns or not rows:
        return False
    if len(columns) == 1 and len(rows) >= 3:
        return True
    numeric_cells = 0
    long_cells = 0
    total_cells = 0
    for row in rows:
        for cell in row:
            text = str(cell or "").strip()
            if not text:
                continue
            total_cells += 1
            if NUMERIC_RE.search(text):
                numeric_cells += 1
            if len(text) > 140:
                long_cells += 1
    if total_cells == 0:
        return True
    return long_cells / total_cells > 0.35 and numeric_cells / total_cells < 0.15


def table_fill_ratio(rows: Sequence[Sequence[Any]]) -> float:
    total = 0
    filled = 0
    for row in rows:
        for cell in row:
            total += 1
            if str(cell or "").strip():
                filled += 1
    return filled / total if total else 0.0


def merge_quality_flags(row: Dict[str, Any], flags: Sequence[str]) -> None:
    existing = list(row.get("quality_flags") or [])
    row["quality_flags"] = sorted(set(existing) | set(flags))


def ensure_qa_defaults(row: Dict[str, Any]) -> None:
    row.setdefault("qa_status", "pass")
    row.setdefault("qa_flags", [])
    row.setdefault("review_reasons", [])
    row.setdefault("requires_review", False)
    row.setdefault("usable_for_ranking", not bool(row.get("requires_review")))


def mark_for_review(row: Dict[str, Any], flags: Sequence[str]) -> None:
    flags = sorted(set(flags))
    merge_quality_flags(row, flags)
    row["qa_flags"] = sorted(set(row.get("qa_flags") or []) | set(flags))
    row["qa_status"] = "fail" if SEVERE_FLAGS & set(flags) else "warning"
    row["requires_review"] = True
    row["usable_for_ranking"] = False
    reasons = set(row.get("review_reasons") or [])
    reasons.add("post_mineru_qa_gate")
    row["review_reasons"] = sorted(reasons)


def increment_counts(counts: Dict[str, int], flags: Sequence[str]) -> None:
    for flag in flags:
        counts[flag] = counts.get(flag, 0) + 1


def coerce_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload
