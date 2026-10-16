"""
Retrieval evaluation (evaluation/retrieval/questions.json) and
reproducible threshold selection.

- Pure logic tests: dataset validation and the selection rule.
- Offline run: the whole evaluation with the local hashing provider over
  the isolated fixture corpus (no network). Proves the harness end to
  end; its numbers say nothing about the production model.
- OPT-IN live run (OSUSU_RUN_EXTERNAL_AI_TESTS=true): the same evaluation
  with the real OpenAI model. Writes the machine-readable result when
  OSUSU_EVALUATION_OUTPUT_DIR is set.
"""

from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from knowledge.models import KnowledgeDocumentType

from services.knowledge import retrieval_evaluation as ev
from services.knowledge.embedding_service import HashingEmbeddingProvider
from services.knowledge.retriever import MAX_TOP_K, KnowledgeRetriever
from services.llm.explanation_service import RETRIEVAL_TOP_K

from .live import LiveCredentialsMixin, live, output_dir
from .test_retrieval_evaluation import EvaluationFixture


DATASET = Path(settings.BASE_DIR) / "evaluation" / "retrieval" / "questions.json"


def record(qid, expected_retrieval, top1=None, best=None):
    return {
        "id": qid, "category": "RELEVANT", "expected_retrieval": expected_retrieval,
        "top1_score": top1, "best_expected_score": best, "scope_violations": 0,
    }


class DatasetTests(SimpleTestCase):

    def test_dataset_is_valid_and_covers_every_category(self):
        data = ev.load_dataset(DATASET)
        questions = data["questions"]

        self.assertEqual({q["category"] for q in questions}, set(ev.CATEGORIES))
        self.assertEqual(len(data["sha256"]), 64)

        tags = {t for q in questions for t in q["tags"]}
        self.assertTrue({"money", "date", "period", "member", "circle"} <= tags)

        valid_types = set(KnowledgeDocumentType.values)
        for q in questions:
            self.assertTrue(set(q.get("expected_document_types", ())) <= valid_types,
                            q["id"])

    def test_invalid_datasets_are_rejected(self):
        import json
        import tempfile

        for bad in (
            {"questions": []},
            {"questions": [{"id": "X", "category": "NOPE", "question": "q",
                            "expected_retrieval": "none"}]},
            {"questions": [{"id": "X", "category": "RELEVANT", "question": "q",
                            "expected_retrieval": "relevant"}]},
            {"questions": [{"id": "X", "category": "IRRELEVANT", "question": "q",
                            "expected_retrieval": "none"}] * 2},
        ):
            with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
                json.dump(bad, handle)
                handle.flush()
                with self.assertRaises(ev.EvaluationDatasetError):
                    ev.load_dataset(handle.name)


class ThresholdSelectionTests(SimpleTestCase):

    def test_separable_scores_pick_a_point_inside_the_gap(self):
        records = [
            record("R1", "relevant", 0.61, 0.61),
            record("R2", "relevant", 0.48, 0.45),
            record("N1", "none", 0.22),
            record("N2", "none", 0.31),
        ]
        selection = ev.select_threshold(records)

        self.assertTrue(selection["separable"])
        self.assertEqual(selection["threshold"], 0.38)
        applied = ev.apply_threshold(records, selection["threshold"])
        self.assertEqual((applied["false_positives"], applied["false_negatives"]),
                         ([], []))

    def test_overlap_favours_zero_false_positives(self):
        records = [
            record("R1", "relevant", 0.6, 0.6),
            record("R2", "relevant", 0.3, 0.25),
            record("N1", "none", 0.4),
        ]
        selection = ev.select_threshold(records)

        self.assertFalse(selection["separable"])
        self.assertEqual(selection["threshold"], 0.4)
        applied = ev.apply_threshold(records, 0.4)
        self.assertEqual(applied["false_positives"], [])
        self.assertEqual(applied["false_negatives"], ["R2"])

    def test_boundary_is_strict_like_the_retriever(self):
        records = [record("R1", "relevant", 0.5, 0.5), record("N1", "none", 0.5)]
        applied = ev.apply_threshold(records, 0.5)
        self.assertEqual(applied["false_positives"], [])
        self.assertEqual(applied["false_negatives"], ["R1"])

    def test_a_relevant_question_missing_from_top_k_is_a_miss(self):
        records = [record("R1", "relevant", 0.7, None),
                   record("R2", "relevant", 0.6, 0.6),
                   record("N1", "none", 0.1)]
        selection = ev.select_threshold(records)
        self.assertEqual(selection["retrieval_misses_at_any_threshold"], ["R1"])
        self.assertIn("R1", ev.apply_threshold(records, 0.2)["false_negatives"])

    def test_small_or_offline_evaluations_are_always_provisional(self):
        records = [record("R1", "relevant", 0.9, 0.9), record("N1", "none", 0.1)]
        selection = ev.select_threshold(records)

        reasons = ev.provisional_reasons(records, selection, live=True)
        self.assertTrue(any("relevant questions" in r for r in reasons))
        self.assertTrue(any("negative questions" in r for r in reasons))

        reasons = ev.provisional_reasons(records, selection, live=False)
        self.assertTrue(any("live" in r for r in reasons))

    def test_large_clean_live_evaluation_is_not_provisional(self):
        records = (
            [record(f"R{i}", "relevant", 0.7, 0.7) for i in range(ev.MIN_POSITIVES)]
            + [record(f"N{i}", "none", 0.2) for i in range(ev.MIN_NEGATIVES)]
        )
        selection = ev.select_threshold(records)
        self.assertEqual(ev.provisional_reasons(records, selection, live=True), [])


class RunEvaluationMixin:

    def run_evaluation(self, *, live_run, compare=()):
        dataset = ev.load_dataset(DATASET)
        retriever = KnowledgeRetriever(provider=self.provider, store=self.store,
                                       min_similarity=-1.0)

        def search(question):
            return [
                ev.Hit(r.score, r.document_type, r.citation["circle_id"])
                for r in retriever.retrieve(
                    question, circle_ids={self.circle.id}, top_k=MAX_TOP_K,
                )
            ]

        records = ev.score_questions(
            dataset, search,
            scope_circle_id=self.circle.id,
            pipeline_top_k=RETRIEVAL_TOP_K,
        )
        return ev.build_report(
            dataset, records,
            provider=self.provider,
            live=live_run,
            pipeline_top_k=RETRIEVAL_TOP_K,
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            compare_thresholds=compare,
        )


class HashingEvaluationTests(RunEvaluationMixin, EvaluationFixture):
    """Offline end-to-end run of the harness (development provider)."""

    provider_factory = HashingEmbeddingProvider

    def test_offline_evaluation_is_reproducible_and_scoped(self):
        first = self.run_evaluation(live_run=False, compare=(0.03,))
        second = self.run_evaluation(live_run=False)

        self.assertEqual(first["questions"], second["questions"])
        self.assertEqual(first["threshold_selection"], second["threshold_selection"])
        self.assertEqual(first["scope_violations"], 0)
        self.assertEqual(first["dataset"]["size"], len(first["questions"]))
        self.assertTrue(first["threshold_selection"]["provisional"])
        self.assertFalse(first["live"])

        directory = output_dir()
        if directory:
            ev.write_report(first, directory)


@live
class OpenAIRetrievalEvaluationLive(LiveCredentialsMixin, RunEvaluationMixin,
                                    EvaluationFixture):
    """
    OPT-IN. Embeds ONLY the isolated fixture corpus and the dataset
    questions with the configured production model.
    """

    required_settings = ("OSUSU_EMBEDDING_API_KEY",)

    @staticmethod
    def provider_factory():
        from services.knowledge.openai_embedding_provider import (
            OpenAIEmbeddingProvider,
        )
        return OpenAIEmbeddingProvider(
            api_key=settings.OSUSU_EMBEDDING_API_KEY,
            model=settings.OSUSU_EMBEDDING_MODEL,
            dimension=settings.OSUSU_EMBEDDING_DIMENSIONS,
        )

    def test_live_retrieval_evaluation(self):
        report = self.run_evaluation(live_run=True, compare=(0.03,))

        self.assertEqual(report["scope_violations"], 0)
        self.assertEqual(report["embedding"]["model"], settings.OSUSU_EMBEDDING_MODEL)
        self.assert_no_secret(report)

        directory = output_dir()
        if directory:
            ev.write_report(report, directory)
