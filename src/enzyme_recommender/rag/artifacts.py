from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            json.dump(row, handle, ensure_ascii=False)
            handle.write("\n")


def find_mineru_auto_dir(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_file():
        raise ValueError(f"expected a MinerU artifact directory, got file: {path}")
    if list(path.glob("*_content_list.json")):
        return path

    candidates = sorted(
        candidate.parent
        for candidate in path.rglob("*_content_list.json")
        if not candidate.name.endswith("_content_list_v2.json")
    )
    if not candidates:
        raise FileNotFoundError(f"cannot find *_content_list.json under {path}")
    if len(set(candidates)) > 1:
        candidate_text = "\n".join(str(candidate) for candidate in candidates)
        raise ValueError(f"multiple MinerU auto dirs found; pass one explicitly:\n{candidate_text}")
    return candidates[0]


def infer_document_id(auto_dir: Path) -> str:
    content_lists = sorted(
        path for path in auto_dir.glob("*_content_list.json") if not path.name.endswith("_content_list_v2.json")
    )
    if not content_lists:
        return auto_dir.parent.name
    return content_lists[0].name.replace("_content_list.json", "")


def optional_path(auto_dir: Path, document_id: str, suffix: str) -> Optional[Path]:
    path = auto_dir / f"{document_id}{suffix}"
    return path if path.exists() else None


def count_by(items: Iterable[Dict[str, Any]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "<missing>")
        counts[value] = counts.get(value, 0) + 1
    return counts

