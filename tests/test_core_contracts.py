from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from enzyme_recommender.rag.embedding import HashEmbeddingConfig, HashEmbeddingModel
from enzyme_recommender.rag.qdrant import build_index_points, citation, extract_collection_vector_size
from enzyme_recommender.rag.retrieval import RetrievalHit, RetrievalResponse
from enzyme_recommender.generators import ChatMessage, GenerationRequest, MockGeneratorClient
from enzyme_recommender.api.app import resolve_pdf_file
from enzyme_recommender.recommendation.enzyme import resolve_evidence_refs
from enzyme_recommender.runtime.config import RuntimeConfig


class RuntimeConfigTests(unittest.TestCase):
    def test_embedding_local_files_only_is_loaded_from_yaml(self) -> None:
        config = RuntimeConfig.from_file(Path("configs/local.yaml"))

        self.assertEqual(config.embedding.provider, "hash_v1")
        self.assertEqual(config.embedding.dimensions, 768)
        self.assertTrue(config.embedding.local_files_only)


class QdrantContractTests(unittest.TestCase):
    def test_extract_collection_vector_size_for_single_vector_config(self) -> None:
        payload = {"config": {"params": {"vectors": {"size": 768, "distance": "Cosine"}}}}

        self.assertEqual(extract_collection_vector_size(payload), 768)

    def test_extract_collection_vector_size_for_named_vector_config(self) -> None:
        payload = {
            "config": {
                "params": {
                    "vectors": {
                        "text": {"size": 384, "distance": "Cosine"},
                        "table": {"size": 384, "distance": "Cosine"},
                    }
                }
            }
        }

        self.assertEqual(extract_collection_vector_size(payload), 384)

    def test_citation_displays_mineru_page_idx_as_one_based_pdf_page(self) -> None:
        self.assertEqual(citation({"source_pdf": "A21.pdf", "page_start": 9, "page_end": 9}), "A21.pdf:p10")
        self.assertEqual(citation({"source_pdf": "A21.pdf", "page_start": 9, "page_end": 10}), "A21.pdf:p10-p11")


class IndexPointTests(unittest.TestCase):
    def test_build_index_points_preserves_payload_and_vector_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rag_dir = root / "rag"
            evidence_dir = root / "evidence"
            rag_dir.mkdir()
            evidence_dir.mkdir()

            write_jsonl(
                rag_dir / "rag_chunks.jsonl",
                [
                    {
                        "chunk_id": "B10_chunk_0001",
                        "document_id": "B10",
                        "source_pdf": "B10.pdf",
                        "chunk_type": "text",
                        "page_start": 0,
                        "page_end": 0,
                        "section": "Abstract",
                        "source_block_indices": [1],
                        "signals": ["enzyme_identity"],
                        "quality_flags": [],
                        "text": "Burkholderia cepacia lipase immobilized on ZIF-8.",
                    }
                ],
            )
            write_jsonl(rag_dir / "table_records.jsonl", [])
            write_jsonl(
                evidence_dir / "evidence_records.jsonl",
                [
                    {
                        "evidence_id": "ev_test",
                        "record_type": "immobilization_strategy",
                        "document_id": "B10",
                        "source_pdf": "B10.pdf",
                        "source_id": "B10_chunk_0001",
                        "page_start": 0,
                        "page_end": 0,
                        "section": "Abstract",
                        "evidence_span": "ZIF-8 carrier",
                        "extracted": {"carrier": "ZIF-8"},
                        "metrics": [],
                        "quality_flags": [],
                        "review_reasons": [],
                        "requires_review": False,
                        "confidence": "medium",
                    }
                ],
            )

            points = build_index_points(
                rag_input_dir=rag_dir,
                evidence_dir=evidence_dir,
                embedding_model=HashEmbeddingModel(HashEmbeddingConfig(dimensions=64)),
            )

        self.assertEqual(len(points), 2)
        self.assertTrue(all(len(point["vector"]) == 64 for point in points))
        self.assertEqual({point["payload"]["point_type"] for point in points}, {"rag_chunk", "evidence_record"})
        self.assertEqual({point["payload"]["citation"] for point in points}, {"B10.pdf:p1"})


class EvidenceReferenceTests(unittest.TestCase):
    def test_resolve_evidence_refs_filters_hallucinated_references(self) -> None:
        retrieval = RetrievalResponse(
            query="bcl zif-8",
            collection="enzyme_immobilization_b10",
            embedding_model="hash-v1-64",
            top_k=2,
            usable_only=True,
            hits=[
                RetrievalHit(
                    score=0.9,
                    point_type="evidence_record",
                    source_id="ev_1",
                    citation="B10.pdf:p8",
                    record_type="table_comparison_row",
                    confidence="medium",
                    usable_for_ranking=True,
                    text="This study yield 93.4%",
                ),
                RetrievalHit(
                    score=0.8,
                    point_type="evidence_record",
                    source_id="ev_2",
                    citation="B10.pdf:p3",
                    record_type="formulation_condition",
                    confidence="medium",
                    usable_for_ranking=True,
                    text="pH 7.5",
                ),
            ],
        )

        evidence_ids, citations = resolve_evidence_refs(
            raw_ids=["1", "ev_2", "ev_fake"],
            raw_citations=["B10.pdf:p8", "fake.pdf:p1"],
            retrieval=retrieval,
        )

        self.assertEqual(evidence_ids, ["ev_1", "ev_2"])
        self.assertEqual(citations, ["B10.pdf:p8", "B10.pdf:p3"])


class GeneratorStreamTests(unittest.TestCase):
    def test_mock_generator_streams_content_and_finish_chunk(self) -> None:
        client = MockGeneratorClient()
        request = GenerationRequest(
            messages=[
                ChatMessage(role="system", content="You are a test assistant."),
                ChatMessage(role="user", content="Recommend an immobilization carrier for BCL."),
            ],
            model="mock-generator-v1",
            response_format="json_object",
        )

        chunks = list(client.stream_generate(request))

        self.assertGreater(len(chunks), 1)
        self.assertTrue(any(chunk.delta for chunk in chunks))
        self.assertEqual(chunks[-1].finish_reason, "stop")


class PdfRouteTests(unittest.TestCase):
    def test_resolve_pdf_file_accepts_known_pdf_name(self) -> None:
        path = resolve_pdf_file("B10.pdf")

        self.assertIsNotNone(path)
        assert path is not None
        self.assertEqual(path.name, "B10.pdf")

    def test_resolve_pdf_file_rejects_path_traversal(self) -> None:
        self.assertIsNone(resolve_pdf_file("../configs/local.yaml"))


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


if __name__ == "__main__":
    unittest.main()
