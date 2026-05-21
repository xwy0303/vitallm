from __future__ import annotations

import argparse
from pathlib import Path

from enzyme_recommender.ingestion import MinerUClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Continue polling an existing MinerU task.")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--result-base-url", required=True)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--timeout-seconds", default=1800.0, type=float)
    parser.add_argument("--interval-seconds", default=10.0, type=float)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = MinerUClient(
        submit_base_url=args.result_base_url,
        result_base_url=args.result_base_url,
        timeout=180.0,
    )
    result = client.poll_until_done(
        args.task_id,
        artifact_dir=args.artifact_dir,
        timeout_seconds=args.timeout_seconds,
        interval_seconds=args.interval_seconds,
    )
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
