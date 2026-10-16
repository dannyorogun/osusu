"""
Retrieval evaluation set - a DEVELOPMENT BASELINE, not a validated
benchmark. Isolated fixture data only (KnowledgeFixture); nothing here
touches production data.

Observed cosine scores (HashingEmbeddingProvider, Sprint 25, top hits
with the threshold disabled; fixture circle "Manchester Developers"):

  question                                   v1 (d1024)        v2 (d4096, stop-words)
  Q1 How much is the weekly contribution?    0.247 risk  X     0.056 member contribution
  Q2 How often are payouts made?             0.115 member X    0.079 payout summary
  Q3 What is the current treasury balance?   0.247 risk  X     0.154 financial summary
  Q4 Why was the payout delayed?             0.147 circle      0.051 payout summary
  Q5 What is the capital of France?          0.267 risk  X     0.000 (nothing)
  Q5b zzqx vvkw                              0.039 risk        0.000 (nothing)
  Q6 Birmingham Bakers sourdough fund (in A) 0.114 circle      0.015 (collision noise)
  Q7 How frequently do members receive their
     disbursement?                           0.076 circle      0.085 circle summary

v1: an unrelated question outscored every relevant one - no threshold
could separate them. v2 (stop-words removed, 4096 buckets): noise <= 0.015,
relevant top hits >= 0.044. Threshold 0.03 was set inside that gap
(HashingEmbeddingProvider.default_min_similarity), not tuned per test.

Known lexical limitations (recorded, not "fixed" by tuning):
- Q1 matches contribution OBLIGATIONS, not the constitution line
  ("contribute" != "contribution" lexically).
- Q4 retrieves payout evidence although NO delay reason exists anywhere;
  the answer must come back "insufficient" - never an invented reason.
- Q7 synonyms only match through incidental shared words.
- The 0.015 / 0.044 margin is narrow.

The production embedding model (OpenAI) is evaluated with the larger
labelled set in evaluation/retrieval/questions.json
(knowledge/tests/test_retrieval_threshold.py); its threshold must come
from that live run.
"""

from django.test import override_settings

from knowledge.models import KnowledgeDocumentType as T

from services.knowledge.embedding_service import HashingEmbeddingProvider
from services.knowledge.index_service import KnowledgeIndexService
from services.knowledge.retriever import KnowledgeRetriever
from services.knowledge.vector_store import DatabaseVectorStore
from services.llm.explanation_service import (
    STATUS_INSUFFICIENT,
    ExplanationService,
)
from services.llm.fake_provider import FakeLLMProvider

from .fixtures import KnowledgeFixture


EVALUATION_SET = {
    "Q1": "How much is the weekly contribution?",
    "Q2": "How often are payouts made?",
    "Q3": "What is the current treasury balance?",
    "Q4": "Why was the payout delayed?",
    "Q5": "What is the capital of France?",
    "Q5b": "zzqx vvkw",
    "Q6": "Tell me about the Birmingham Bakers sourdough fund",
    "Q7": "How frequently do members receive their disbursement?",
}


class EvaluationFixture(KnowledgeFixture):

    provider_factory = HashingEmbeddingProvider

    def setUp(self):
        super().setUp()
        self.provider = self.provider_factory()
        self.store = DatabaseVectorStore.for_provider(self.provider)
        for circle in (self.circle, self.other_circle):
            KnowledgeIndexService.index_circle(
                circle, provider=self.provider, store=self.store,
            )

    def retrieve(self, key, min_similarity=None, circle=None):
        retriever = KnowledgeRetriever(
            provider=self.provider,
            store=self.store,
            min_similarity=min_similarity,
        )
        return retriever.retrieve(
            EVALUATION_SET[key],
            circle_ids={(circle or self.circle).id},
            top_k=10,
        )


class HashingRetrievalEvaluationTests(EvaluationFixture):
    """Expectations at the shipped default threshold (0.03)."""

    def test_threshold_is_the_measured_default(self):
        self.assertEqual(KnowledgeRetriever(
            provider=self.provider, store=self.store,
        ).min_similarity, 0.03)

    def test_q1_contribution_question_finds_contribution_evidence(self):
        results = self.retrieve("Q1")

        self.assertTrue(results)
        self.assertTrue(any("contribution" in r.content.lower() for r in results))

    def test_q2_payout_question_finds_payout_summary_first(self):
        self.assertEqual(self.retrieve("Q2")[0].document_type, T.PAYOUT_SUMMARY)

    def test_q3_treasury_question_finds_financial_summary_first(self):
        top = self.retrieve("Q3")[0]

        self.assertEqual(top.document_type, T.CIRCLE_FINANCIAL_SUMMARY)
        self.assertIn("£65.00", top.content)

    def test_q4_delay_reason_is_not_supported_by_any_evidence(self):
        results = self.retrieve("Q4")

        # Payout evidence may be retrieved, but nothing explains a delay.
        for result in results:
            self.assertNotIn("delay", result.content.lower())

        answer = ExplanationService.answer_question(
            user=self.alice,
            circle_id=self.circle.id,
            question=EVALUATION_SET["Q4"],
            provider=FakeLLMProvider(),
            retriever=KnowledgeRetriever(provider=self.provider, store=self.store),
        )
        self.assertNotIn("delay", answer.answer.lower().replace(
            EVALUATION_SET["Q4"].lower(), ""))

    def test_q5_unrelated_and_nonsense_questions_retrieve_nothing(self):
        for key in ("Q5", "Q5b"):
            with self.subTest(question=key):
                self.assertEqual(self.retrieve(key), [])

    def test_q5_unrelated_question_yields_controlled_answer_without_llm(self):
        provider = FakeLLMProvider()

        result = ExplanationService.answer_question(
            user=self.alice,
            circle_id=self.circle.id,
            question=EVALUATION_SET["Q5"],
            provider=provider,
            retriever=KnowledgeRetriever(provider=self.provider, store=self.store),
        )

        self.assertEqual(result.status, STATUS_INSUFFICIENT)
        self.assertEqual(provider.calls, [])

    def test_q6_other_circle_question_never_returns_other_circle(self):
        self.assertEqual(self.retrieve("Q6"), [])

        # Even with the threshold disabled, only circle A can come back.
        for result in self.retrieve("Q6", min_similarity=-1.0):
            self.assertEqual(result.citation["circle_id"], str(self.circle.id))
            self.assertNotIn("Birmingham", result.content)

        # And the other circle's own scope does find it.
        self.assertIn(
            "Birmingham Bakers",
            self.retrieve("Q6", circle=self.other_circle)[0].content,
        )

    def test_q7_synonyms_are_a_known_lexical_limitation(self):
        # Recorded, not asserted as relevant: lexical matching only.
        for result in self.retrieve("Q7"):
            self.assertEqual(result.citation["circle_id"], str(self.circle.id))

    def test_threshold_is_configurable_and_can_empty_retrieval(self):
        self.assertTrue(self.retrieve("Q3"))

        with override_settings(OSUSU_RAG_MIN_SIMILARITY="0.9"):
            self.assertEqual(
                KnowledgeRetriever(provider=self.provider, store=self.store)
                .retrieve(EVALUATION_SET["Q3"], circle_ids={self.circle.id}),
                [],
            )

    def test_scores_below_threshold_are_dropped(self):
        unfiltered = self.retrieve("Q6", min_similarity=-1.0)
        filtered = self.retrieve("Q6")

        self.assertTrue(unfiltered)
        self.assertTrue(all(r.score > 0.03 for r in filtered))
        self.assertLess(len(filtered), len(unfiltered))
