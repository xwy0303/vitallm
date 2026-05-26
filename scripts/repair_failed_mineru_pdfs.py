from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from pypdf import PdfReader, PdfWriter


FAILED_LOAD_PAGE = "Failed to load page"
STATE_DICT_MISMATCH = "state_dict"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create non-destructive repair candidates for PDFs that failed MinerU."
    )
    parser.add_argument("--registry", default=Path("artifacts/ingestion_registry/documents.jsonl"), type=Path)
    parser.add_argument("--output-root", default=Path("artifacts/pdf_repair"), type=Path)
    parser.add_argument("--document-id", action="append", default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    documents = latest_documents(args.registry)
    selected = sorted(
        (
            document
            for document in documents.values()
            if document.get("current_status") == "failed_mineru"
            and (not args.document_id or document.get("document_id") in set(args.document_id))
        ),
        key=lambda item: str(item.get("document_id")),
    )
    report = []
    for document in selected:
        item = repair_document(document, args.output_root, dry_run=args.dry_run)
        report.append(item)
        print(json.dumps(item, ensure_ascii=False))

    if not args.dry_run:
        args.output_root.mkdir(parents=True, exist_ok=True)
        output_path = args.output_root / "repair_report.json"
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"WROTE {output_path}")


def latest_documents(path: Path) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            document = json.loads(line)
            latest[str(document.get("document_id"))] = document
    return latest


def repair_document(document: Dict[str, Any], output_root: Path, dry_run: bool = False) -> Dict[str, Any]:
    document_id = str(document.get("document_id"))
    source_pdf = str(document.get("source_pdf") or f"{document_id}.pdf")
    raw_pdf_path = Path(str(document.get("raw_pdf_path")))
    error_message = str(document.get("last_error_message") or "")
    failure_class = classify_failure(error_message)
    item: Dict[str, Any] = {
        "document_id": document_id,
        "source_pdf": source_pdf,
        "raw_pdf_path": str(raw_pdf_path),
        "failure_class": failure_class,
        "action": "none",
        "repaired_pdf_path": None,
        "render_before": None,
        "render_after": None,
        "page_count_delta": None,
        "needs_ocr_fallback": False,
        "status": "skipped",
    }
    item["render_before"] = validate_pdfium_render(raw_pdf_path)

    if failure_class == "mineru_model_state_dict_mismatch":
        item["action"] = "fix_mineru_runtime_model_cache_then_retry_original_pdf"
        item["status"] = "requires_runtime_repair"
        return item
    if failure_class != "pdf_page_load_failure":
        item["action"] = "inspect_failure_manually"
        item["status"] = "requires_manual_triage"
        return item

    output_dir = output_root / document_id
    repaired_pdf_path = output_dir / f"{Path(source_pdf).stem}.pypdf-rewrite.pdf"
    item["action"] = "pypdf_rewrite"
    item["repaired_pdf_path"] = str(repaired_pdf_path)
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        rewrite_pdf(raw_pdf_path, repaired_pdf_path)
    if repaired_pdf_path.exists():
        item["render_after"] = validate_pdfium_render(repaired_pdf_path)
        item["page_count_delta"] = page_count_delta(item["render_before"], item["render_after"])
        if item["render_after"]["bad_pages"]:
            item["status"] = "repair_candidate_partial"
            item["needs_ocr_fallback"] = True
        elif item["page_count_delta"] not in {0, None}:
            item["status"] = "repair_candidate_renderable_but_page_count_changed"
            item["needs_ocr_fallback"] = True
        else:
            item["status"] = "repair_candidate_ready"
    else:
        item["status"] = "dry_run"
    return item


def classify_failure(message: str) -> str:
    if STATE_DICT_MISMATCH in message:
        return "mineru_model_state_dict_mismatch"
    if FAILED_LOAD_PAGE in message:
        return "pdf_page_load_failure"
    return "unknown_mineru_failure"


def rewrite_pdf(input_path: Path, output_path: Path) -> None:
    reader = PdfReader(str(input_path), strict=False)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    with output_path.open("wb") as handle:
        writer.write(handle)


def page_count_delta(before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]]) -> Optional[int]:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return None
    before_count = before.get("page_count")
    after_count = after.get("page_count")
    if not isinstance(before_count, int) or not isinstance(after_count, int):
        return None
    return after_count - before_count


def validate_pdfium_render(path: Path) -> Dict[str, Any]:
    pdfium = require_pypdfium2()
    result: Dict[str, Any] = {
        "page_count": None,
        "bad_pages": [],
        "error": None,
    }
    try:
        pdf = pdfium.PdfDocument(str(path))
        result["page_count"] = len(pdf)
        bad_pages: List[Dict[str, Any]] = []
        for page_index in range(len(pdf)):
            try:
                _ = pdf[page_index].render(scale=0.2).to_pil()
            except Exception as exc:  # noqa: BLE001 - report exact renderer failure per page.
                bad_pages.append(
                    {
                        "page": page_index + 1,
                        "error_type": type(exc).__name__,
                        "message": str(exc)[:200],
                    }
                )
        result["bad_pages"] = bad_pages
    except Exception as exc:  # noqa: BLE001 - report open failure.
        result["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return result


def require_pypdfium2():
    try:
        import pypdfium2 as pdfium
    except ModuleNotFoundError as exc:  # pragma: no cover - environment guard.
        raise SystemExit(
            "pypdfium2 is required for render validation. Run with .venv-mineru/bin/python "
            "or install pypdfium2 in the active environment."
        ) from exc
    return pdfium


if __name__ == "__main__":
    main()
