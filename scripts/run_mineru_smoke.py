from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from enzyme_recommender.ingestion import MinerUClient, MinerUOptions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a single-PDF MinerU smoke test.")
    parser.add_argument("--pdf", required=True, type=Path, help="PDF file to submit.")
    parser.add_argument("--submit-base-url", required=True, help="MinerU submit service base URL.")
    parser.add_argument("--result-base-url", required=True, help="MinerU result service base URL.")
    parser.add_argument("--artifact-root", default="artifacts/mineru_smoke", type=Path)
    parser.add_argument("--lang-list", default="en")
    parser.add_argument("--start-page-id", default="0")
    parser.add_argument("--end-page-id", default="999")
    parser.add_argument("--return-model-output", default="false")
    parser.add_argument("--timeout-seconds", default=1800.0, type=float)
    parser.add_argument("--interval-seconds", default=10.0, type=float)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    options = MinerUOptions(
        lang_list=args.lang_list,
        start_page_id=args.start_page_id,
        end_page_id=args.end_page_id,
        return_model_output=args.return_model_output,
    )
    client = MinerUClient(
        submit_base_url=args.submit_base_url,
        result_base_url=args.result_base_url,
        timeout=180.0,
    )

    try:
        task_id, payload = client.submit_pdfs([args.pdf], options)
    except httpx.HTTPStatusError as exc:
        print(json.dumps({
            "status": "submit_failed",
            "status_code": exc.response.status_code,
            "content_type": exc.response.headers.get("content-type"),
            "body_head": exc.response.text[:1000],
        }, ensure_ascii=False, indent=2))
        raise

    artifact_dir = args.artifact_root / f"{args.pdf.stem}_{task_id}"
    manifest = client.build_manifest(task_id, [args.pdf], options=options, raw_submit_response=payload)
    manifest.artifact_dir = str(artifact_dir)
    client.write_manifest(manifest, artifact_dir)
    print(json.dumps({
        "status": "submitted",
        "task_id": task_id,
        "artifact_dir": str(artifact_dir),
    }, ensure_ascii=False, indent=2))

    result = client.poll_until_done(
        task_id,
        artifact_dir=artifact_dir,
        timeout_seconds=args.timeout_seconds,
        interval_seconds=args.interval_seconds,
    )
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

