from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from PIL import Image, ImageDraw
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

try:
    from scripts.repair_failed_mineru_pdfs import validate_pdfium_render
except ModuleNotFoundError:  # Allow direct execution as scripts/build_pdf_raster_fallbacks.py.
    from repair_failed_mineru_pdfs import validate_pdfium_render


DEFAULT_DPI = 200
MIN_RENDERED_PAGE_SIDE_PX = 100
REQUIRED_TOOLS = ["pdfinfo", "pdftoppm"]
OCR_TOOLS = ["ocrmypdf", "tesseract"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build page-count preserving raster/OCR fallback PDFs for MinerU failed documents."
    )
    parser.add_argument("--repair-report", default=Path("artifacts/pdf_repair/repair_report.json"), type=Path)
    parser.add_argument("--output-root", default=Path("artifacts/pdf_raster_fallback"), type=Path)
    parser.add_argument("--document-id", action="append", default=None)
    parser.add_argument("--dpi", default=DEFAULT_DPI, type=int)
    parser.add_argument("--no-ocr", action="store_true", help="Only build raster image PDFs; skip OCRmyPDF.")
    parser.add_argument("--jobs", default=2, type=int, help="OCRmyPDF worker count.")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    require_tools(REQUIRED_TOOLS)
    if not args.no_ocr:
        require_tools(OCR_TOOLS)
    report_items = load_repair_report(args.repair_report)
    selected = select_repair_items(report_items, document_ids=args.document_id)
    results = []
    for item in selected:
        result = build_fallback_for_document(
            item,
            output_root=args.output_root,
            dpi=args.dpi,
            run_ocr=not args.no_ocr,
            jobs=args.jobs,
            overwrite=args.overwrite,
        )
        results.append(result)
        print(json.dumps(summarize_item_for_stdout(result), ensure_ascii=False))

    args.output_root.mkdir(parents=True, exist_ok=True)
    output_path = args.output_root / "fallback_report.json"
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {output_path}")


def require_tools(names: Sequence[str]) -> None:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        raise SystemExit(f"missing required command(s): {', '.join(missing)}")


def load_repair_report(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"expected list repair report: {path}")
    return [dict(item) for item in payload if isinstance(item, dict)]


def select_repair_items(
    report_items: Sequence[Dict[str, Any]],
    document_ids: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    allowed = set(document_ids or [])
    selected = [
        item
        for item in report_items
        if item.get("needs_ocr_fallback") is True and (not allowed or item.get("document_id") in allowed)
    ]
    return sorted(selected, key=lambda item: str(item.get("document_id")))


def build_fallback_for_document(
    item: Dict[str, Any],
    output_root: Path,
    dpi: int,
    run_ocr: bool,
    jobs: int,
    overwrite: bool = False,
) -> Dict[str, Any]:
    document_id = str(item.get("document_id"))
    source_pdf = Path(str(item.get("raw_pdf_path"))).expanduser()
    expected_pages = int(item.get("render_before", {}).get("page_count") or pdfinfo_page_count(source_pdf))
    output_dir = output_root / document_id
    pages_dir = output_dir / "pages"
    raster_pdf_path = output_dir / f"{document_id}.raster-image.pdf"
    ocr_pdf_path = output_dir / f"{document_id}.raster-ocr.pdf"
    manifest_path = output_dir / "fallback_manifest.json"

    output_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)
    if overwrite:
        clean_directory(pages_dir)
        for path in [raster_pdf_path, ocr_pdf_path, manifest_path]:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    page_results: List[Dict[str, Any]] = []
    image_paths: List[Path] = []
    last_size: Optional[tuple[int, int]] = None
    for page_number in range(1, expected_pages + 1):
        image_path = pages_dir / f"page_{page_number:04d}.png"
        if not image_path.exists() or overwrite:
            page_result = render_page_with_poppler(source_pdf, image_path, page_number, dpi=dpi)
        else:
            page_result = {"page": page_number, "status": "cached", "image_path": str(image_path)}

        if image_path.exists():
            with Image.open(image_path) as image:
                image_size = image.size
            if is_tiny_render(image_size):
                placeholder_size = last_size or (int(8.27 * dpi), int(11.69 * dpi))
                write_placeholder_page(
                    image_path,
                    page_number,
                    document_id,
                    placeholder_size,
                    reason="Rendered page was abnormally small.",
                )
                page_result.update(
                    {
                        "status": "placeholder",
                        "image_path": str(image_path),
                        "placeholder_reason": "tiny_render",
                        "rendered_size": list(image_size),
                    }
                )
            else:
                last_size = image_size
                page_result["image_size"] = list(image_size)
            page_result["image_path"] = str(image_path)
        else:
            placeholder_size = last_size or (int(8.27 * dpi), int(11.69 * dpi))
            write_placeholder_page(
                image_path,
                page_number,
                document_id,
                placeholder_size,
                reason="Original PDF page could not be rasterized.",
            )
            page_result.update(
                {
                    "status": "placeholder",
                    "image_path": str(image_path),
                    "placeholder_reason": "pdftoppm_failed",
                }
            )
        page_results.append(page_result)
        image_paths.append(image_path)

    write_image_pdf(image_paths, raster_pdf_path, dpi=dpi)
    final_pdf_path = raster_pdf_path
    ocr_result: Dict[str, Any] = {"status": "skipped", "output_pdf_path": None}
    if run_ocr:
        ocr_result = run_ocrmypdf(raster_pdf_path, ocr_pdf_path, jobs=jobs)
        if ocr_result["status"] == "succeeded":
            final_pdf_path = ocr_pdf_path

    final_pdfinfo_pages = pdfinfo_page_count(final_pdf_path)
    final_pdfium = validate_pdfium_render(final_pdf_path)
    placeholder_pages = [
        int(page["page"])
        for page in page_results
        if page.get("status") == "placeholder"
    ]
    status = "fallback_ready"
    if final_pdfinfo_pages != expected_pages:
        status = "page_count_mismatch"
    elif final_pdfium.get("bad_pages"):
        status = "render_validation_failed"
    elif placeholder_pages:
        status = "fallback_ready_with_placeholders"
    elif run_ocr and ocr_result["status"] != "succeeded":
        status = "raster_ready_ocr_failed"

    result = {
        "document_id": document_id,
        "source_pdf": item.get("source_pdf"),
        "raw_pdf_path": str(source_pdf),
        "expected_pages": expected_pages,
        "source_pdfium_bad_pages": [
            bad_page.get("page")
            for bad_page in item.get("render_before", {}).get("bad_pages", [])
            if isinstance(bad_page, dict)
        ],
        "dpi": dpi,
        "raster_pdf_path": str(raster_pdf_path),
        "ocr_pdf_path": str(ocr_pdf_path) if ocr_result["status"] == "succeeded" else None,
        "final_pdf_path": str(final_pdf_path),
        "ocr_result": ocr_result,
        "final_pdfinfo_pages": final_pdfinfo_pages,
        "final_pdfium_render": final_pdfium,
        "placeholder_pages": placeholder_pages,
        "page_results": page_results,
        "status": status,
    }
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def clean_directory(path: Path) -> None:
    for child in path.iterdir():
        if child.is_file():
            child.unlink()


def render_page_with_poppler(source_pdf: Path, image_path: Path, page_number: int, dpi: int) -> Dict[str, Any]:
    prefix = image_path.with_suffix("")
    command = [
        "pdftoppm",
        "-f",
        str(page_number),
        "-l",
        str(page_number),
        "-r",
        str(dpi),
        "-png",
        "-singlefile",
        str(source_pdf),
        str(prefix),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode == 0 and image_path.exists():
        return {
            "page": page_number,
            "status": "rendered",
            "image_path": str(image_path),
            "stderr": completed.stderr.strip()[:1000],
        }
    return {
        "page": page_number,
        "status": "render_failed",
        "image_path": str(image_path),
        "returncode": completed.returncode,
        "stderr": completed.stderr.strip()[:1000],
    }

def is_tiny_render(size: tuple[int, int]) -> bool:
    return size[0] < MIN_RENDERED_PAGE_SIDE_PX or size[1] < MIN_RENDERED_PAGE_SIDE_PX


def write_placeholder_page(
    image_path: Path,
    page_number: int,
    document_id: str,
    size: tuple[int, int],
    reason: str,
) -> None:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    text = (
        f"{document_id} page {page_number}\n"
        "UNRECOVERABLE PAGE PLACEHOLDER\n"
        f"{reason}"
    )
    draw.multiline_text((72, 72), text, fill="black", spacing=12)
    image.save(image_path)


def write_image_pdf(image_paths: Sequence[Path], output_path: Path, dpi: int) -> None:
    pdf = canvas.Canvas(str(output_path))
    for image_path in image_paths:
        with Image.open(image_path) as image:
            width_px, height_px = image.size
        width_pt = width_px * 72.0 / dpi
        height_pt = height_px * 72.0 / dpi
        pdf.setPageSize((width_pt, height_pt))
        pdf.drawImage(ImageReader(str(image_path)), 0, 0, width=width_pt, height=height_pt)
        pdf.showPage()
    pdf.save()


def run_ocrmypdf(input_pdf: Path, output_pdf: Path, jobs: int) -> Dict[str, Any]:
    command = [
        "ocrmypdf",
        "--rotate-pages",
        "--deskew",
        "--jobs",
        str(jobs),
        "--output-type",
        "pdf",
        str(input_pdf),
        str(output_pdf),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    status = "succeeded" if completed.returncode == 0 and output_pdf.exists() else "failed"
    return {
        "status": status,
        "output_pdf_path": str(output_pdf) if status == "succeeded" else None,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def pdfinfo_page_count(path: Path) -> int:
    completed = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, check=True)
    for line in completed.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise ValueError(f"pdfinfo did not report page count: {path}")


def summarize_item_for_stdout(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "document_id": result["document_id"],
        "status": result["status"],
        "expected_pages": result["expected_pages"],
        "final_pdfinfo_pages": result["final_pdfinfo_pages"],
        "placeholder_pages": result["placeholder_pages"],
        "final_pdf_path": result["final_pdf_path"],
    }


if __name__ == "__main__":
    main()
