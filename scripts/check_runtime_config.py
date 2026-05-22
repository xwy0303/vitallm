from __future__ import annotations

import argparse
from pathlib import Path

from enzyme_recommender.generators import ChatMessage, GenerationRequest
from enzyme_recommender.runtime import RuntimeServices


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate runtime config and generator protocol wiring.")
    parser.add_argument("--config", default=Path("configs/local.yaml"), type=Path)
    parser.add_argument("--run-mock-generation", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime = RuntimeServices.from_config_file(args.config)
    config = runtime.config
    print(f"Runtime config: {args.config}")
    print(f"Document parser: {config.document_parser.provider} {config.document_parser.submit_base_url}")
    print(f"Vector store: {config.vector_store.provider} {config.vector_store.url} collection={config.vector_store.collection}")
    print(f"Embedding: {config.embedding.provider} dimensions={config.embedding.dimensions}")
    print(f"Generator: {config.generator.provider}")

    if args.run_mock_generation:
        generator = runtime.generator()
        response = generator.generate(
            GenerationRequest(
                messages=[
                    ChatMessage(role="system", content="You are an evidence-first enzyme immobilization assistant."),
                    ChatMessage(role="user", content="Recommend an immobilization carrier for Burkholderia cepacia lipase."),
                ],
                model=config.generator_providers[config.generator.provider].model,
                temperature=config.generator.temperature,
                response_format="json_object",
                timeout_seconds=config.generator.timeout_seconds,
                max_retries=config.generator.max_retries,
            )
        )
        print(f"Mock generation provider={response.provider} model={response.model}")
        print(response.content)


if __name__ == "__main__":
    main()
