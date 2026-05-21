from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from typing import Iterable


TEXT_SUFFIXES = {".md", ".txt", ".json"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize MinerU artifact files for extraction readiness.")
    parser.add_argument("artifact", type=Path, help="Artifact directory or zip file.")
    parser.add_argument("--preview-chars", default=800, type=int)
    return parser.parse_args()


def iter_files(path: Path) -> Iterable[Path]:
    if path.is_dir():
        yield from sorted(p for p in path.rglob("*") if p.is_file())
    else:
        yield path


def classify_file(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".md"):
        return "markdown"
    if "content" in name and path.suffix.lower() == ".json":
        return "content_list"
    if "middle" in name and path.suffix.lower() == ".json":
        return "middle_json"
    if "table" in name and path.suffix.lower() in {".json", ".html", ".xlsx", ".csv"}:
        return "table"
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image"
    return "other"


def read_preview(path: Path, limit: int) -> str:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    return text[:limit]


def summarize_json(path: Path) -> dict:
    if path.suffix.lower() != ".json":
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"json_error": "invalid_json"}
    if isinstance(payload, list):
        return {"json_type": "list", "items": len(payload)}
    if isinstance(payload, dict):
        return {"json_type": "dict", "keys": sorted(payload.keys())[:30]}
    return {"json_type": type(payload).__name__}


def summarize_zip(path: Path, preview_chars: int) -> dict:
    with zipfile.ZipFile(path) as archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        by_kind = {}
        previews = []
        for member in members:
            suffix = Path(member.filename).suffix.lower()
            kind = classify_file(Path(member.filename))
            by_kind[kind] = by_kind.get(kind, 0) + 1
            if suffix in TEXT_SUFFIXES and len(previews) < 5:
                text = archive.read(member).decode("utf-8", errors="ignore")
                previews.append({
                    "name": member.filename,
                    "kind": kind,
                    "size": member.file_size,
                    "preview": text[:preview_chars],
                })
        return {
            "artifact": str(path),
            "type": "zip",
            "file_count": len(members),
            "by_kind": by_kind,
            "previews": previews,
        }


def summarize_dir(path: Path, preview_chars: int) -> dict:
    files = list(iter_files(path))
    by_kind = {}
    previews = []
    json_summaries = []
    for file_path in files:
        kind = classify_file(file_path)
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if file_path.suffix.lower() in TEXT_SUFFIXES and len(previews) < 8:
            previews.append({
                "name": str(file_path.relative_to(path)),
                "kind": kind,
                "size": file_path.stat().st_size,
                "preview": read_preview(file_path, preview_chars),
            })
        if file_path.suffix.lower() == ".json" and len(json_summaries) < 12:
            json_summaries.append({
                "name": str(file_path.relative_to(path)),
                "kind": kind,
                **summarize_json(file_path),
            })
    return {
        "artifact": str(path),
        "type": "directory",
        "file_count": len(files),
        "by_kind": by_kind,
        "json_summaries": json_summaries,
        "previews": previews,
    }


def main() -> None:
    args = parse_args()
    artifact = args.artifact
    if artifact.suffix.lower() == ".zip":
        summary = summarize_zip(artifact, args.preview_chars)
    else:
        summary = summarize_dir(artifact, args.preview_chars)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

