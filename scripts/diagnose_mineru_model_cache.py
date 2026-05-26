from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


WEIGHT_FILES = {
    "ch_det": "ch_PP-OCRv5_det_infer.pth",
    "seal_det": "seal_PP-OCRv4_det_server_infer.pth",
    "seal_lite_det": "seal_PP-OCRv4_det_infer.pth",
}

EXPECTED_HEAD_SHAPES = {
    "ch_det": (24, 96, 3, 3),
    "seal_det": (64, 256, 3, 3),
    "seal_lite_det": (24, 96, 3, 3),
}

HEAD_WEIGHT_KEY = "head.binarize.conv1.weight"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose local MinerU OCR/seal model cache without submitting PDFs. "
            "Run with the MinerU Python runtime for torch tensor inspection."
        )
    )
    parser.add_argument(
        "--model-root",
        default=None,
        type=Path,
        help="Optional PDF-Extract-Kit model root. Defaults to the newest HuggingFace cache snapshot.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON only.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_report(args.model_root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print(json.dumps(report, ensure_ascii=False, indent=2))
    verdict = report.get("verdict", {})
    print()
    print(f"VERDICT status={verdict.get('status')} reason={verdict.get('reason')}")
    if verdict.get("recommended_action"):
        print(f"RECOMMENDED_ACTION {verdict['recommended_action']}")


def build_report(model_root: Optional[Path]) -> Dict[str, Any]:
    resolved_model_root = model_root.expanduser().resolve() if model_root else find_latest_pdf_extract_kit_snapshot()
    report: Dict[str, Any] = {
        "status": "ok",
        "mineru": mineru_runtime_info(),
        "environment": {
            "MINERU_DEVICE_MODE": os.environ.get("MINERU_DEVICE_MODE"),
        },
        "model_root": str(resolved_model_root) if resolved_model_root else None,
        "weights": {},
        "verdict": {},
    }
    if resolved_model_root is None:
        report["status"] = "failed"
        report["verdict"] = {
            "status": "unknown",
            "reason": "PDF-Extract-Kit HuggingFace cache snapshot was not found",
            "recommended_action": "start MinerU once or download the PDF-Extract-Kit models, then rerun this diagnostic",
        }
        return report

    torch_error: Optional[str] = None
    try:
        import torch
    except Exception as exc:  # noqa: BLE001 - report runtime import failure.
        torch = None  # type: ignore[assignment]
        torch_error = f"{type(exc).__name__}: {exc}"

    for label, filename in WEIGHT_FILES.items():
        path = resolved_model_root / "models" / "OCR" / "paddleocr_torch" / filename
        report["weights"][label] = inspect_weight_file(
            path=path,
            expected_shape=EXPECTED_HEAD_SHAPES[label],
            torch_module=torch if torch_error is None else None,
            torch_error=torch_error,
        )
    report["verdict"] = build_verdict(report)
    if report["verdict"].get("status") != "ok":
        report["status"] = "failed"
    return report


def mineru_runtime_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "package_origin": None,
        "package_version": None,
        "reported_device": None,
        "torch": None,
    }
    spec = importlib.util.find_spec("mineru")
    if spec and spec.origin:
        info["package_origin"] = spec.origin
    try:
        info["package_version"] = importlib.metadata.version("mineru")
    except importlib.metadata.PackageNotFoundError:
        info["package_version"] = None

    try:
        from mineru.utils.config_reader import get_device

        info["reported_device"] = get_device()
    except Exception as exc:  # noqa: BLE001 - diagnostic only.
        info["reported_device_error"] = f"{type(exc).__name__}: {exc}"

    try:
        import torch

        info["torch"] = {
            "version": getattr(torch, "__version__", None),
            "cuda_available": bool(torch.cuda.is_available()),
            "mps_available": bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()),
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic only.
        info["torch_error"] = f"{type(exc).__name__}: {exc}"
    return info


def find_latest_pdf_extract_kit_snapshot() -> Optional[Path]:
    root = (
        Path.home()
        / ".cache"
        / "huggingface"
        / "hub"
        / "models--opendatalab--PDF-Extract-Kit-1.0"
        / "snapshots"
    )
    if not root.is_dir():
        return None
    snapshots = sorted((path for path in root.iterdir() if path.is_dir()), key=lambda item: item.stat().st_mtime)
    return snapshots[-1] if snapshots else None


def inspect_weight_file(
    path: Path,
    expected_shape: tuple[int, ...],
    torch_module: Any,
    torch_error: Optional[str],
) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else None,
        "expected_head_shape": list(expected_shape),
        "head_shape": None,
        "first_keys": [],
        "matches_expected_shape": None,
        "error": None,
    }
    if not path.is_file():
        item["error"] = "file_not_found"
        return item
    if torch_error:
        item["error"] = f"torch_unavailable: {torch_error}"
        return item
    try:
        state = torch_module.load(path, map_location="cpu", weights_only=True)
        if not isinstance(state, dict):
            item["error"] = f"unexpected_state_type: {type(state).__name__}"
            return item
        keys = list(state.keys())
        item["first_keys"] = keys[:8]
        tensor = state.get(HEAD_WEIGHT_KEY)
        if tensor is None:
            item["error"] = f"missing_tensor: {HEAD_WEIGHT_KEY}"
            return item
        head_shape = tuple(int(value) for value in tensor.shape)
        item["head_shape"] = list(head_shape)
        item["matches_expected_shape"] = head_shape == expected_shape
    except Exception as exc:  # noqa: BLE001 - diagnostic should report exact local failure.
        item["error"] = f"{type(exc).__name__}: {exc}"
    return item


def build_verdict(report: Dict[str, Any]) -> Dict[str, Any]:
    weights = report.get("weights") or {}
    missing = [label for label, item in weights.items() if not item.get("exists")]
    errors = [label for label, item in weights.items() if item.get("error")]
    mismatched = [label for label, item in weights.items() if item.get("matches_expected_shape") is False]
    seal = weights.get("seal_det") or {}
    seal_lite = weights.get("seal_lite_det") or {}
    device = ((report.get("mineru") or {}).get("reported_device") or "").lower()

    if errors:
        file_not_found_errors = [
            label for label, item in weights.items() if str(item.get("error") or "") == "file_not_found"
        ]
        non_missing_errors = sorted(set(errors) - set(file_not_found_errors))
        if non_missing_errors:
            return {
                "status": "inspection_failed",
                "reason": f"could not inspect weight files: {', '.join(non_missing_errors)}",
                "recommended_action": "run this script with the MinerU virtualenv Python",
            }
    if missing:
        if "seal_lite_det" in missing and "seal_det" in mismatched:
            return {
                "status": "seal_cache_incomplete_and_server_mismatched",
                "reason": (
                    "seal_lite detector is missing and seal server detector has a lite tensor shape; "
                    "CPU fallback needs seal_lite to be downloadable or restored first"
                ),
                "recommended_action": (
                    "let MinerU/HuggingFace redownload seal_PP-OCRv4_det_infer.pth, or repair the model cache, "
                    "then set MINERU_DEVICE_MODE=cpu and retry failed original PDFs"
                ),
            }
        return {
            "status": "cache_incomplete",
            "reason": f"missing weight files: {', '.join(missing)}",
            "recommended_action": "redownload the PDF-Extract-Kit OCR model cache before retrying failed PDFs",
        }
    if "seal_det" in mismatched and seal.get("head_shape") == seal_lite.get("head_shape"):
        action = "set MINERU_DEVICE_MODE=cpu and restart MinerU, or redownload the seal server OCR weight"
        if device == "cpu":
            action = "MinerU is already reporting CPU; retry the failed original PDFs before changing model cache"
        return {
            "status": "known_seal_server_weight_mismatch",
            "reason": (
                "seal_PP-OCRv4_det_server_infer.pth has the lite detector tensor shape, "
                "so MPS/CUDA seal OCR can fail while CPU seal_lite avoids this path"
            ),
            "recommended_action": action,
        }
    if mismatched:
        return {
            "status": "weight_shape_mismatch",
            "reason": f"unexpected OCR detector tensor shape: {', '.join(mismatched)}",
            "recommended_action": "repair or redownload the mismatched model files before retrying failed PDFs",
        }
    return {
        "status": "ok",
        "reason": "all inspected OCR detector weights match expected tensor shapes",
        "recommended_action": None,
    }


def _shape(value: Iterable[int]) -> list[int]:
    return [int(item) for item in value]


if __name__ == "__main__":
    main()
