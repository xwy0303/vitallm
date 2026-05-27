from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
for import_root in [REPO_ROOT, SRC_ROOT]:
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from enzyme_recommender.rag.enzyme_aliases import expand_query_for_retrieval, matched_enzyme_alias_keys
from enzyme_recommender.runtime import RuntimeServices


PAIRED_QUERIES = [
    {
        "id": "bcl_carrier",
        "zh": "伯克霍尔德菌脂肪酶 推荐固定化载体",
        "en": "Burkholderia cepacia lipase recommend immobilization carrier",
    },
    {
        "id": "calb_carrier",
        "zh": "南极假丝酵母脂肪酶B 推荐固定化载体",
        "en": "Candida antarctica lipase B CALB recommend immobilization carrier",
    },
    {
        "id": "crl_carrier",
        "zh": "皱褶假丝酵母脂肪酶 推荐固定化载体",
        "en": "Candida rugosa lipase CRL recommend immobilization carrier",
    },
    {
        "id": "pfl_carrier",
        "zh": "假单胞菌脂肪酶 推荐固定化载体",
        "en": "Pseudomonas lipase recommend immobilization carrier",
    },
    {
        "id": "ppl_carrier",
        "zh": "猪胰脂肪酶 推荐固定化载体",
        "en": "porcine pancreatic lipase PPL recommend immobilization carrier",
    },
    {
        "id": "rml_conditions",
        "zh": "米根霉脂肪酶 固定化条件",
        "en": "Rhizomucor miehei lipase RML immobilization conditions",
    },
    {
        "id": "tll_support",
        "zh": "疏棉状嗜热丝孢菌脂肪酶 固定化载体",
        "en": "Thermomyces lanuginosus lipase TLL immobilization support",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test Chinese enzyme alias retrieval against English pairs.")
    parser.add_argument("--config", default=Path("configs/local.yaml"), type=Path)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--top-k", default=5, type=int)
    parser.add_argument("--output", default=None, type=Path)
    parser.add_argument("--markdown", default=None, type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime = RuntimeServices.from_config_file(args.config)
    if args.collection:
        runtime.config.vector_store.collection = args.collection
    retriever = runtime.retriever()

    pair_results: List[Dict[str, Any]] = []
    for pair in PAIRED_QUERIES:
        zh = run_query(retriever, pair["zh"], args.top_k)
        en = run_query(retriever, pair["en"], args.top_k)
        zh_docs = {item["document_id"] for item in zh["hits"] if item.get("document_id")}
        en_docs = {item["document_id"] for item in en["hits"] if item.get("document_id")}
        zh_records = {item["record_type"] for item in zh["hits"] if item.get("record_type")}
        en_records = {item["record_type"] for item in en["hits"] if item.get("record_type")}
        pair_results.append(
            {
                "id": pair["id"],
                "zh": zh,
                "en": en,
                "document_overlap": sorted(zh_docs & en_docs),
                "record_type_overlap": sorted(zh_records & en_records),
                "ok": bool((zh_docs & en_docs) or (zh_records & en_records)),
            }
        )

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config": str(args.config),
        "collection": runtime.qdrant_config().collection,
        "top_k": args.top_k,
        "total_pairs": len(pair_results),
        "passed_pairs": sum(1 for item in pair_results if item["ok"]),
        "pairs": pair_results,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(summary), encoding="utf-8")
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"Chinese alias paired smoke: {summary['passed_pairs']}/{summary['total_pairs']} pairs passed")
        for item in pair_results:
            print(
                f"- {item['id']}: ok={item['ok']} "
                f"doc_overlap={','.join(item['document_overlap']) or '-'} "
                f"record_overlap={','.join(item['record_type_overlap']) or '-'}"
            )


def run_query(retriever: Any, query: str, top_k: int) -> Dict[str, Any]:
    response = retriever.retrieve(query, top_k=top_k)
    return {
        "query": query,
        "expanded_query": expand_query_for_retrieval(query),
        "alias_keys": sorted(matched_enzyme_alias_keys(query)),
        "query_plan": response.query_plan.model_dump(mode="json") if response.query_plan else None,
        "hits": [
            {
                "rank": index,
                "score": round(hit.score, 6),
                "document_id": hit.document_id,
                "source_pdf": hit.source_pdf,
                "source_id": hit.source_id,
                "citation": hit.citation,
                "point_type": hit.point_type,
                "record_type": hit.record_type,
                "route_labels": hit.route_labels,
                "text_preview": (hit.source_chunk_text or hit.text or "")[:220],
            }
            for index, hit in enumerate(response.hits[:top_k], start=1)
        ],
    }


def render_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        "# Chinese Enzyme Alias Retrieval Smoke",
        "",
        f"- Created at: `{summary['created_at']}`",
        f"- Collection: `{summary['collection']}`",
        f"- Pairs passed: `{summary['passed_pairs']}/{summary['total_pairs']}`",
        "",
        "| Pair | OK | Doc overlap | ZH top docs | EN top docs |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for item in summary["pairs"]:
        zh_docs = ", ".join(hit.get("document_id") or "-" for hit in item["zh"]["hits"][:5])
        en_docs = ", ".join(hit.get("document_id") or "-" for hit in item["en"]["hits"][:5])
        lines.append(
            f"| {item['id']} | {str(item['ok'])} | "
            f"{', '.join(item['document_overlap']) or '-'} | {zh_docs} | {en_docs} |"
        )
    lines.append("")
    lines.append("## Details")
    for item in summary["pairs"]:
        lines.extend(
            [
                "",
                f"### {item['id']}",
                "",
                f"- ZH expanded: `{item['zh']['expanded_query']}`",
                f"- EN expanded: `{item['en']['expanded_query']}`",
                "",
                "| Lang | Rank | Document | Record Type | Source ID | Citation | Score |",
                "| --- | ---: | --- | --- | --- | --- | ---: |",
            ]
        )
        for lang in ["zh", "en"]:
            for hit in item[lang]["hits"][:5]:
                lines.append(
                    f"| {lang.upper()} | {hit['rank']} | {hit['document_id'] or '-'} | "
                    f"{hit['record_type'] or '-'} | {hit['source_id']} | {hit['citation'] or '-'} | {hit['score']} |"
                )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
