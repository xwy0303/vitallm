from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from enzyme_recommender.rag.artifacts import (
    count_by,
    find_mineru_auto_dir,
    infer_document_id,
    load_json,
    optional_path,
)


SKIP_BLOCK_TYPES = {"header", "footer", "page_number"}
TEXT_BLOCK_TYPES = {"text", "list", "equation"}
TABLE_BLOCK_TYPES = {"table"}

SIGNAL_PATTERNS = {
    "enzyme_identity": re.compile(
        r"\b(lipase|enzyme|BCL|Burkholderia\s+cepacia|Candida|Novozym|Pseudomonas)\b",
        re.I,
    ),
    "immobilization_strategy": re.compile(
        r"\b(immobili[sz]ation|immobilized|adsorption|covalent|carrier|support|ZIF-8|MOF|metal[- ]organic framework)\b",
        re.I,
    ),
    "formulation_condition": re.compile(
        r"\b(loading|adsorption time|temperature|pH|buffer|mg|mM|min|hour|h|wt\s*%|°C|\\circ)\b",
        re.I,
    ),
    "performance_metric": re.compile(
        r"\b(activity recovery|immobili[sz]ation efficiency|yield|reusability|reuse|cycle|stability|specific activity|biodiesel yield)\b",
        re.I,
    ),
    "application_context": re.compile(
        r"\b(biodiesel|transesterification|esterification|substrate|methanol|oil|reaction system)\b",
        re.I,
    ),
}

NUMERIC_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|mg|g|mM|M|min|h|hour|hours|cycle|cycles|wt\s*%|°C|C)\b",
    re.I,
)

PERCENT_PATTERN = re.compile(r"\b(\d+(?:\.\d+)?)\s*%")


class TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: List[List[str]] = []
        self._current_row: Optional[List[str]] = None
        self._current_cell: Optional[List[str]] = None
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []
            self._in_cell = True

    def handle_data(self, data: str) -> None:
        if self._in_cell and self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            self._current_row.append(normalize_text(" ".join(self._current_cell)))
            self._current_cell = None
            self._in_cell = False
        elif tag == "tr" and self._current_row is not None:
            if any(cell for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None


@dataclass
class TextBlock:
    block_index: int
    block_type: str
    page_idx: int
    bbox: Optional[List[float]]
    text: str
    section: Optional[str]
    quality_flags: List[str] = field(default_factory=list)


def build_rag_inputs(
    artifact_dir: Path,
    source_pdf: Optional[str] = None,
    document_id: Optional[str] = None,
    max_chars: int = 1200,
    min_chars: int = 80,
) -> Dict[str, Any]:
    auto_dir = find_mineru_auto_dir(artifact_dir)
    document_id = document_id or infer_document_id(auto_dir)
    source_pdf = source_pdf or f"{document_id}.pdf"

    content_list_path = auto_dir / f"{document_id}_content_list.json"
    content_list_v2_path = optional_path(auto_dir, document_id, "_content_list_v2.json")
    md_path = optional_path(auto_dir, document_id, ".md")
    middle_path = optional_path(auto_dir, document_id, "_middle.json")
    model_path = optional_path(auto_dir, document_id, "_model.json")

    content_items = load_json(content_list_path)
    if not isinstance(content_items, list):
        raise ValueError(f"expected list in {content_list_path}")

    text_blocks, table_records = split_content_items(content_items, document_id, source_pdf)
    rag_chunks = build_text_chunks(
        text_blocks,
        document_id=document_id,
        source_pdf=source_pdf,
        max_chars=max_chars,
        min_chars=min_chars,
    )
    table_chunks = build_table_chunks(table_records, document_id=document_id, source_pdf=source_pdf)
    extraction_candidates = build_extraction_candidates(rag_chunks, table_records)

    all_chunks = rag_chunks + table_chunks
    manifest = {
        "document_id": document_id,
        "source_pdf": source_pdf,
        "artifact_dir": str(auto_dir),
        "inputs": {
            "content_list": str(content_list_path),
            "content_list_v2": str(content_list_v2_path) if content_list_v2_path else None,
            "markdown": str(md_path) if md_path else None,
            "middle_json": str(middle_path) if middle_path else None,
            "model_json": str(model_path) if model_path else None,
        },
        "counts": {
            "content_items": len(content_items),
            "block_types": count_by(content_items, "type"),
            "pages": count_pages(content_items),
            "text_blocks": len(text_blocks),
            "rag_chunks": len(all_chunks),
            "text_chunks": len(rag_chunks),
            "table_chunks": len(table_chunks),
            "table_records": len(table_records),
            "extraction_candidates": len(extraction_candidates),
        },
        "strategy": {
            "primary_input": "content_list",
            "excluded_block_types": sorted(SKIP_BLOCK_TYPES),
            "max_chars": max_chars,
            "min_chars": min_chars,
            "table_handling": "tables are stored in table_records and mirrored as table chunks for retrieval",
        },
    }
    return {
        "manifest": manifest,
        "rag_chunks": all_chunks,
        "table_records": table_records,
        "extraction_candidates": extraction_candidates,
    }


def split_content_items(
    content_items: Sequence[Dict[str, Any]],
    document_id: str,
    source_pdf: str,
) -> Tuple[List[TextBlock], List[Dict[str, Any]]]:
    text_blocks: List[TextBlock] = []
    table_records: List[Dict[str, Any]] = []
    current_section: Optional[str] = None

    for block_index, item in enumerate(content_items):
        block_type = str(item.get("type") or "")
        if block_type in SKIP_BLOCK_TYPES:
            continue

        raw_text = extract_text(item)
        text = normalize_text(raw_text)
        page_idx = int(item.get("page_idx") or 0)
        bbox = normalize_bbox(item.get("bbox"))

        section_title = detect_section_title(item, text)
        if section_title:
            current_section = section_title

        if block_type in TEXT_BLOCK_TYPES and text:
            text_blocks.append(
                TextBlock(
                    block_index=block_index,
                    block_type=block_type,
                    page_idx=page_idx,
                    bbox=bbox,
                    text=text,
                    section=current_section,
                    quality_flags=detect_quality_flags(text),
                )
            )
        elif block_type in TABLE_BLOCK_TYPES:
            table_records.append(
                build_table_record(
                    item,
                    block_index=block_index,
                    document_id=document_id,
                    source_pdf=source_pdf,
                    current_section=current_section,
                )
            )

    return text_blocks, table_records


def build_text_chunks(
    text_blocks: Sequence[TextBlock],
    document_id: str,
    source_pdf: str,
    max_chars: int,
    min_chars: int,
) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    current: List[TextBlock] = []

    def flush() -> None:
        if not current:
            return
        chunk_text = "\n\n".join(block.text for block in current)
        if len(chunk_text) < min_chars and not chunks and not extract_signals(chunk_text):
            return
        if len(chunk_text) < min_chars and chunks:
            chunks[-1]["text"] = f"{chunks[-1]['text']}\n\n{chunk_text}"
            chunks[-1]["source_block_indices"].extend(block.block_index for block in current)
            chunks[-1]["page_end"] = max(chunks[-1]["page_end"], max(block.page_idx for block in current))
            chunks[-1]["bbox"] = union_bboxes([chunks[-1].get("bbox")] + [block.bbox for block in current])
            chunks[-1]["block_types"] = sorted(set(chunks[-1]["block_types"]) | {block.block_type for block in current})
            chunks[-1]["signals"] = extract_signals(chunks[-1]["text"])
            chunks[-1]["quality_flags"] = sorted(set(chunks[-1]["quality_flags"]) | set(detect_quality_flags(chunk_text)))
            return
        chunks.append(make_text_chunk(current, len(chunks), document_id, source_pdf))

    for block in text_blocks:
        if not current:
            current = [block]
            continue

        candidate_text = "\n\n".join([existing.text for existing in current] + [block.text])
        same_section = block.section == current[-1].section
        close_page = block.page_idx <= current[-1].page_idx + 1
        if len(candidate_text) <= max_chars and same_section and close_page:
            current.append(block)
        else:
            flush()
            current = [block]
    flush()

    return chunks


def make_text_chunk(blocks: Sequence[TextBlock], chunk_index: int, document_id: str, source_pdf: str) -> Dict[str, Any]:
    text = "\n\n".join(block.text for block in blocks)
    chunk_id = f"{document_id}_chunk_{chunk_index:04d}"
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "source_pdf": source_pdf,
        "chunk_type": "text",
        "page_start": min(block.page_idx for block in blocks),
        "page_end": max(block.page_idx for block in blocks),
        "bbox": union_bboxes(block.bbox for block in blocks),
        "section": blocks[0].section,
        "block_types": sorted({block.block_type for block in blocks}),
        "source_block_indices": [block.block_index for block in blocks],
        "text": text,
        "text_sha256": sha256_text(text),
        "signals": extract_signals(text),
        "quality_flags": sorted({flag for block in blocks for flag in block.quality_flags} | set(detect_quality_flags(text))),
    }


def build_table_record(
    item: Dict[str, Any],
    block_index: int,
    document_id: str,
    source_pdf: str,
    current_section: Optional[str],
) -> Dict[str, Any]:
    page_idx = int(item.get("page_idx") or 0)
    html = str(item.get("table_body") or "")
    rows = parse_html_table(html)
    columns = rows[0] if rows else []
    caption = normalize_caption(item.get("table_caption"))
    table_id = f"{document_id}_p{page_idx}_t{block_index}"
    table_text = table_rows_to_text(columns, rows[1:])
    quality_flags = detect_table_quality_flags(columns, rows[1:])
    if not rows:
        quality_flags.append("table_parse_empty")

    return {
        "table_id": table_id,
        "document_id": document_id,
        "source_pdf": source_pdf,
        "source_block_index": block_index,
        "page_idx": page_idx,
        "bbox": normalize_bbox(item.get("bbox")),
        "section": current_section,
        "caption": caption,
        "columns": columns,
        "rows": rows[1:] if rows else [],
        "row_count": max(len(rows) - 1, 0),
        "html": html,
        "img_path": item.get("img_path"),
        "text": table_text,
        "signals": extract_signals(f"{caption}\n{table_text}"),
        "quality_flags": sorted(set(quality_flags)),
    }


def build_table_chunks(
    table_records: Sequence[Dict[str, Any]],
    document_id: str,
    source_pdf: str,
) -> List[Dict[str, Any]]:
    chunks = []
    for index, table in enumerate(table_records):
        text = "\n".join(part for part in [table.get("caption"), table.get("text")] if part)
        chunks.append(
            {
                "chunk_id": f"{document_id}_table_chunk_{index:04d}",
                "document_id": document_id,
                "source_pdf": source_pdf,
                "chunk_type": "table",
                "page_start": table["page_idx"],
                "page_end": table["page_idx"],
                "bbox": table.get("bbox"),
                "section": table.get("section"),
                "block_types": ["table"],
                "source_block_indices": [table["source_block_index"]],
                "table_id": table["table_id"],
                "text": text,
                "text_sha256": sha256_text(text),
                "signals": table.get("signals", []),
                "quality_flags": table.get("quality_flags", []),
            }
        )
    return chunks


def build_extraction_candidates(
    rag_chunks: Sequence[Dict[str, Any]],
    table_records: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for chunk in rag_chunks:
        candidate_types = candidate_types_from_signals(chunk.get("signals", []))
        if not candidate_types:
            continue
        candidates.append(
            {
                "candidate_id": f"cand_{chunk['chunk_id']}",
                "candidate_source": "rag_chunk",
                "candidate_types": candidate_types,
                "document_id": chunk["document_id"],
                "source_pdf": chunk["source_pdf"],
                "page_start": chunk["page_start"],
                "page_end": chunk["page_end"],
                "bbox": chunk.get("bbox"),
                "source_id": chunk["chunk_id"],
                "source_block_indices": chunk["source_block_indices"],
                "section": chunk.get("section"),
                "text": chunk["text"],
                "signals": chunk.get("signals", []),
                "quality_flags": chunk.get("quality_flags", []),
            }
        )

    for table in table_records:
        candidate_types = candidate_types_from_signals(table.get("signals", []))
        if "table_metric" not in candidate_types:
            candidate_types.append("table_metric")
        candidates.append(
            {
                "candidate_id": f"cand_{table['table_id']}",
                "candidate_source": "table_record",
                "candidate_types": sorted(set(candidate_types)),
                "document_id": table["document_id"],
                "source_pdf": table["source_pdf"],
                "page_start": table["page_idx"],
                "page_end": table["page_idx"],
                "bbox": table.get("bbox"),
                "source_id": table["table_id"],
                "source_block_indices": [table["source_block_index"]],
                "section": table.get("section"),
                "text": "\n".join(part for part in [table.get("caption"), table.get("text")] if part),
                "signals": table.get("signals", []),
                "quality_flags": table.get("quality_flags", []),
            }
        )
    return candidates


def extract_text(item: Dict[str, Any]) -> str:
    if item.get("type") == "equation":
        return str(item.get("text") or "")
    if item.get("type") == "list":
        value = item.get("text") or item.get("list_body") or ""
        return str(value)
    return str(item.get("text") or "")


def detect_section_title(item: Dict[str, Any], text: str) -> Optional[str]:
    if not text:
        return None
    if item.get("text_level") is not None:
        return text
    if re.match(r"^\d+(?:\.\d+)*\.\s+\S+", text):
        return text
    return None


def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_caption(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, list):
        text = " ".join(str(item) for item in value)
    else:
        text = str(value)
    text = normalize_text(text)
    return text or None


def normalize_bbox(value: Any) -> Optional[List[float]]:
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        return [float(number) for number in value]
    except (TypeError, ValueError):
        return None


def union_bboxes(bboxes: Iterable[Optional[List[float]]]) -> Optional[List[float]]:
    valid = [bbox for bbox in bboxes if bbox is not None]
    if not valid:
        return None
    return [
        min(bbox[0] for bbox in valid),
        min(bbox[1] for bbox in valid),
        max(bbox[2] for bbox in valid),
        max(bbox[3] for bbox in valid),
    ]


def parse_html_table(html: str) -> List[List[str]]:
    parser = TableHTMLParser()
    parser.feed(html)
    return parser.rows


def table_rows_to_text(columns: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = []
    if columns:
        lines.append("Columns: " + " | ".join(columns))
    for index, row in enumerate(rows, start=1):
        if columns and len(columns) == len(row):
            pairs = [f"{column}: {cell}" for column, cell in zip(columns, row)]
            lines.append(f"Row {index}: " + "; ".join(pairs))
        else:
            lines.append(f"Row {index}: " + " | ".join(row))
    return "\n".join(lines)


def extract_signals(text: str) -> List[str]:
    signals = [name for name, pattern in SIGNAL_PATTERNS.items() if pattern.search(text)]
    numeric_signals = sorted(set(match.group(0) for match in NUMERIC_PATTERN.finditer(text)))
    signals.extend(f"numeric:{value}" for value in numeric_signals[:20])
    return signals


def candidate_types_from_signals(signals: Sequence[str]) -> List[str]:
    signal_set = set(signals)
    candidates = []
    for candidate in [
        "enzyme_identity",
        "immobilization_strategy",
        "formulation_condition",
        "performance_metric",
        "application_context",
    ]:
        if candidate in signal_set:
            candidates.append(candidate)
    return candidates


def detect_quality_flags(text: str) -> List[str]:
    flags = []
    percentages = []
    for match in PERCENT_PATTERN.finditer(text):
        try:
            percentages.append(float(match.group(1)))
        except ValueError:
            continue
    if any(value > 300 for value in percentages):
        flags.append("suspicious_percent_gt_300")
    if has_likely_ocr_repetition(text):
        flags.append("possible_ocr_duplicate_text")
    return flags


def detect_table_quality_flags(columns: Sequence[str], rows: Sequence[Sequence[str]]) -> List[str]:
    flags = []
    lower_columns = [column.lower() for column in columns]
    yield_indices = [
        index
        for index, column in enumerate(lower_columns)
        if "yield" in column and "%" in column
    ]
    reference_indices = [
        index
        for index, column in enumerate(lower_columns)
        if "reference" in column
    ]

    for row in rows:
        for index in yield_indices:
            if index >= len(row):
                continue
            value = parse_numeric_prefix(row[index])
            if value is not None and value > 100:
                flags.append("suspicious_table_yield_gt_100")
        for index in reference_indices:
            if index >= len(row):
                continue
            reference = row[index].strip()
            if reference and reference != "This study" and not reference.startswith("["):
                flags.append("suspicious_reference_cell")
    return sorted(set(flags))


def parse_numeric_prefix(value: str) -> Optional[float]:
    match = re.search(r"\d+(?:\.\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def has_likely_ocr_repetition(text: str) -> bool:
    words = re.findall(r"[A-Za-z]{4,}", text.lower())
    if len(words) < 40:
        return False
    bigrams = [" ".join(words[index : index + 2]) for index in range(len(words) - 1)]
    unique = len(set(bigrams))
    return unique / max(len(bigrams), 1) < 0.72


def count_pages(content_items: Sequence[Dict[str, Any]]) -> int:
    pages = {item.get("page_idx") for item in content_items if item.get("page_idx") is not None}
    return len(pages)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
