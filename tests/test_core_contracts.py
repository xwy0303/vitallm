from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from enzyme_recommender.rag.embedding import (
    HashEmbeddingConfig,
    HashEmbeddingModel,
    SentenceEmbeddingConfig,
    SentenceEmbeddingModel,
    is_meta_tensor_load_error,
)
from enzyme_recommender.rag.indexing import (
    POINT_SCHEMA_VERSION,
    build_collection_name,
    build_index_identity,
    build_index_version as build_rag_index_version,
    embedding_identity_slug,
    resolve_collection_name,
)
from enzyme_recommender.ingestion.pipeline import build_index_version, extract_zip_safe
from enzyme_recommender.ingestion.registry import IngestionRegistry, normalize_pdf_filename, safe_identifier
from enzyme_recommender.evidence.curation import append_curation_decision, rebuild_curated_evidence, summarize_curation
from enzyme_recommender.rag.qdrant import (
    PAYLOAD_INDEX_FIELDS,
    QdrantRestClient,
    build_index_points,
    citation,
    extract_collection_vector_size,
)
from enzyme_recommender.rag.documents import (
    DocumentCatalogItem,
    build_document_catalog_from_payloads,
    resolve_document_reference,
    resolve_document_reference_from_hits,
)
from enzyme_recommender.ingestion.qa import MinerUQAGateConfig, apply_qa_gate
from enzyme_recommender.rag.retrieval import (
    RetrievalHit,
    RetrievalResponse,
    apply_result_diversity,
    build_qdrant_filter,
    build_query_plan,
    is_paper_process_query,
    rerank_hits,
    rerank_document_hits,
)
from enzyme_recommender.generators import ChatMessage, GenerationRequest, MockGeneratorClient
from enzyme_recommender.generators.openai_compatible import OpenAICompatibleGeneratorClient
from enzyme_recommender.api.models import DashboardSummaryResponse
from enzyme_recommender.api.app import (
    build_evidence_preview,
    build_ingestion_summary,
    collect_artifact_stats,
    collect_source_pdf_stats,
    get_cached_dashboard_summary,
    resolve_pdf_file,
    runtime_with_collection,
    summarize_qdrant_payloads,
)
from enzyme_recommender.recommendation.enzyme import (
    EnzymeRecommendationRequest,
    PAPER_PROCESS_OBJECTIVE,
    RecommendationService,
    build_retrieval_query,
    build_stream_generation_prompt,
    is_paper_process_question,
    resolve_evidence_refs,
)
from enzyme_recommender.recommendation.formulation import FormulationOptimizationRequest, FormulationOptimizationService
from enzyme_recommender.runtime import RuntimeServices
from enzyme_recommender.runtime.config import RuntimeConfig
from scripts.run_ingestion_worker import document_is_indexed_for_collection, is_transient_service_error, should_skip_indexed_document
from scripts.benchmark_retrieval import evaluate_case, evaluate_hits, summarize_results
from scripts.benchmark_qa_system import (
    EndpointResult,
    collect_case_metrics,
    evaluate_acceptance_targets,
    evaluate_endpoint_result,
    load_manifest,
    match_expected_evidence,
    summarize_all,
    summarize_manifest_validation,
)
from scripts.ensure_qdrant_payload_indexes import build_summary as build_payload_index_summary
from scripts.queue_pdf_fallback_ingestion import queue_fallback_ingestion
from scripts.repair_failed_mineru_pdfs import page_count_delta
from scripts.register_pdf_corpus import register_pdf_corpus, select_pdf_paths
from scripts.export_manual_review_package import (
    STUDENT_ALLOWED_CONTENT_TYPES,
    STUDENT_REVIEW_COLUMNS,
    build_student_review_rows,
)
from scripts.import_student_review_csv import import_student_reviews


class RuntimeConfigTests(unittest.TestCase):
    def test_embedding_local_files_only_is_loaded_from_yaml(self) -> None:
        config = RuntimeConfig.from_file(Path("configs/local.yaml"))

        self.assertEqual(config.embedding.provider, "sentence")
        self.assertEqual(
            config.vector_store.collection,
            "enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1",
        )
        self.assertEqual(config.embedding.dimensions, 768)
        self.assertTrue(config.embedding.local_files_only)

    def test_hash_rollback_config_is_available(self) -> None:
        config = RuntimeConfig.from_file(Path("configs/local.hash.yaml"))

        self.assertEqual(config.embedding.provider, "hash_v1")
        self.assertEqual(config.vector_store.collection, "enzyme_immobilization_literature")

    def test_runtime_reuses_embedding_model_instance(self) -> None:
        runtime = RuntimeServices(config=RuntimeConfig.from_file(Path("configs/local.yaml")))

        self.assertIs(runtime.embedding_model(), runtime.embedding_model())

    def test_meta_tensor_load_error_is_detected_for_embedding_fallback(self) -> None:
        error = RuntimeError("Cannot copy out of meta tensor; no data! Please use torch.nn.Module.to_empty()")

        self.assertTrue(is_meta_tensor_load_error(error))
        self.assertFalse(is_meta_tensor_load_error(RuntimeError("connection timeout")))


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

    def test_document_scope_filter_uses_existing_metadata_fields(self) -> None:
        query_filter = build_qdrant_filter(
            point_type="evidence_record",
            usable_only=False,
            record_type="formulation_condition",
            document_id="B10",
            source_pdf="B10.pdf",
        )

        self.assertEqual(
            query_filter,
            {
                "must": [
                    {"key": "point_type", "match": {"value": "evidence_record"}},
                    {"key": "record_type", "match": {"value": "formulation_condition"}},
                    {"key": "document_id", "match": {"value": "B10"}},
                    {"key": "source_pdf", "match": {"value": "B10.pdf"}},
                ]
            },
        )


class DocumentResolverTests(unittest.TestCase):
    def test_explicit_document_id_resolves_before_title_matching(self) -> None:
        catalog = [
            DocumentCatalogItem(document_id="A12", source_pdf="A12.pdf", title_candidate="Other title"),
            DocumentCatalogItem(document_id="B10", source_pdf="B10.pdf", title_candidate="BCL ZIF-8 biodiesel"),
        ]

        result = resolve_document_reference("B10论文对酶固定化剂的优化过程是怎么样的", catalog)

        self.assertEqual(result.status, "resolved")
        self.assertTrue(result.explicit)
        self.assertEqual(result.document.document_id if result.document else None, "B10")

    def test_title_match_resolves_when_single_candidate_is_strong(self) -> None:
        catalog = [
            DocumentCatalogItem(
                document_id="A1",
                source_pdf="A1.pdf",
                title_candidate="Immobilization of lipase on UiO-66 for esterification",
                aliases=["Immobilization of lipase on UiO-66 for esterification"],
            ),
            DocumentCatalogItem(
                document_id="B10",
                source_pdf="B10.pdf",
                title_candidate="BCL immobilized on ZIF-8 for soybean oil ethanol biodiesel",
                aliases=["BCL immobilized on ZIF-8 for soybean oil ethanol biodiesel"],
            ),
        ]

        result = resolve_document_reference("BCL immobilized on ZIF-8 soybean oil ethanol 这篇论文优化过程", catalog)

        self.assertEqual(result.status, "resolved")
        self.assertFalse(result.explicit)
        self.assertEqual(result.document.document_id if result.document else None, "B10")

    def test_title_match_reports_ambiguity_for_close_candidates(self) -> None:
        catalog = [
            DocumentCatalogItem(
                document_id="A1",
                source_pdf="A1.pdf",
                title_candidate="lipase immobilization on ZIF-8 carrier",
                aliases=["lipase immobilization on ZIF-8 carrier"],
            ),
            DocumentCatalogItem(
                document_id="A2",
                source_pdf="A2.pdf",
                title_candidate="lipase immobilization on ZIF-8 support",
                aliases=["lipase immobilization on ZIF-8 support"],
            ),
        ]

        result = resolve_document_reference("lipase ZIF-8 论文优化过程", catalog)

        self.assertEqual(result.status, "ambiguous")
        self.assertEqual({item.document_id for item in result.candidates}, {"A1", "A2"})

    def test_retrieval_hit_fallback_resolves_weak_title_catalog(self) -> None:
        catalog = [
            DocumentCatalogItem(document_id="A61", source_pdf="A61.pdf", title_candidate="Abstract: immobilized lipase"),
            DocumentCatalogItem(document_id="B10", source_pdf="B10.pdf", title_candidate="Abstract: hierarchical ZIF-8"),
        ]
        hits = [
            RetrievalHit(
                score=1.4,
                point_type="evidence_record",
                source_id="ev_b10_1",
                document_id="B10",
                source_pdf="B10.pdf",
                record_type="immobilization_strategy",
                text="BCL immobilized on ZIF-8 for soybean oil ethanol biodiesel.",
            ),
            RetrievalHit(
                score=1.2,
                point_type="evidence_record",
                source_id="ev_b10_2",
                document_id="B10",
                source_pdf="B10.pdf",
                record_type="table_comparison_row",
                text="B. cepacia lipase soybean oil ethanol biodiesel yield 93.4.",
            ),
            RetrievalHit(
                score=1.1,
                point_type="evidence_record",
                source_id="ev_a61",
                document_id="A61",
                source_pdf="A61.pdf",
                record_type="immobilization_strategy",
                text="CALB immobilization on MOF-199 for biodiesel.",
            ),
        ]

        result = resolve_document_reference_from_hits(
            "BCL immobilized on ZIF-8 soybean oil ethanol biodiesel 论文优化流程",
            catalog,
            hits,
        )

        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.document.document_id if result.document else None, "B10")

    def test_retrieval_hit_fallback_reports_ambiguity_for_close_documents(self) -> None:
        catalog = [
            DocumentCatalogItem(document_id="A1", source_pdf="A1.pdf"),
            DocumentCatalogItem(document_id="A2", source_pdf="A2.pdf"),
        ]
        hits = [
            RetrievalHit(
                score=1.2,
                point_type="evidence_record",
                source_id="ev_a1",
                document_id="A1",
                source_pdf="A1.pdf",
                text="lipase ZIF-8 biodiesel immobilization process",
            ),
            RetrievalHit(
                score=1.18,
                point_type="evidence_record",
                source_id="ev_a2",
                document_id="A2",
                source_pdf="A2.pdf",
                text="lipase ZIF-8 biodiesel immobilization process",
            ),
        ]

        result = resolve_document_reference_from_hits("lipase ZIF-8 biodiesel 论文优化流程", catalog, hits)

        self.assertEqual(result.status, "ambiguous")
        self.assertEqual({item.document_id for item in result.candidates[:2]}, {"A1", "A2"})

    def test_catalog_summary_counts_review_and_quality_flags(self) -> None:
        catalog = build_document_catalog_from_payloads(
            [
                {
                    "document_id": "B10",
                    "source_pdf": "B10.pdf",
                    "point_type": "rag_chunk",
                    "page_start": 0,
                    "section": "Title",
                    "text": "BCL immobilized on hierarchical ZIF-8 for biodiesel production",
                    "qa_status": "pass",
                },
                {
                    "document_id": "B10",
                    "source_pdf": "B10.pdf",
                    "point_type": "evidence_record",
                    "text": "bad table",
                    "requires_review": True,
                    "quality_flags": ["bad_table_structure"],
                },
            ]
        )

        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0].indexed_points, 2)
        self.assertIn("BCL immobilized", catalog[0].title_candidate or "")
        self.assertEqual(catalog[0].qa_summary["requires_review"], 1)
        self.assertEqual(catalog[0].qa_summary["quality_flags"]["bad_table_structure"], 1)


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
                extra_payload={
                    "ingestion_sha256": "abc123",
                    "index_version": "test_index",
                },
                index_version="test_index",
            )

        self.assertEqual(len(points), 2)
        self.assertTrue(all(len(point["vector"]) == 64 for point in points))
        self.assertEqual({point["payload"]["point_type"] for point in points}, {"rag_chunk", "evidence_record"})
        self.assertEqual({point["payload"]["citation"] for point in points}, {"B10.pdf:p1"})
        self.assertEqual({point["payload"]["ingestion_sha256"] for point in points}, {"abc123"})
        self.assertEqual({point["payload"]["index_version"] for point in points}, {"test_index"})
        self.assertEqual({point["payload"]["point_schema_version"] for point in points}, {POINT_SCHEMA_VERSION})

    def test_build_index_points_includes_curated_evidence_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rag_dir = root / "rag"
            evidence_dir = root / "evidence"
            rag_dir.mkdir()
            evidence_dir.mkdir()
            write_jsonl(rag_dir / "rag_chunks.jsonl", [])
            write_jsonl(rag_dir / "table_records.jsonl", [])
            write_jsonl(evidence_dir / "evidence_records.jsonl", [])
            write_jsonl(
                evidence_dir / "curated_evidence_records.jsonl",
                [
                    {
                        "evidence_id": "cur_1",
                        "source_evidence_id": "ev_1",
                        "record_type": "performance_metric",
                        "candidate_source": "curated_evidence",
                        "document_id": "B10",
                        "source_pdf": "B10.pdf",
                        "source_id": "ev_1",
                        "page_start": 0,
                        "page_end": 0,
                        "section": "Abstract",
                        "evidence_span": "Biodiesel yield 93.4%",
                        "extracted": {},
                        "metrics": [{"name": "biodiesel_yield", "value": 93.4, "unit": "%"}],
                        "quality_flags": ["suspicious_percent_gt_300"],
                        "review_reasons": [],
                        "requires_review": False,
                        "usable_for_ranking": True,
                        "confidence": "high",
                        "curation_status": "edit",
                    }
                ],
            )

            points = build_index_points(
                rag_input_dir=rag_dir,
                evidence_dir=evidence_dir,
                embedding_model=HashEmbeddingModel(HashEmbeddingConfig(dimensions=64)),
            )

        self.assertEqual(len(points), 1)
        payload = points[0]["payload"]
        self.assertEqual(payload["source_id"], "cur_1")
        self.assertEqual(payload["source_evidence_id"], "ev_1")
        self.assertEqual(payload["candidate_source"], "curated_evidence")
        self.assertTrue(payload["usable_for_ranking"])
        self.assertFalse(payload["requires_review"])

    def test_build_index_version_uses_embedding_model_identity(self) -> None:
        model = HashEmbeddingModel(HashEmbeddingConfig(dimensions=64))

        self.assertIn("hash_v1_64", build_index_version(model))
        self.assertEqual(build_index_version(model), build_rag_index_version(model))


class IndexIdentityTests(unittest.TestCase):
    def test_collection_name_is_stable_for_hash_embedding(self) -> None:
        model = HashEmbeddingModel(HashEmbeddingConfig(dimensions=768))

        self.assertEqual(embedding_identity_slug(model), "hash_v1_768")
        self.assertEqual(
            build_collection_name(model),
            "enzyme_immobilization_literature_hash_v1_768_point_schema_v1",
        )

    def test_collection_name_includes_sentence_model_identity(self) -> None:
        model = SentenceEmbeddingModel(
            SentenceEmbeddingConfig(
                model_name="BAAI/bge-base-en-v1.5",
                dimensions=768,
                local_files_only=True,
            )
        )

        self.assertEqual(
            build_collection_name(model),
            "enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1",
        )
        self.assertIn(POINT_SCHEMA_VERSION, build_rag_index_version(model))

    def test_auto_collection_resolves_to_embedding_identity(self) -> None:
        model = HashEmbeddingModel(HashEmbeddingConfig(dimensions=64))
        expected = "enzyme_immobilization_literature_hash_v1_64_point_schema_v1"

        self.assertEqual(resolve_collection_name(model, collection=None), expected)
        self.assertEqual(resolve_collection_name(model, collection="auto"), expected)
        self.assertEqual(build_index_identity(model, collection="auto").collection, expected)

    def test_explicit_collection_is_preserved(self) -> None:
        model = HashEmbeddingModel(HashEmbeddingConfig(dimensions=64))

        self.assertEqual(resolve_collection_name(model, collection=" live_collection "), "live_collection")
        self.assertEqual(build_index_identity(model, collection="live_collection").collection, "live_collection")


class IngestionRegistryTests(unittest.TestCase):
    def test_normalize_pdf_filename_and_safe_identifier(self) -> None:
        self.assertEqual(normalize_pdf_filename(" ../A 1 "), "A 1.pdf")
        self.assertEqual(safe_identifier(" A 1 / weird:name "), "A_1_weird_name")

    def test_register_pdf_path_is_idempotent_by_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf_path = root / "A1.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%test\n")
            registry = IngestionRegistry(root / "artifacts")

            with patch("enzyme_recommender.ingestion.registry.count_pdf_pages_or_raise", return_value=3):
                first = registry.register_pdf_path(pdf_path, uploaded_by="test")
                second = registry.register_pdf_path(pdf_path, uploaded_by="test")

            self.assertFalse(first.duplicate)
            self.assertTrue(second.duplicate)
            self.assertEqual(first.document.document_id, second.document.document_id)
            self.assertEqual(len(registry.load_documents()), 1)
            self.assertEqual(registry.get_document(first.document.document_id).current_status, "deduplicated")

    def test_create_batch_and_job_records_latest_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf_path = root / "A1.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%test\n")
            registry = IngestionRegistry(root / "artifacts")

            with patch("enzyme_recommender.ingestion.registry.count_pdf_pages_or_raise", return_value=3):
                registered = registry.register_pdf_path(pdf_path, uploaded_by="test")
            batch = registry.create_batch([registered], uploaded_by="test")
            document = registry.get_document(registered.document.document_id)
            assert document is not None
            job = registry.create_job(document)
            updated = registry.update_job(job, status="running", metadata={"stage_note": "ok"})
            updated = registry.update_job(updated, stage="rag_build", status="failed", error_code="x")

            self.assertIn(document.document_id, batch.document_ids)
            self.assertEqual(updated.stage, "rag_build")
            self.assertEqual(updated.status, "failed")
            self.assertEqual(updated.metadata["stage_note"], "ok")

    def test_select_pdf_paths_accepts_stem_and_trims_filename_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf_dir = root / "pdfs"
            pdf_dir.mkdir()
            (pdf_dir / "C6 .pdf").write_bytes(b"%PDF-1.4\n%test\n")
            (pdf_dir / "B1.pdf").write_bytes(b"%PDF-1.4\n%test\n")

            selected = select_pdf_paths(pdf_dir, ["C6", "B1.pdf", "C6 .pdf"])

        self.assertEqual([path.name for path in selected], ["C6 .pdf", "B1.pdf"])

    def test_register_pdf_corpus_avoids_duplicate_active_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf_path = root / "A1.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%test\n")
            artifact_root = root / "artifacts"

            with patch("enzyme_recommender.ingestion.registry.count_pdf_pages_or_raise", return_value=3):
                first = register_pdf_corpus([pdf_path], artifact_root, uploaded_by="test", queue_jobs=True)
                second = register_pdf_corpus([pdf_path], artifact_root, uploaded_by="test", queue_jobs=True)

        self.assertEqual(first.jobs_created, 1)
        self.assertEqual(second.jobs_created, 0)
        self.assertEqual(second.active_jobs_skipped, 1)

    def test_register_pdf_corpus_requeues_terminal_doc_for_new_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf_path = root / "A1.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%test\n")
            artifact_root = root / "artifacts"
            registry = IngestionRegistry(artifact_root)

            with patch("enzyme_recommender.ingestion.registry.count_pdf_pages_or_raise", return_value=3):
                registered = registry.register_pdf_path(pdf_path, uploaded_by="test")
            document = registry.get_document(registered.document.document_id)
            assert document is not None
            registry.update_document(document, status="searchable", active_collection="old_collection")

            with patch("enzyme_recommender.ingestion.registry.count_pdf_pages_or_raise", return_value=3):
                same_collection = register_pdf_corpus(
                    [pdf_path],
                    artifact_root,
                    uploaded_by="test",
                    queue_jobs=True,
                    target_collection="old_collection",
                )
                new_collection = register_pdf_corpus(
                    [pdf_path],
                    artifact_root,
                    uploaded_by="test",
                    queue_jobs=True,
                    target_collection="new_collection",
                )

        self.assertEqual(same_collection.jobs_created, 0)
        self.assertEqual(new_collection.jobs_created, 1)

    def test_worker_skip_requires_terminal_status_and_matching_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf_path = root / "A1.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%test\n")
            registry = IngestionRegistry(root / "artifacts")

            with patch("enzyme_recommender.ingestion.registry.count_pdf_pages_or_raise", return_value=3):
                registered = registry.register_pdf_path(pdf_path, uploaded_by="test")
            document = registry.get_document(registered.document.document_id)
            assert document is not None

            document = registry.update_document(
                document,
                status="searchable",
                active_collection="enzyme_immobilization_literature",
            )

            self.assertTrue(document_is_indexed_for_collection(document, "enzyme_immobilization_literature"))
            self.assertTrue(should_skip_indexed_document(document, "enzyme_immobilization_literature"))
            self.assertFalse(
                should_skip_indexed_document(
                    document,
                    "enzyme_immobilization_literature",
                    reindex_only=True,
                )
            )
            self.assertFalse(
                should_skip_indexed_document(
                    document,
                    "enzyme_immobilization_literature",
                    delete_existing_points=True,
                )
            )
            self.assertFalse(document_is_indexed_for_collection(document, "enzyme_immobilization_b10"))
            document = registry.update_document(document, status="indexed")
            self.assertFalse(document_is_indexed_for_collection(document, "enzyme_immobilization_literature"))

    def test_worker_treats_local_service_outage_as_transient(self) -> None:
        self.assertTrue(is_transient_service_error(RuntimeError("[Errno 61] Connection refused")))
        self.assertTrue(is_transient_service_error(RuntimeError("cannot connect to Qdrant at http://127.0.0.1:6333")))
        self.assertFalse(is_transient_service_error(RuntimeError("cannot find *_content_list.json under artifacts")))

    def test_build_ingestion_summary_counts_latest_documents_and_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf_path = root / "A1.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n%test\n")
            registry = IngestionRegistry(root / "artifacts")

            with patch("enzyme_recommender.ingestion.registry.count_pdf_pages_or_raise", return_value=3):
                registered = registry.register_pdf_path(pdf_path, uploaded_by="test")
            document = registry.get_document(registered.document.document_id)
            assert document is not None
            registry.update_document(document, status="searchable")
            registry.create_job(document)

            summary = build_ingestion_summary(registry)

            self.assertEqual(summary.total_documents, 1)
            self.assertEqual(summary.searchable_documents, 1)
            self.assertEqual(summary.queued_jobs, 1)

    def test_queue_fallback_ingestion_preserves_original_document_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_root = root / "artifacts"
            pdf_path = root / "A34.pdf"
            fallback_dir = artifact_root / "pdf_raster_fallback" / "A34"
            fallback_pdf = fallback_dir / "A34.raster-ocr.pdf"
            fallback_dir.mkdir(parents=True)
            pdf_path.write_bytes(b"%PDF-1.4\n%test\n")
            fallback_pdf.write_bytes(b"%PDF-1.4\n%fallback\n")
            registry = IngestionRegistry(artifact_root)

            with patch("enzyme_recommender.ingestion.registry.count_pdf_pages_or_raise", return_value=7):
                registered = registry.register_pdf_path(pdf_path, uploaded_by="test")
            document = registry.get_document(registered.document.document_id)
            assert document is not None
            registry.update_document(document, status="failed_mineru", last_error_code="failed_mineru")
            (fallback_dir / "fallback_manifest.json").write_text(
                json.dumps(
                    {
                        "document_id": document.document_id,
                        "status": "fallback_ready_with_placeholders",
                        "expected_pages": 10,
                        "final_pdfinfo_pages": 10,
                        "final_pdfium_render": {"bad_pages": []},
                        "final_pdf_path": str(fallback_pdf),
                        "placeholder_pages": [8, 9, 10],
                    }
                ),
                encoding="utf-8",
            )

            summary = queue_fallback_ingestion(artifact_root, ["A34"], queue_jobs=True)
            updated = registry.get_document("A34")

        assert updated is not None
        self.assertEqual(summary["documents_updated"], 1)
        self.assertEqual(summary["jobs_created"], 1)
        self.assertEqual(updated.document_id, "A34")
        self.assertEqual(updated.source_pdf, "A34.pdf")
        self.assertEqual(Path(updated.raw_pdf_path).name, "A34.raster-ocr.pdf")
        self.assertEqual(updated.current_status, "deduplicated")
        self.assertEqual(updated.page_count, 10)


class EvidenceCurationTests(unittest.TestCase):
    def test_curation_accept_builds_ranking_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_dir = Path(temp_dir) / "evidence" / "B10"
            evidence_dir.mkdir(parents=True)
            write_jsonl(
                evidence_dir / "evidence_records.jsonl",
                [
                    {
                        "evidence_id": "ev_1",
                        "record_type": "performance_metric",
                        "candidate_source": "rag_chunk",
                        "document_id": "B10",
                        "source_pdf": "B10.pdf",
                        "source_id": "B10_chunk_1",
                        "page_start": 0,
                        "page_end": 0,
                        "evidence_span": "Biodiesel yield 93.4%",
                        "extracted": {},
                        "metrics": [{"name": "biodiesel_yield", "value": 93.4, "unit": "%"}],
                        "quality_flags": [],
                        "review_reasons": ["manual_review"],
                        "requires_review": True,
                        "usable_for_ranking": False,
                        "confidence": "low",
                    }
                ],
            )

            append_curation_decision(evidence_dir, "ev_1", "accept", "tester", "verified against PDF")
            curated = rebuild_curated_evidence(evidence_dir)
            summary = summarize_curation(Path(temp_dir) / "evidence")

        self.assertEqual(len(curated), 1)
        self.assertEqual(curated[0]["source_evidence_id"], "ev_1")
        self.assertTrue(curated[0]["usable_for_ranking"])
        self.assertFalse(curated[0]["requires_review"])
        self.assertEqual(summary["curated_records"], 1)

    def test_curation_reject_removes_from_curated_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_dir = Path(temp_dir) / "evidence" / "B10"
            evidence_dir.mkdir(parents=True)
            write_jsonl(
                evidence_dir / "evidence_records.jsonl",
                [
                    {
                        "evidence_id": "ev_bad",
                        "record_type": "table_comparison_row",
                        "document_id": "B10",
                        "source_pdf": "B10.pdf",
                        "source_id": "B10_table_1",
                        "evidence_span": "bad row",
                        "extracted": {},
                        "metrics": [],
                        "quality_flags": ["bad_table_structure"],
                        "review_reasons": ["upstream_quality_flags"],
                        "requires_review": True,
                    }
                ],
            )

            append_curation_decision(evidence_dir, "ev_bad", "reject", "tester", "bad table")
            curated = rebuild_curated_evidence(evidence_dir)

        self.assertEqual(curated, [])


class StudentReviewWorkflowTests(unittest.TestCase):
    def test_student_review_export_uses_chinese_columns_and_mapping(self) -> None:
        evidence_items = [
            {
                "priority": "P1",
                "document_id": "A11",
                "source_pdf": "A11.pdf",
                "page_start_1based": "5",
                "page_end_1based": "5",
                "record_type": "table_comparison_row",
                "evidence_id": "ev_table",
                "source_id": "A11_p4_t85",
                "table_id": "A11_p4_t85",
                "section": "3.1. Material characterization",
                "quality_flags": "missing_enzyme_cell",
                "qa_flags": "",
                "review_task": "回到 PDF 表格确认该行 enzyme 是否能由表头/caption/相邻行唯一确定。",
                "evidence_span": "MOFs: ZIF-8(Zn); Recovery activity (%): 67.4",
                "extracted_json": json.dumps({"table_id": "A11_p4_t85", "row_index": 1}),
                "metrics_json": "[]",
            },
            {
                "priority": "P2",
                "document_id": "A12",
                "source_pdf": "A12.pdf",
                "page_start_1based": "3",
                "page_end_1based": "3",
                "record_type": "formulation_condition",
                "evidence_id": "ev_condition",
                "source_id": "A12_chunk_0014",
                "section": "Preparation of Cu-BTC",
                "quality_flags": "possible_ocr_duplicate_text",
                "qa_flags": "",
                "review_task": "检查是否重复 OCR 但事实仍正确。",
                "evidence_span": "potassium phosphate buffer pH 8.5",
                "extracted_json": json.dumps({"pH": 8.5}),
                "metrics_json": "[]",
            },
        ]

        student_rows, mapping_rows = build_student_review_rows(evidence_items)

        self.assertEqual(len(student_rows), 2)
        self.assertEqual(len(mapping_rows), 2)
        self.assertEqual(set(student_rows[0]), set(STUDENT_REVIEW_COLUMNS))
        self.assertEqual(len({row["任务编号"] for row in student_rows}), 2)
        self.assertEqual({row["task_id"] for row in mapping_rows}, {row["任务编号"] for row in student_rows})
        self.assertTrue({row["内容类型"] for row in student_rows} <= STUDENT_ALLOWED_CONTENT_TYPES)
        self.assertEqual(student_rows[0]["内容类型"], "表格数据")
        self.assertIn("表格行缺少酶/蛋白名称", student_rows[0]["风险提示"])

    def test_student_review_import_converts_chinese_decisions_to_curation_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_root = root / "artifacts"
            evidence_dir = artifact_root / "evidence" / "A11"
            evidence_dir.mkdir(parents=True)
            source_records = [
                {
                    "evidence_id": "ev_accept",
                    "record_type": "immobilization_strategy",
                    "document_id": "A11",
                    "source_pdf": "A11.pdf",
                    "source_id": "A11_chunk_1",
                    "page_start": 0,
                    "page_end": 0,
                    "evidence_span": "Lipase immobilized on ZIF-8.",
                    "extracted": {"carrier": "ZIF-8"},
                    "metrics": [],
                    "quality_flags": ["possible_ocr_duplicate_text"],
                    "review_reasons": ["upstream_quality_flags"],
                    "requires_review": True,
                },
                {
                    "evidence_id": "ev_edit",
                    "record_type": "table_comparison_row",
                    "document_id": "A11",
                    "source_pdf": "A11.pdf",
                    "source_id": "A11_table_1",
                    "page_start": 1,
                    "page_end": 1,
                    "evidence_span": "Yield 900%",
                    "extracted": {"carrier": "ZIF-8"},
                    "metrics": [{"name": "biodiesel_yield", "value": 900, "unit": "%"}],
                    "quality_flags": ["suspicious_table_yield_gt_100"],
                    "review_reasons": ["metric_percent_gt_100"],
                    "requires_review": True,
                },
                {
                    "evidence_id": "ev_reject",
                    "record_type": "table_comparison_row",
                    "document_id": "A11",
                    "source_pdf": "A11.pdf",
                    "source_id": "A11_table_2",
                    "page_start": 2,
                    "page_end": 2,
                    "evidence_span": "bad row",
                    "extracted": {},
                    "metrics": [],
                    "quality_flags": ["missing_enzyme_cell"],
                    "review_reasons": ["upstream_quality_flags"],
                    "requires_review": True,
                },
            ]
            write_jsonl(evidence_dir / "evidence_records.jsonl", source_records)
            mapping_rows = [
                {
                    "task_id": "REV-A11-accept",
                    "document_id": "A11",
                    "evidence_id": "ev_accept",
                    "record_type": "immobilization_strategy",
                    "source_review_row": {
                        "extracted_json": json.dumps({"carrier": "ZIF-8"}),
                        "metrics_json": "[]",
                    },
                },
                {
                    "task_id": "REV-A11-edit",
                    "document_id": "A11",
                    "evidence_id": "ev_edit",
                    "record_type": "table_comparison_row",
                    "source_review_row": {
                        "extracted_json": json.dumps({"carrier": "ZIF-8"}),
                        "metrics_json": json.dumps([{"name": "biodiesel_yield", "value": 900, "unit": "%"}]),
                    },
                },
                {
                    "task_id": "REV-A11-reject",
                    "document_id": "A11",
                    "evidence_id": "ev_reject",
                    "record_type": "table_comparison_row",
                    "source_review_row": {"extracted_json": "{}", "metrics_json": "[]"},
                },
                {
                    "task_id": "REV-A11-uncertain",
                    "document_id": "A11",
                    "evidence_id": "ev_reject",
                    "record_type": "table_comparison_row",
                    "source_review_row": {"extracted_json": "{}", "metrics_json": "[]"},
                },
            ]
            write_jsonl(root / "mapping.jsonl", mapping_rows)
            student_rows = [
                make_student_csv_row("REV-A11-accept", "正确", reviewer="student1"),
                make_student_csv_row(
                    "REV-A11-edit",
                    "需修改",
                    reviewer="student1",
                    enzyme="CALB",
                    carrier="ZIF-8",
                    metric_name="biodiesel_yield",
                    metric_value="90.0",
                    metric_unit="%",
                    evidence_span="Corrected yield 90.0%",
                ),
                make_student_csv_row("REV-A11-reject", "错误", reviewer="student1", note="PDF table row cannot be verified"),
                make_student_csv_row("REV-A11-uncertain", "不确定", reviewer="student1"),
            ]
            write_csv(root / "student.csv", STUDENT_REVIEW_COLUMNS, student_rows)

            report = import_student_reviews(
                student_csv=root / "student.csv",
                mapping_path=root / "mapping.jsonl",
                artifact_root=artifact_root,
                output_dir=root,
                dry_run=False,
            )
            decisions = load_jsonl_for_test(evidence_dir / "curation_decisions.jsonl")
            curated = load_jsonl_for_test(evidence_dir / "curated_evidence_records.jsonl")
            uncertain = list(csv.DictReader((root / "student_review_uncertain_or_error.csv").open(encoding="utf-8-sig")))

        self.assertEqual(report["accepted"], 1)
        self.assertEqual(report["edited"], 1)
        self.assertEqual(report["rejected"], 1)
        self.assertEqual(report["uncertain"], 1)
        self.assertEqual(report["errors"], 0)
        self.assertEqual([decision["action"] for decision in decisions], ["accept", "edit", "reject"])
        edited = next(record for record in curated if record["source_evidence_id"] == "ev_edit")
        self.assertEqual(edited["extracted"]["enzyme_name"], "CALB")
        self.assertEqual(edited["extracted"]["carrier"], "ZIF-8")
        self.assertEqual(edited["metrics"][0]["value"], 90)
        self.assertTrue(edited["usable_for_ranking"])
        self.assertFalse(edited["requires_review"])
        self.assertEqual(len(uncertain), 1)

    def test_student_review_import_reports_invalid_rows_without_curation_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_root = root / "artifacts"
            evidence_dir = artifact_root / "evidence" / "A11"
            evidence_dir.mkdir(parents=True)
            write_jsonl(
                evidence_dir / "evidence_records.jsonl",
                [
                    {
                        "evidence_id": "ev_1",
                        "record_type": "performance_metric",
                        "document_id": "A11",
                        "source_pdf": "A11.pdf",
                        "source_id": "A11_chunk_1",
                        "evidence_span": "yield 90%",
                        "extracted": {},
                        "metrics": [],
                        "quality_flags": [],
                        "requires_review": True,
                    }
                ],
            )
            write_jsonl(
                root / "mapping.jsonl",
                [
                    {
                        "task_id": "REV-A11-1",
                        "document_id": "A11",
                        "evidence_id": "ev_1",
                        "record_type": "performance_metric",
                        "source_review_row": {"extracted_json": "{}", "metrics_json": "[]"},
                    }
                ],
            )
            rows = [
                make_student_csv_row("REV-A11-1", "需修改", reviewer="student1"),
                make_student_csv_row("REV-A11-missing", "正确", reviewer="student1"),
                make_student_csv_row("REV-A11-1", "错误", reviewer="student1"),
            ]
            write_csv(root / "student.csv", STUDENT_REVIEW_COLUMNS, rows)

            report = import_student_reviews(
                student_csv=root / "student.csv",
                mapping_path=root / "mapping.jsonl",
                artifact_root=artifact_root,
                output_dir=root,
                dry_run=False,
            )
            decisions_path = evidence_dir / "curation_decisions.jsonl"

        self.assertEqual(report["errors"], 3)
        self.assertFalse(decisions_path.exists())


class IngestionArtifactTests(unittest.TestCase):
    def test_extract_zip_safe_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            zip_path = root / "bad.zip"
            import zipfile

            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("../escape.txt", "bad")

            with self.assertRaises(ValueError):
                extract_zip_safe(zip_path, root / "out")

    def test_page_count_delta_marks_repair_page_loss(self) -> None:
        before = {"page_count": 10}
        after = {"page_count": 7}

        self.assertEqual(page_count_delta(before, after), -3)
        self.assertIsNone(page_count_delta(before, {"page_count": None}))


class QdrantClientTests(unittest.TestCase):
    def test_delete_points_by_filter_posts_filter_payload(self) -> None:
        class FakeResponse:
            status_code = 200
            text = "{}"

        client = QdrantRestClient.__new__(QdrantRestClient)
        client.config = type("Config", (), {"collection": "test"})()
        client.base_url = "http://qdrant"
        calls = []

        def fake_request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            return FakeResponse()

        client._request = fake_request  # type: ignore[method-assign]

        client.delete_points_by_filter({"must": [{"key": "document_id", "match": {"value": "A1"}}]})

        self.assertEqual(calls[0][0], "POST")
        self.assertEqual(calls[0][1], "/collections/test/points/delete")
        self.assertIn("filter", calls[0][2]["json"])

    def test_create_payload_index_posts_field_schema(self) -> None:
        class FakeResponse:
            status_code = 200
            text = "{}"

        client = QdrantRestClient.__new__(QdrantRestClient)
        client.config = type("Config", (), {"collection": "test"})()
        client.base_url = "http://qdrant"
        calls = []

        def fake_request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            return FakeResponse()

        client._request = fake_request  # type: ignore[method-assign]

        client.create_payload_index("document_id", "keyword")

        self.assertEqual(calls[0][0], "PUT")
        self.assertEqual(calls[0][1], "/collections/test/index")
        self.assertEqual(calls[0][2]["json"]["field_name"], "document_id")
        self.assertEqual(calls[0][2]["json"]["field_schema"], "keyword")

    def test_payload_index_summary_reports_expected_fields(self) -> None:
        summary = build_payload_index_summary("test", {}, {"document_id": {"data_type": "keyword"}})

        self.assertFalse(summary["all_present"])
        self.assertIn("document_id", PAYLOAD_INDEX_FIELDS)
        document_field = next(field for field in summary["fields"] if field["field_name"] == "document_id")
        self.assertTrue(document_field["present_after"])


class RetrievalBenchmarkTests(unittest.TestCase):
    def test_evaluate_hits_matches_expected_document_and_record_type(self) -> None:
        hits = [
            RetrievalHit(
                score=0.4,
                point_type="evidence_record",
                source_id="ev_other",
                document_id="A1",
                record_type="formulation_condition",
                text="pH 7.5",
            ),
            RetrievalHit(
                score=0.3,
                point_type="evidence_record",
                source_id="ev_b10",
                document_id="B10",
                record_type="table_comparison_row",
                text="yield 93.4%",
            ),
        ]

        score = evaluate_hits(hits, [{"document_id": "B10", "record_type": "table_comparison_row"}])
        summary = summarize_results("smoke", "test_collection", [{"id": "q1", "ok": score["ok"], "rank": score["rank"]}])

        self.assertTrue(score["ok"])
        self.assertEqual(score["rank"], 2)
        self.assertEqual(summary["passed"], 1)
        self.assertAlmostEqual(summary["mrr"], 0.5)

    def test_exclusion_case_fails_on_forbidden_quality_flag(self) -> None:
        hits = [
            RetrievalHit(
                score=0.8,
                point_type="evidence_record",
                source_id="ev_bad",
                document_id="A14",
                record_type="table_comparison_row",
                quality_flags=["missing_enzyme_cell"],
                requires_review=True,
                usable_for_ranking=True,
                text="Specific activity row from damaged table",
            )
        ]

        score = evaluate_case(
            hits,
            {
                "kind": "exclusion",
                "query": "A14 damaged table specific activity",
                "forbidden_any": [
                    {
                        "document_id": "A14",
                        "record_type": "table_comparison_row",
                        "quality_flags_any": ["missing_enzyme_cell"],
                    }
                ],
            },
        )

        self.assertFalse(score["ok"])
        self.assertFalse(score["forbidden_ok"])
        self.assertEqual(score["forbidden_hits"][0]["source_id"], "ev_bad")

    def test_negative_case_passes_when_forbidden_hit_is_absent(self) -> None:
        hits = [
            RetrievalHit(
                score=0.2,
                point_type="evidence_record",
                source_id="ev_other",
                document_id="B10",
                record_type="immobilization_strategy",
                text="BCL-ZIF-8 immobilization",
            )
        ]

        score = evaluate_case(
            hits,
            {
                "kind": "negative",
                "query": "CRISPR Cas9 graphene quantum dots",
                "expected_absent": [{"document_id": "A999"}],
            },
        )

        self.assertTrue(score["ok"])
        self.assertIsNone(score["rank"])


class QASystemBenchmarkTests(unittest.TestCase):
    def test_layered_manifests_load_with_target_counts(self) -> None:
        manifests = {
            "benchmarks/retrieval_quality_v1.json": 120,
            "benchmarks/answer_quality_v1.json": 50,
            "benchmarks/no_answer_intent_v1.json": 30,
            "benchmarks/formulation_optimizer_v1.json": 20,
        }

        for manifest_path, target_count in manifests.items():
            manifest = load_manifest(Path(manifest_path))

            self.assertEqual(manifest["target_case_count"], target_count)
            self.assertGreater(len(manifest["cases"]), 0)

    def test_formal_manifest_schema_artifact_is_present(self) -> None:
        schema = json.loads(Path("schemas/generated/qa_benchmark_manifest.schema.json").read_text(encoding="utf-8"))

        self.assertEqual(schema["title"], "Layered QA Benchmark Manifest")
        self.assertIn("case", schema["$defs"])
        self.assertIn("endpoint", schema["$defs"])

    def test_manifest_validation_summary_tracks_seed_coverage(self) -> None:
        manifests = [
            load_manifest(Path("benchmarks/retrieval_quality_v1.json")),
            load_manifest(Path("benchmarks/answer_quality_v1.json")),
            load_manifest(Path("benchmarks/no_answer_intent_v1.json")),
            load_manifest(Path("benchmarks/formulation_optimizer_v1.json")),
        ]

        summary = summarize_manifest_validation(manifests)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["target_case_count"], 220)
        self.assertGreater(summary["actual_case_count"], 0)
        self.assertIn("manual_user_like", summary["by_source"])
        self.assertIn("no_answer", summary["by_kind"])

    def test_match_expected_evidence_returns_rank_per_gold_item(self) -> None:
        hits = [
            RetrievalHit(
                score=0.9,
                point_type="evidence_record",
                source_id="ev_other",
                document_id="A1",
                record_type="immobilization_strategy",
                text="CALB immobilization on carrier.",
            ),
            RetrievalHit(
                score=0.8,
                point_type="evidence_record",
                source_id="ev_b10",
                document_id="B10",
                record_type="formulation_condition",
                text="BCL-ZIF-8 loading of 700 mg and adsorption time 30 min.",
            ),
            RetrievalHit(
                score=0.7,
                point_type="evidence_record",
                source_id="ev_magnetic",
                document_id="A18",
                record_type="performance_metric",
                text="Magnetic Fe3O4 MOF reuse after eight cycles.",
            ),
        ]

        ranks = match_expected_evidence(
            hits,
            [
                {"document_id": "B10", "text_contains": "ZIF-8"},
                {"text_contains_any": ["magnetic", "Fe3O4"]},
            ],
        )

        self.assertEqual(ranks, [2, 3])

    def test_no_answer_case_fails_on_unexpected_candidates_and_citations(self) -> None:
        endpoint_result = EndpointResult(
            endpoint="recommend_stream",
            generated_text="Recommended ZIF-8 carrier.",
            candidates=[{"name": "ZIF-8", "citations": ["B10.pdf:p8"]}],
            citations=["B10.pdf:p8"],
            next_experiment_suggestions=[{"step": "try ZIF-8"}],
        )
        case = {
            "kind": "no_answer",
            "expected_behavior": {
                "type": "no_answer",
                "max_evidence_hits": 0,
                "expect_no_candidates": True,
                "expect_no_citations": True,
                "expect_no_next_experiments": True,
            },
        }

        checks = evaluate_endpoint_result(endpoint_result, case)
        metrics = collect_case_metrics(endpoint_result, case, checks)

        self.assertFalse(checks["overall_ok"])
        self.assertFalse(checks["no_answer_ok"])
        self.assertTrue(metrics["unexpected_candidate"])
        self.assertTrue(metrics["unexpected_citation"])

    def test_no_answer_case_fails_on_forbidden_claims(self) -> None:
        endpoint_result = EndpointResult(
            endpoint="recommend_stream",
            generated_text="可以保证 100% 产率。",
        )
        case = {
            "kind": "no_answer",
            "forbidden_claims": ["100% 产率"],
            "expected_behavior": {
                "type": "no_answer",
                "max_evidence_hits": 0,
                "expect_no_candidates": True,
                "expect_no_citations": True,
                "expect_no_next_experiments": True,
            },
        }

        checks = evaluate_endpoint_result(endpoint_result, case)

        self.assertFalse(checks["overall_ok"])
        self.assertFalse(checks["forbidden_claims_ok"])

    def test_case_metrics_compute_recall_mrr_and_ndcg_windows(self) -> None:
        endpoint_result = EndpointResult(
            endpoint="search_evidence",
            evidence_hits=[
                RetrievalHit(
                    score=0.9,
                    point_type="evidence_record",
                    source_id="ev_1",
                    document_id="A1",
                    record_type="immobilization_strategy",
                    text="Unrelated immobilization strategy.",
                ),
                RetrievalHit(
                    score=0.8,
                    point_type="evidence_record",
                    source_id="ev_2",
                    document_id="A2",
                    record_type="performance_metric",
                    text="Unrelated performance metric.",
                ),
                RetrievalHit(
                    score=0.7,
                    point_type="evidence_record",
                    source_id="ev_3",
                    document_id="A3",
                    record_type="formulation_condition",
                    text="Unrelated formulation condition.",
                ),
                RetrievalHit(
                    score=0.6,
                    point_type="evidence_record",
                    source_id="ev_b10",
                    document_id="B10",
                    record_type="formulation_condition",
                    text="BCL-ZIF-8 loading of 700 mg and adsorption time 30 min.",
                ),
            ],
        )
        case = {
            "kind": "positive",
            "expected_evidence": [{"document_id": "B10", "text_contains": "700 mg"}],
        }

        checks = evaluate_endpoint_result(endpoint_result, case)
        metrics = collect_case_metrics(endpoint_result, case, checks)

        self.assertTrue(checks["overall_ok"])
        self.assertEqual(metrics["first_expected_rank"], 4)
        self.assertFalse(metrics["recall_at_3"])
        self.assertTrue(metrics["recall_at_5"])
        self.assertAlmostEqual(metrics["mrr_at_5"], 0.25)
        self.assertGreater(metrics["ndcg_at_5"], 0.0)

    def test_summarize_all_groups_by_kind_endpoint_and_difficulty(self) -> None:
        runtime = runtime_with_config()
        case_results = [
            {
                "benchmark": "unit",
                "id": "c1",
                "kind": "positive",
                "difficulty": "medium",
                "endpoint": "search_evidence",
                "query": "BCL-ZIF-8",
                "ok": True,
                "checks": {"plan_ok": True},
                "metrics": {
                    "has_expected_evidence": True,
                    "recall_at_3": True,
                    "recall_at_5": True,
                    "recall_at_8": True,
                    "mrr_at_3": 1.0,
                    "mrr_at_5": 1.0,
                    "mrr_at_8": 1.0,
                    "ndcg_at_5": 1.0,
                    "forbidden_hit_count": 0,
                },
                "actual": {},
            }
        ]

        summary = summarize_all(
            [{"name": "unit", "_path": "benchmarks/unit.json", "target_case_count": 1, "cases": [{"id": "c1"}]}],
            case_results,
            runtime,
            "mock",
            datetime.now(timezone.utc),
        )

        self.assertTrue(summary["all_passed"])
        self.assertEqual(summary["by_kind"]["positive"]["passed"], 1)
        self.assertEqual(summary["by_endpoint"]["search_evidence"]["passed"], 1)
        self.assertEqual(summary["by_difficulty"]["medium"]["passed"], 1)
        self.assertEqual(summary["metrics"]["retrieval"]["recall_at_5"], 1.0)
        self.assertIn("acceptance", summary)

    def test_acceptance_targets_flag_threshold_failures(self) -> None:
        acceptance = evaluate_acceptance_targets(
            {
                "retrieval": {
                    "cases": 1,
                    "recall_at_5": 0.94,
                    "mrr_at_5": 0.86,
                    "forbidden_hit_rate": 0.0,
                },
                "no_answer": {
                    "cases": 1,
                    "no_answer_accuracy": 1.0,
                    "unexpected_candidate_rate": 0.0,
                    "unexpected_citation_rate": 0.0,
                },
                "answer_quality": {
                    "cases": 1,
                    "citation_accuracy": 0.91,
                    "unsupported_claim_count_per_answer": 0.0,
                    "condition_type_accuracy": 1.0,
                    "stream_final_consistency": 1.0,
                },
                "formulation": {
                    "cases": 1,
                    "evidence_backed_change_rate": 1.0,
                    "unsafe_global_optimum_claim_count": 0,
                },
            }
        )

        self.assertFalse(acceptance["all_targets_met"])
        failed = [item for item in acceptance["checks"] if not item["ok"]]
        self.assertEqual(failed[0]["metric"], "recall_at_5")

    def test_acceptance_targets_skip_empty_metric_groups(self) -> None:
        acceptance = evaluate_acceptance_targets(
            {
                "retrieval": {
                    "cases": 1,
                    "recall_at_5": 1.0,
                    "mrr_at_5": 1.0,
                    "forbidden_hit_rate": 0.0,
                },
                "no_answer": {"cases": 0},
                "answer_quality": {"cases": 0},
                "formulation": {"cases": 0},
            }
        )

        skipped = [item for item in acceptance["checks"] if item.get("skipped")]
        self.assertTrue(skipped)
        self.assertTrue(all(item["ok"] for item in skipped))


class RetrievalPlanningTests(unittest.TestCase):
    def test_query_plan_routes_formulation_conditions(self) -> None:
        plan = build_query_plan("BCL-ZIF-8 loading 700 mg adsorption time 30 min pH 7.5", top_k=8)

        self.assertIn("condition", plan.intents)
        self.assertIn("strategy", plan.intents)
        self.assertIn("formulation_condition", plan.record_type_priorities)
        self.assertTrue(any(route.record_type == "formulation_condition" for route in plan.routes))

    def test_rerank_prefers_record_type_matching_query_intent(self) -> None:
        plan = build_query_plan("BCL loading 700 mg adsorption time 30 min pH 7.5", top_k=2)
        hits = [
            RetrievalHit(
                score=0.91,
                vector_score=0.91,
                point_type="evidence_record",
                source_id="ev_enzyme",
                record_type="enzyme_identity",
                text="Burkholderia cepacia lipase BCL enzyme identity.",
            ),
            RetrievalHit(
                score=0.90,
                vector_score=0.90,
                point_type="evidence_record",
                source_id="ev_condition",
                record_type="formulation_condition",
                text="BCL-ZIF-8 loading of 700 mg, adsorption time 30 min, pH value 7.5.",
            ),
        ]

        reranked = rerank_hits(plan.query_tokens and " ".join(plan.query_tokens) or "", hits, plan)

        self.assertEqual(reranked[0].source_id, "ev_condition")

    def test_rerank_promotes_exact_numeric_material_match(self) -> None:
        plan = build_query_plan("BCL-ZIF-8 loading 700 mg adsorption time 30 min pH 7.5", top_k=2)
        hits = [
            RetrievalHit(
                score=0.86,
                vector_score=0.86,
                point_type="evidence_record",
                source_id="ev_near",
                record_type="formulation_condition",
                text="BCL-ZIF-8 loading of 500 mg, adsorption time 15 min, pH value 8.0.",
            ),
            RetrievalHit(
                score=0.82,
                vector_score=0.82,
                point_type="evidence_record",
                source_id="ev_exact",
                record_type="formulation_condition",
                text="BCL-ZIF-8 loading of 700 mg, adsorption time 30 min, pH value 7.5.",
            ),
        ]

        reranked = rerank_hits("BCL-ZIF-8 loading 700 mg adsorption time 30 min pH 7.5", hits, plan)

        self.assertEqual(reranked[0].source_id, "ev_exact")
        self.assertGreater(reranked[0].lexical_score or 0.0, reranked[1].lexical_score or 0.0)

    def test_rerank_promotes_ocr_split_rare_material_match(self) -> None:
        query = "lipase@NKMOF-101-Mn 2-fold higher activity than lipase@ZIF-8 3-fold higher than MCM-41 hexane"
        plan = build_query_plan(query, top_k=2)
        hits = [
            RetrievalHit(
                score=0.86,
                vector_score=0.86,
                point_type="evidence_record",
                source_id="ev_generic_zif8",
                record_type="immobilization_strategy",
                text="Lipase@ZIF-8 showed higher activity in hexane and was compared with MCM-41.",
            ),
            RetrievalHit(
                score=0.82,
                vector_score=0.82,
                point_type="evidence_record",
                source_id="ev_nkmof_mn",
                record_type="immobilization_strategy",
                text=(
                    "Hydrophobicity of NKMOF-101s in n-hexane led to superior catalytic activity. "
                    "Lipa se@NKMOF-101-Mn maintained activity after reuse."
                ),
            ),
        ]

        reranked = rerank_hits(query, hits, plan)

        self.assertEqual(reranked[0].source_id, "ev_nkmof_mn")
        self.assertGreater(reranked[0].lexical_score or 0.0, reranked[1].lexical_score or 0.0)

    def test_rerank_normalizes_number_words_for_reuse_queries(self) -> None:
        plan = build_query_plan("MOF immobilized lipase reusability ten cycles", top_k=2)
        hits = [
            RetrievalHit(
                score=0.86,
                vector_score=0.86,
                point_type="evidence_record",
                source_id="ev_eight",
                record_type="performance_metric",
                text="Immobilized lipase retained activity after eight cycles.",
            ),
            RetrievalHit(
                score=0.82,
                vector_score=0.82,
                point_type="evidence_record",
                source_id="ev_ten",
                record_type="performance_metric",
                text="MOF immobilized lipase reusability after 10 cycles.",
            ),
        ]

        reranked = rerank_hits("MOF immobilized lipase reusability ten cycles", hits, plan)

        self.assertEqual(reranked[0].source_id, "ev_ten")

    def test_rerank_diversifies_repeated_rows_from_same_table(self) -> None:
        plan = build_query_plan("best ZIF-8 lipase biodiesel reuse cycles", top_k=4)
        hits = [
            RetrievalHit(
                score=0.91,
                vector_score=0.91,
                point_type="evidence_record",
                source_id="ev_table_1",
                parent_source_id="A35_p5_t79",
                document_id="A35",
                record_type="table_comparison_row",
                text="Enzyme: Gklip@ZIF-8; Biodiesel yield (%): 32.6",
            ),
            RetrievalHit(
                score=0.90,
                vector_score=0.90,
                point_type="evidence_record",
                source_id="ev_table_2",
                parent_source_id="A35_p5_t79",
                document_id="A35",
                record_type="table_comparison_row",
                text="Enzyme: Gklip@ZIF-8; Biodiesel yield (%): 28.3",
            ),
            RetrievalHit(
                score=0.89,
                vector_score=0.89,
                point_type="evidence_record",
                source_id="ev_table_3",
                parent_source_id="A35_p5_t79",
                document_id="A35",
                record_type="table_comparison_row",
                text="Enzyme: Gklip@ZIF-8; Biodiesel yield (%): 64.9",
            ),
            RetrievalHit(
                score=0.88,
                vector_score=0.88,
                point_type="evidence_record",
                source_id="ev_b10",
                parent_source_id="B10_p8_t82",
                document_id="B10",
                record_type="table_comparison_row",
                text="BCL-ZIF-8 biodiesel production and reuse cycles.",
            ),
        ]

        reranked = rerank_hits("best ZIF-8 lipase biodiesel reuse cycles", hits, plan)

        self.assertEqual(reranked[0].source_id, "ev_table_1")
        self.assertIn("ev_b10", [hit.source_id for hit in reranked[:3]])

    def test_paper_process_intent_promotes_formulation_conditions(self) -> None:
        plan = build_query_plan("B10论文对酶固定化剂的优化过程是怎么样的", top_k=4)
        hits = [
            RetrievalHit(
                score=0.95,
                vector_score=0.95,
                point_type="evidence_record",
                source_id="ev_table",
                document_id="B10",
                source_pdf="B10.pdf",
                page_start=8,
                record_type="table_comparison_row",
                text="BCL-ZIF-8 biodiesel yield 93.4%",
            ),
            RetrievalHit(
                score=0.82,
                vector_score=0.82,
                point_type="evidence_record",
                source_id="ev_condition",
                document_id="B10",
                source_pdf="B10.pdf",
                page_start=5,
                record_type="formulation_condition",
                text="BCL-ZIF-8 loading 700 mg adsorption time 30 min pH 7.5 temperature 25 C.",
            ),
        ]

        reranked = rerank_document_hits("B10论文对酶固定化剂的优化过程是怎么样的", hits, plan)

        self.assertEqual(reranked[0].source_id, "ev_condition")
        self.assertIn("paper", plan.intents)
        self.assertIn("process", plan.intents)

    def test_document_rerank_keeps_performance_and_table_context_in_top_k(self) -> None:
        plan = build_query_plan("B10 paper optimization process reusability biodiesel 8 cycles 93.4", top_k=12)
        hits = [
            *[
                RetrievalHit(
                    score=0.90 - index * 0.01,
                    vector_score=0.90 - index * 0.01,
                    point_type="evidence_record",
                    source_id=f"ev_condition_{index}",
                    document_id="B10",
                    source_pdf="B10.pdf",
                    page_start=5 + index,
                    record_type="formulation_condition",
                    text=f"BCL-ZIF-8 formulation condition {index}",
                )
                for index in range(8)
            ],
            RetrievalHit(
                score=0.70,
                vector_score=0.70,
                point_type="evidence_record",
                source_id="ev_performance",
                document_id="B10",
                source_pdf="B10.pdf",
                page_start=8,
                record_type="performance_metric",
                text="BCL-ZIF-8 reusability 8 cycles with last yield 71.3%.",
                metrics=[{"name": "reuse_cycles", "value": 8, "unit": "cycle"}],
            ),
            RetrievalHit(
                score=0.68,
                vector_score=0.68,
                point_type="evidence_record",
                source_id="ev_table",
                document_id="B10",
                source_pdf="B10.pdf",
                page_start=9,
                record_type="table_comparison_row",
                text="B. cepacia lipase soybean oil ethanol yield 93.4 and 8 cycles.",
                metrics=[{"name": "biodiesel_yield", "value": 93.4, "unit": "%"}],
            ),
        ]

        reranked = rerank_document_hits(
            "B10 paper optimization process reusability biodiesel 8 cycles 93.4",
            hits,
            plan,
            top_k=6,
        )

        self.assertIn("ev_performance", [hit.source_id for hit in reranked])
        self.assertIn("ev_table", [hit.source_id for hit in reranked])

    def test_document_rerank_keeps_review_evidence_behind_usable_evidence(self) -> None:
        plan = build_query_plan("B10论文对酶固定化剂的优化过程是怎么样的", top_k=4)
        hits = [
            RetrievalHit(
                score=0.95,
                vector_score=0.95,
                point_type="evidence_record",
                source_id="ev_review",
                document_id="B10",
                source_pdf="B10.pdf",
                page_start=4,
                record_type="formulation_condition",
                requires_review=True,
                quality_flags=["suspicious_percent_gt_300"],
                text="BCL loading range with suspicious OCR duplicate text.",
            ),
            RetrievalHit(
                score=0.80,
                vector_score=0.80,
                point_type="evidence_record",
                source_id="ev_usable",
                document_id="B10",
                source_pdf="B10.pdf",
                page_start=5,
                record_type="formulation_condition",
                usable_for_ranking=True,
                text="BCL-ZIF-8 loading 700 mg adsorption time 30 min pH 7.5.",
            ),
        ]

        reranked = rerank_document_hits("B10论文对酶固定化剂的优化过程是怎么样的", hits, plan)

        self.assertEqual(reranked[0].source_id, "ev_usable")

    def test_paper_process_query_detector(self) -> None:
        self.assertTrue(is_paper_process_query("B10论文对酶固定化剂的优化过程是怎么样的"))
        self.assertTrue(is_paper_process_question("B10 paper BCL-ZIF-8 optimization process"))
        self.assertFalse(is_paper_process_question("优化固定化载体推荐"))

    def test_diversity_drops_exact_duplicate_evidence_text(self) -> None:
        duplicate_text = (
            "Columns: Enzyme | Carrier | Yield | Reuse. "
            "Row 1: Enzyme: BCL | Carrier: ZIF-8 | Yield: 93.4% | Reuse: 8 cycles. "
            "This sentence makes the fingerprint long enough to detect duplicated rows."
        )
        hits = [
            RetrievalHit(
                score=0.92,
                rerank_score=0.92,
                point_type="evidence_record",
                source_id="ev_dup_1",
                document_id="B10",
                record_type="table_comparison_row",
                text=duplicate_text,
            ),
            RetrievalHit(
                score=0.91,
                rerank_score=0.91,
                point_type="evidence_record",
                source_id="ev_dup_2",
                document_id="B10",
                record_type="table_comparison_row",
                text=duplicate_text,
            ),
            RetrievalHit(
                score=0.86,
                rerank_score=0.86,
                point_type="evidence_record",
                source_id="ev_other_doc",
                document_id="C6",
                record_type="immobilization_strategy",
                text="Warfarin synthesis used supported lipase evidence in a different document.",
            ),
        ]

        diversified = apply_result_diversity(hits)

        self.assertEqual([hit.source_id for hit in diversified], ["ev_dup_1", "ev_other_doc"])

    def test_retrieval_query_for_evidence_question_does_not_inject_recommendation_terms(self) -> None:
        query = build_retrieval_query(
            EnzymeRecommendationRequest(
                enzyme_name="Burkholderia cepacia lipase",
                objective="answer_evidence_question",
                application_context="B10 这篇文章用了什么固定化载体？",
            )
        )

        self.assertIn("B10 这篇文章用了什么固定化载体？", query)
        self.assertIn("immobilization enzyme evidence", query)
        self.assertNotIn("activity recovery reusability stability", query)

    def test_retrieval_query_for_explicit_recommendation_keeps_recommendation_terms(self) -> None:
        query = build_retrieval_query(
            EnzymeRecommendationRequest(
                enzyme_name="BCL",
                application_context="请推荐 BCL 用于 biodiesel 的固定化载体",
            )
        )

        self.assertIn("activity recovery reusability stability", query)

    def test_retrieval_query_for_paper_process_does_not_inject_recommendation_terms(self) -> None:
        query = build_retrieval_query(
            EnzymeRecommendationRequest(
                enzyme_name="B10论文",
                objective=PAPER_PROCESS_OBJECTIVE,
                application_context="B10论文对酶固定化剂的优化过程是怎么样的",
            )
        )

        self.assertIn("B10论文对酶固定化剂的优化过程是怎么样的", query)
        self.assertNotIn("activity recovery reusability stability", query)


class PostMinerUQAGateTests(unittest.TestCase):
    def test_placeholder_pages_are_marked_unusable(self) -> None:
        chunks = [
            {
                "chunk_id": "A34_chunk_1",
                "page_start": 7,
                "page_end": 7,
                "text": "UNRECOVERABLE PAGE PLACEHOLDER",
                "quality_flags": [],
            }
        ]
        tables: list[dict] = []

        summary = apply_qa_gate(chunks, tables, MinerUQAGateConfig(placeholder_pages=frozenset({7})))

        self.assertEqual(summary.status, "fail")
        self.assertIn("unrecoverable_page_placeholder", chunks[0]["quality_flags"])
        self.assertTrue(chunks[0]["requires_review"])
        self.assertFalse(chunks[0]["usable_for_ranking"])

    def test_bad_table_structure_is_marked_for_review(self) -> None:
        chunks: list[dict] = []
        tables = [
            {
                "table_id": "A14_p5_t1",
                "page_idx": 4,
                "columns": ["flattened"],
                "rows": [["alpha"], ["beta"], ["gamma"]],
                "bbox": [0, 0, 1000, 120],
                "quality_flags": [],
                "text": "alpha beta gamma",
            }
        ]

        summary = apply_qa_gate(chunks, tables, MinerUQAGateConfig())

        self.assertEqual(summary.status, "fail")
        self.assertIn("bad_table_structure", tables[0]["quality_flags"])
        self.assertTrue(tables[0]["requires_review"])


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

    def test_build_evidence_preview_is_immediate_and_cited(self) -> None:
        preview = build_evidence_preview(sample_retrieval_response(), title="证据预览")

        self.assertIn("证据预览", preview)
        self.assertIn("B10.pdf:p8", preview)
        self.assertIn("模型建议生成中", preview)


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

    def test_openai_stream_preserves_reasoning_delta(self) -> None:
        class FakeStreamResponse:
            def raise_for_status(self) -> None:
                return None

            def iter_lines(self):
                yield 'data: {"model":"m","choices":[{"delta":{"reasoning_content":"thinking"},"finish_reason":null}]}'
                yield 'data: {"model":"m","choices":[{"delta":{"content":"answer"},"finish_reason":null}]}'
                yield "data: [DONE]"

        client = OpenAICompatibleGeneratorClient(provider="test", base_url="http://llm", api_key="k")

        chunks = list(client._iter_stream_response(FakeStreamResponse(), "fallback-model"))  # type: ignore[arg-type]

        self.assertEqual(chunks[0].reasoning_delta, "thinking")
        self.assertEqual(chunks[0].delta, "")
        self.assertEqual(chunks[1].delta, "answer")


class LiveStreamPromptTests(unittest.TestCase):
    def test_recommendation_live_stream_uses_text_response_format(self) -> None:
        service = RecommendationService(runtime=runtime_with_config())
        request = EnzymeRecommendationRequest(enzyme_name="BCL")
        retrieval = sample_retrieval_response()

        generation_request = service.build_stream_generation_request(request, retrieval)

        self.assertEqual(generation_request.response_format, "text")
        self.assertEqual(generation_request.max_retries, 0)
        self.assertIn("不输出 JSON", generation_request.messages[-1].content)

    def test_evidence_question_stream_prompt_does_not_force_recommendation(self) -> None:
        request = EnzymeRecommendationRequest(
            enzyme_name="B10 这篇文章",
            objective="answer_evidence_question",
            application_context="B10 这篇文章用了什么固定化载体？",
        )
        prompt = build_stream_generation_prompt(request, sample_retrieval_response())

        self.assertIn("回答用户问题", prompt)
        self.assertIn("不要默认改写成固定化推荐", prompt)
        self.assertIn("直接回答用户问题", prompt)

    def test_paper_process_stream_prompt_has_required_structure_and_warnings(self) -> None:
        request = EnzymeRecommendationRequest(
            enzyme_name="B10论文",
            objective=PAPER_PROCESS_OBJECTIVE,
            application_context="B10论文对酶固定化剂的优化过程是怎么样的",
            paper_document_id="B10",
            paper_source_pdf="B10.pdf",
            paper_resolution_status="resolved",
        )
        retrieval = RetrievalResponse(
            query="B10论文优化过程",
            collection="enzyme_immobilization_b10",
            embedding_model="hash-v1-64",
            top_k=1,
            usable_only=False,
            hits=[
                RetrievalHit(
                    score=0.8,
                    point_type="evidence_record",
                    source_id="ev_condition",
                    citation="B10.pdf:p6",
                    document_id="B10",
                    source_pdf="B10.pdf",
                    record_type="formulation_condition",
                    requires_review=True,
                    qa_status="fail",
                    text="loading 700 mg adsorption time 30 min pH 7.5",
                )
            ],
        )

        prompt = build_stream_generation_prompt(request, retrieval)

        self.assertIn("论文定位", prompt)
        self.assertIn("优化变量", prompt)
        self.assertIn("证据缺口与需复核项", prompt)
        self.assertIn("requires_review=true", prompt)
        self.assertIn("qa_status=fail", prompt)

    def test_evidence_qa_response_does_not_fallback_to_recommendation_candidates(self) -> None:
        service = RecommendationService(runtime=runtime_with_config())
        request = EnzymeRecommendationRequest(
            enzyme_name="你好",
            objective="answer_evidence_question",
            application_context="你好",
        )
        retrieval = RetrievalResponse(
            query="你好",
            collection="enzyme_immobilization_b10",
            embedding_model="hash-v1-64",
            top_k=1,
            usable_only=True,
            hits=[
                RetrievalHit(
                    score=0.5,
                    point_type="evidence_record",
                    source_id="ev_noise",
                    citation="A48.pdf:p5",
                    record_type="immobilization_strategy",
                    text="adsorption on carrier",
                    extracted={"immobilization_method": "adsorption"},
                )
            ],
        )
        generation = MockGeneratorClient().generate(
            GenerationRequest(
                messages=[ChatMessage(role="user", content="hello")],
                model="mock-generator-v1",
                response_format="text",
            )
        )

        response = service.build_response(request, retrieval, generation)

        self.assertEqual(response.candidates, [])
        self.assertEqual(response.next_experiment_suggestions, [])

    def test_formulation_live_stream_uses_text_response_format(self) -> None:
        service = FormulationOptimizationService(runtime=runtime_with_config())
        request = FormulationOptimizationRequest(enzyme_name="BCL", user_formulation={"buffer": {"pH": 7}})
        retrieval = sample_retrieval_response()

        generation_request = service.build_stream_generation_request(request, retrieval)

        self.assertEqual(generation_request.response_format, "text")
        self.assertEqual(generation_request.max_retries, 0)
        self.assertIn("不输出 JSON", generation_request.messages[-1].content)


class PdfRouteTests(unittest.TestCase):
    def test_resolve_pdf_file_accepts_known_pdf_name(self) -> None:
        path = resolve_pdf_file("B10.pdf")

        self.assertIsNotNone(path)
        assert path is not None
        self.assertEqual(path.name, "B10.pdf")

    def test_resolve_pdf_file_rejects_path_traversal(self) -> None:
        self.assertIsNone(resolve_pdf_file("../configs/local.yaml"))


class DashboardSummaryTests(unittest.TestCase):
    def test_collect_source_pdf_stats_counts_local_pdf_pages(self) -> None:
        stats = collect_source_pdf_stats(Path("MOF固定化脂肪酶文献调研"))

        self.assertGreaterEqual(stats["source_pdf_count"], 90)
        self.assertGreater(stats["source_pdf_pages"], 900)
        self.assertEqual(stats["source_pdf_page_failures"], 0)

    def test_summarize_qdrant_payloads_counts_documents_pages_and_point_types(self) -> None:
        payloads = [
            {
                "point_type": "rag_chunk",
                "document_id": "A1",
                "source_pdf": "A1.pdf",
                "page_start": 0,
                "page_end": 1,
            },
            {
                "point_type": "table_record",
                "document_id": "A1",
                "source_pdf": "A1.pdf",
                "page_start": 3,
                "page_end": 3,
            },
            {
                "point_type": "evidence_record",
                "document_id": "B2",
                "source_pdf": "B2.pdf",
                "page_start": 0,
                "page_end": 0,
            },
        ]

        summary = summarize_qdrant_payloads(
            payloads,
            {"status": "green", "points_count": 3},
        )

        self.assertEqual(summary["processed_docs"], 2)
        self.assertEqual(summary["processed_pages"], 5)
        self.assertEqual(summary["indexed_docs"], 2)
        self.assertEqual(summary["indexed_pages"], 5)
        self.assertEqual(summary["rag_chunks"], 1)
        self.assertEqual(summary["table_records"], 1)
        self.assertEqual(summary["evidence_records"], 1)
        self.assertEqual(summary["qdrant_points"], 3)
        self.assertEqual(summary["qdrant_status"], "green")

    def test_collect_artifact_stats_uses_manifests_and_evidence_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rag_root = root / "rag_inputs"
            evidence_root = root / "evidence"
            doc_root = rag_root / "A1"
            ev_root = evidence_root / "A1"
            doc_root.mkdir(parents=True)
            ev_root.mkdir(parents=True)
            (doc_root / "document_manifest.json").write_text(
                json.dumps(
                    {
                        "counts": {
                            "pages": 7,
                            "rag_chunks": 11,
                            "table_records": 2,
                        }
                    }
                ),
                encoding="utf-8",
            )
            write_jsonl(ev_root / "evidence_records.jsonl", [{"id": "ev1"}, {"id": "ev2"}])
            write_jsonl(ev_root / "review_queue.jsonl", [{"id": "rv1"}])

            stats = collect_artifact_stats(rag_root, evidence_root)

        self.assertEqual(stats["processed_docs"], 1)
        self.assertEqual(stats["processed_pages"], 7)
        self.assertEqual(stats["rag_chunks"], 11)
        self.assertEqual(stats["table_records"], 2)
        self.assertEqual(stats["evidence_records"], 2)
        self.assertEqual(stats["review_items"], 1)

    def test_dashboard_summary_cache_is_scoped_by_collection(self) -> None:
        app = type("AppStub", (), {"state": type("StateStub", (), {})()})()
        runtime = runtime_with_config()

        with patch("enzyme_recommender.api.app.build_dashboard_summary") as build_summary:
            build_summary.side_effect = [
                make_dashboard_summary(
                    "enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1",
                    1,
                ),
                make_dashboard_summary("alternate_collection", 2),
            ]

            first = get_cached_dashboard_summary(app, runtime)
            second = get_cached_dashboard_summary(app, runtime)
            alternate_runtime = runtime_with_collection(runtime, "alternate_collection")
            third = get_cached_dashboard_summary(app, alternate_runtime)

        self.assertIs(first, second)
        self.assertEqual(
            first.collection,
            "enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1",
        )
        self.assertEqual(first.processed_docs, 1)
        self.assertEqual(third.collection, "alternate_collection")
        self.assertEqual(third.processed_docs, 2)
        self.assertEqual(build_summary.call_count, 2)

    def test_runtime_with_collection_resolves_auto_collection(self) -> None:
        runtime = runtime_with_config()

        auto_runtime = runtime_with_collection(runtime, "auto")

        self.assertEqual(
            auto_runtime.config.vector_store.collection,
            "enzyme_immobilization_literature_sentence_baai_bge_base_en_v1_5_768_point_schema_v1",
        )


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    import csv

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def load_jsonl_for_test(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def make_student_csv_row(
    task_id: str,
    decision: str,
    reviewer: str = "",
    enzyme: str = "",
    carrier: str = "",
    condition: str = "",
    metric_name: str = "",
    metric_value: str = "",
    metric_unit: str = "",
    evidence_span: str = "",
    note: str = "",
) -> dict:
    return {
        "任务编号": task_id,
        "PDF文件": "A11.pdf",
        "页码": "1",
        "章节或表格": "test",
        "内容类型": "性能结果",
        "需校验内容": "test evidence",
        "机器提取结果": "test machine result",
        "风险提示": "",
        "判定结果": decision,
        "正确的酶/蛋白": enzyme,
        "正确的载体/材料": carrier,
        "正确的固定化方法/条件": condition,
        "正确的指标名": metric_name,
        "正确的数值": metric_value,
        "正确的单位": metric_unit,
        "正确原文或表格行": evidence_span,
        "错误原因或备注": note,
        "标注人": reviewer,
    }


def make_dashboard_summary(collection: str, processed_docs: int) -> DashboardSummaryResponse:
    return DashboardSummaryResponse(
        source_pdf_count=processed_docs,
        processed_docs=processed_docs,
        processed_pages=processed_docs * 10,
        indexed_docs=processed_docs,
        indexed_pages=processed_docs * 10,
        rag_chunks=0,
        table_records=0,
        evidence_records=0,
        curated_evidence_records=0,
        review_items=0,
        qdrant_points=0,
        qdrant_status="green",
        stats_source="test",
        collection=collection,
    )


def runtime_with_config() -> RuntimeServices:
    return RuntimeServices(config=RuntimeConfig.from_file(Path("configs/local.yaml")))


def sample_retrieval_response() -> RetrievalResponse:
    return RetrievalResponse(
        query="BCL immobilization",
        collection="enzyme_immobilization_b10",
        embedding_model="hash-v1-768",
        top_k=1,
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
                extracted={"carrier": "ZIF-8"},
                text="BCL immobilized on ZIF-8 with biodiesel yield evidence.",
            )
        ],
    )


if __name__ == "__main__":
    unittest.main()
