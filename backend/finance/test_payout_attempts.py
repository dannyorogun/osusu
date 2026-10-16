"""
Sprint 33: provider-independent payout attempt safety.

Every provider here is a controlled TEST DOUBLE. A double that "settles"
proves only that Osusu records settlement evidence correctly; it says
nothing about whether any real provider is safe. Ledger, treasury, audit
and payout services are real (PostgreSQL).
"""

import threading
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import SimpleTestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditLog
from circles.models import Circle, CircleStatus
from finance.models import (
    LedgerTransaction,
    Payout,
    PayoutAttempt,
    PayoutAttemptState,
    PayoutAttemptTransitionError,
    PayoutStatus,
    TransactionType,
)
from finance.test_payout_safety import PRODUCTION, RecordingProvider, SettlingProvider
from finance.tests import PayoutLifecycleFixture
from payments.models import WebhookEvent
from services.circles.circle_service import CircleService
from services.finance.ledger_service import LedgerService
from services.finance.treasury_engine import TreasuryEngine
from services.payouts import provider as contract
from services.payouts.execute_payout_service import (
    ExecutePayoutService,
    PayoutProviderUnavailable,
)
from services.payouts.payout_attempt_service import PayoutAttemptService
from services.payouts.payout_event_service import PayoutEventService, UnknownPayoutEvent
from services.payouts.payout_reconciliation_service import PayoutReconciliationService
from services.payouts.payout_resolution_service import (
    STALE_PREPARED_AFTER,
    PayoutResolutionService,
)
from services.payouts.payout_return_service import PayoutReturnService


def event(attempt_or_ref, outcome, event_id, provider="recording", **extra):
    reference = getattr(attempt_or_ref, "provider_reference", attempt_or_ref)
    return contract.VerifiedPayoutEvent(
        provider=provider,
        event_id=event_id,
        event_type=f"transfer.{outcome}",
        provider_reference=reference,
        outcome=outcome,
        **extra,
    )


class LookupProvider(RecordingProvider):
    """A double that declares status lookup and answers with `answer`."""

    supports_status_lookup = True

    def __init__(self, answer=None, **kwargs):
        super().__init__(**kwargs)
        self.answer = answer
        self.lookups = []

    def lookup_status(self, *, idempotency_key, provider_reference):
        self.lookups.append((idempotency_key, provider_reference))
        return self.answer(idempotency_key) if callable(self.answer) else self.answer


class AttemptFixture(PayoutLifecycleFixture):
    """Treasury 250.00; the approved winner is paid 200.00."""

    def setUp(self):
        super().setUp()
        self.winner, _ = self.decide()

    def payout(self):
        return Payout.objects.get(pk=self.winner.pk)

    def attempts(self):
        return list(self.winner.attempts.order_by("attempt_number"))

    def execute(self, provider):
        return ExecutePayoutService.execute(self.winner, provider=provider)

    def treasury_api(self):
        self.authenticate(self.creator)
        return self.client.get(
            reverse("circle-treasury", kwargs={"circle_id": self.circle.id})
        ).json()

    def payouts_api(self):
        self.authenticate(self.creator)
        return self.client.get(
            reverse("circle-payouts", kwargs={"circle_id": self.circle.id})
        ).json()["payouts"]


@PRODUCTION
class ConfirmedSuccessTests(AttemptFixture):

    def test_settlement_evidence_records_exactly_one_ledger_entry(self):  # 1
        submitted = self.execute(RecordingProvider())
        attempt = submitted["attempt"]
        self.assertEqual(submitted["status"], "submitted")
        self.assertFalse(self.payout_rows().exists())

        result = PayoutEventService.process(event=event(attempt, "settled", "evt-1"))

        self.assertEqual(result["status"], "processed")
        self.assertEqual(self.payout().status, PayoutStatus.PAID)
        row = self.payout_rows().get()
        self.assertEqual(row.amount, Decimal("200.00"))
        self.assertEqual(row.payment_reference, attempt.provider_reference)
        self.assertEqual(row.metadata, {"payout_id": str(self.winner.id)})
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, PayoutAttemptState.SUCCEEDED)
        self.assertEqual(attempt.evidence_reference, "event:evt-1")
        self.assertEqual(self.balance(), Decimal("50.00"))
        self.assertEqual(AuditLog.objects.filter(action="PAYOUT_COMPLETED").count(), 1)

    def test_duplicate_execution_does_not_send_again(self):  # 2
        provider = SettlingProvider()
        first = self.execute(provider)
        second = self.execute(provider)
        self.assertEqual((first["status"], second["status"]), ("paid", "already_paid"))
        self.assertEqual(provider.calls, 1)
        self.assertEqual(len(self.attempts()), 1)
        self.assertEqual(self.payout_rows().count(), 1)

    def test_duplicate_success_events_write_one_ledger_entry(self):  # 6
        attempt = self.execute(RecordingProvider())["attempt"]
        settled = event(attempt, "settled", "evt-1")

        PayoutEventService.process(event=settled)
        duplicate = PayoutEventService.process(event=settled)
        redelivered = PayoutEventService.process(event=event(attempt, "settled", "evt-2"))
        late = PayoutEventService.process(event=event(attempt, "accepted", "evt-0"))
        PayoutAttemptService.record(
            attempt, contract.Classified(contract.SETTLED, attempt.provider_reference),
        )

        self.assertEqual(duplicate["status"], "duplicate")
        self.assertEqual(redelivered["status"], "processed")
        self.assertEqual(late["attempt"].state, PayoutAttemptState.SUCCEEDED)
        self.assertEqual(self.payout_rows().count(), 1)
        self.assertEqual(self.balance(), Decimal("50.00"))
        self.assertEqual(WebhookEvent.objects.filter(processed=True).count(), 3)
        self.assertEqual(AuditLog.objects.filter(action="PAYOUT_COMPLETED").count(), 1)

    def test_database_allows_one_payout_row_per_payout(self):  # 6
        self.execute(SettlingProvider())
        with self.assertRaises(IntegrityError), transaction.atomic():
            LedgerTransaction.objects.create(
                circle=self.circle, member=self.member,
                transaction_type=TransactionType.PAYOUT, amount=Decimal("200.00"),
                period_number=1, payment_reference="another-reference",
                metadata={"payout_id": str(self.winner.id)}, status="completed",
            )
        self.assertEqual(self.payout_rows().count(), 1)

    def test_success_with_a_different_reference_is_refused(self):
        attempt = self.execute(RecordingProvider())["attempt"]
        with self.assertRaises(PayoutAttemptTransitionError):
            PayoutEventService.process(event=event("someone-elses-transfer", "settled", "e1",
                                                   idempotency_key=attempt.idempotency_key))
        self.assertFalse(self.payout_rows().exists())
        self.assertFalse(WebhookEvent.objects.exists())  # rolled back


@PRODUCTION
class UnknownOutcomeTests(AttemptFixture):

    def test_timeout_after_submission_is_unknown_not_failed(self):  # 3
        result = self.execute(RecordingProvider(raises=True))

        self.assertEqual(result["status"], "unknown")
        attempt = self.attempts()[0]
        self.assertEqual(attempt.state, PayoutAttemptState.UNKNOWN)
        self.assertEqual(attempt.error_class, "TimeoutError")
        self.assertEqual(self.payout().status, PayoutStatus.PROCESSING)
        self.assertFalse(AuditLog.objects.filter(action="PAYOUT_EXECUTION_FAILED").exists())

        provider = SettlingProvider()
        retry = self.execute(provider)
        self.assertEqual(retry["status"], "in_progress")
        self.assertEqual(provider.calls, 0)
        self.assertEqual(len(self.attempts()), 1)

    def test_unknown_outcome_keeps_funds_reserved(self):  # 7
        self.execute(RecordingProvider(raises=True))
        other = Payout.objects.create(
            circle=self.circle, member=self.creator, payout_window=2,
            amount=Decimal("100.00"), status=PayoutStatus.APPROVED,
        )
        provider = SettlingProvider()

        with self.assertRaisesMessage(ValueError, "Treasury cannot fund"):
            ExecutePayoutService.execute(other, provider=provider)

        self.assertEqual(provider.calls, 0)
        self.assertEqual(TreasuryEngine.current_balance(self.circle), Decimal("250.00"))
        self.assertEqual(TreasuryEngine.reserved_for_payouts(self.circle), Decimal("200.00"))
        self.assertEqual(TreasuryEngine.available_balance(self.circle), Decimal("50.00"))
        with self.assertRaisesMessage(ValueError, "still unresolved"):
            self.open_window(3)

    def test_unknown_resolved_by_lookup_settlement(self):
        self.execute(RecordingProvider(raises=True))
        attempt = self.attempts()[0]
        provider = LookupProvider(
            answer=lambda key: {"outcome": "settled", "provider_reference": f"tr-{key}"},
        )

        result = PayoutResolutionService.resolve(attempt, provider)

        self.assertEqual(result["result"], "resolved")
        self.assertEqual(provider.lookups, [(attempt.idempotency_key, None)])
        self.assertEqual(provider.calls, 0)  # resolution never re-sends
        self.assertEqual(self.payout().status, PayoutStatus.PAID)
        self.assertEqual(self.payout_rows().get().payment_reference,
                         f"tr-{attempt.idempotency_key}")

    def test_lookup_not_found_is_never_a_failure(self):
        self.execute(RecordingProvider(raises=True))
        attempt = self.attempts()[0]

        result = PayoutResolutionService.resolve(attempt, LookupProvider(answer=None))

        self.assertEqual(result["result"], "unresolved")
        self.assertIn("Do not execute this payout again", result["action"])
        self.assertEqual(result["attempt"].state, PayoutAttemptState.UNKNOWN)
        self.assertEqual(self.payout().status, PayoutStatus.PROCESSING)

    def test_without_lookup_the_outcome_stays_unresolved(self):
        self.execute(RecordingProvider(raises=True))
        result = PayoutResolutionService.resolve(self.attempts()[0], provider=None)
        self.assertEqual(result["result"], "unresolved")
        self.assertEqual(self.payout().status, PayoutStatus.PROCESSING)

    def test_lookup_of_another_provider_is_not_trusted(self):
        self.execute(RecordingProvider(raises=True))
        impostor = LookupProvider(answer={"outcome": "rejected"})
        impostor.name = "other"
        PayoutResolutionService.resolve(self.attempts()[0], impostor)
        self.assertEqual(impostor.lookups, [])
        self.assertEqual(self.payout().status, PayoutStatus.PROCESSING)


class ProcessKilled(BaseException):
    """Stands in for the worker dying mid-request (not an Exception)."""


@PRODUCTION
class InterruptionTests(AttemptFixture):

    def test_interruption_after_attempt_creation_blocks_blind_resend(self):  # 4
        class DyingProvider(RecordingProvider):
            def send(self, **kwargs):
                super().send(**kwargs)
                raise ProcessKilled()

        with self.assertRaises(ProcessKilled):
            self.execute(DyingProvider())

        attempt = self.attempts()[0]
        self.assertEqual(attempt.state, PayoutAttemptState.PREPARED)
        self.assertEqual(self.payout().status, PayoutStatus.PROCESSING)

        provider = SettlingProvider()
        self.assertEqual(self.execute(provider)["status"], "in_progress")
        self.assertEqual(provider.calls, 0)

        fresh = PayoutResolutionService.resolve(attempt)
        self.assertEqual(fresh["attempt"].state, PayoutAttemptState.PREPARED)

        later = timezone.now() + STALE_PREPARED_AFTER
        stale = PayoutResolutionService.resolve(attempt, now=later)
        self.assertEqual(stale["result"], "unresolved")
        self.assertEqual(stale["attempt"].state, PayoutAttemptState.UNKNOWN)
        self.assertEqual(stale["attempt"].error_class, "stale_prepared")
        self.assertEqual(self.execute(provider)["status"], "in_progress")
        self.assertEqual(provider.calls, 0)
        self.assertEqual(TreasuryEngine.reserved_for_payouts(self.circle), Decimal("200.00"))

    def test_unrecordable_response_falls_back_to_unknown(self):
        class ReusedReference(RecordingProvider):
            def send(self, **kwargs):
                super().send(**kwargs)
                return {"outcome": "settled", "provider_reference": "contrib-c1"}

        ReusedReference.confirms_settlement_on_send = True
        result = self.execute(ReusedReference())

        self.assertEqual(result["status"], "unknown")
        self.assertTrue(result["attempt"].error_class.startswith("recording_failed"))
        self.assertFalse(self.payout_rows().exists())


@PRODUCTION
class ConfirmedFailureTests(AttemptFixture):

    def test_confirmed_failure_after_submission(self):  # 8
        attempt = self.execute(RecordingProvider())["attempt"]
        self.assertEqual(TreasuryEngine.reserved_for_payouts(self.circle), Decimal("200.00"))

        PayoutEventService.process(event=event(attempt, "rejected", "evt-r"))

        attempt.refresh_from_db()
        self.assertEqual(attempt.state, PayoutAttemptState.FAILED)
        self.assertIsNotNone(attempt.resolved_at)
        self.assertEqual(self.payout().status, PayoutStatus.FAILED)
        self.assertFalse(self.payout_rows().exists())
        self.assertEqual(TreasuryEngine.reserved_for_payouts(self.circle), Decimal("0"))
        log = AuditLog.objects.get(action="PAYOUT_EXECUTION_FAILED")
        self.assertEqual(log.metadata["from_state"], "submitted")
        self.assertEqual(log.metadata["evidence_reference"], "event:evt-r")

        again = self.execute(SettlingProvider())
        self.assertEqual(again["status"], "paid")
        self.assertEqual([a.state for a in self.attempts()], ["failed", "succeeded"])

    def test_evidence_for_a_superseded_attempt_never_touches_the_new_one(self):
        first = self.execute(RecordingProvider(result="rejected"))["attempt"]
        second = self.execute(RecordingProvider(raises=True))["attempt"]

        for outcome in (contract.SETTLED, contract.RETURNED):
            with self.subTest(outcome):
                with self.assertRaises(PayoutAttemptTransitionError):
                    PayoutAttemptService.record(
                        first, contract.Classified(outcome, "tr-old"),
                    )
        second.refresh_from_db()
        self.assertEqual(second.state, PayoutAttemptState.UNKNOWN)
        self.assertEqual(second.provider_reference, "")
        self.assertEqual(self.payout().status, PayoutStatus.PROCESSING)
        self.assertFalse(self.payout_rows().exists())

    def test_rejection_after_settlement_is_refused(self):
        attempt = self.execute(SettlingProvider())["attempt"]
        with self.assertRaises(PayoutAttemptTransitionError):
            PayoutEventService.process(event=event(attempt, "rejected", "late", provider="settling"))
        self.assertEqual(self.payout().status, PayoutStatus.PAID)
        self.assertEqual(self.payout_rows().count(), 1)


@PRODUCTION
class ReturnTests(AttemptFixture):

    def test_return_adds_a_compensating_entry_and_edits_nothing(self):  # 9
        attempt = self.execute(SettlingProvider())["attempt"]
        original = self.payout_rows().get()
        snapshot = LedgerTransaction.objects.filter(pk=original.pk).values().get()

        PayoutEventService.process(event=event(attempt, "returned", "ret-1", provider="settling"))
        PayoutEventService.process(event=event(attempt, "returned", "ret-2", provider="settling"))
        PayoutReturnService.record_return(
            payout=self.winner, provider_reference=attempt.provider_reference,
        )

        self.assertEqual(LedgerTransaction.objects.filter(pk=original.pk).values().get(), snapshot)
        compensation = LedgerTransaction.objects.get(transaction_type=TransactionType.PAYOUT_RETURN)
        self.assertEqual(compensation.amount, Decimal("200.00"))
        self.assertEqual(compensation.metadata["compensates_transaction_id"], str(original.id))
        self.assertEqual(self.balance(), Decimal("250.00"))
        self.assertEqual(self.payout().status, PayoutStatus.RETURNED)
        self.assertEqual(self.attempts()[0].state, PayoutAttemptState.RETURNED)

        with self.assertRaisesMessage(ValueError, "returned"):
            self.execute(SettlingProvider())
        with self.assertRaisesMessage(ValueError, "still unresolved"):
            self.open_window(2)

    def test_unsettled_payout_cannot_be_returned(self):
        attempt = self.execute(RecordingProvider())["attempt"]
        with self.assertRaisesMessage(ValueError, "Only a settled payout"):
            PayoutReturnService.record_return(
                payout=self.winner, provider_reference=attempt.provider_reference,
            )
        self.assertFalse(
            LedgerTransaction.objects.filter(transaction_type=TransactionType.PAYOUT_RETURN).exists()
        )


class TransitionTests(AttemptFixture):

    def attempt(self, state):
        return PayoutAttempt(state=state)

    def test_only_documented_transitions_are_permitted(self):  # 10
        allowed = {
            ("prepared", "submitted"), ("prepared", "unknown"), ("prepared", "succeeded"),
            ("prepared", "failed"), ("submitted", "succeeded"), ("submitted", "failed"),
            ("unknown", "submitted"), ("unknown", "succeeded"), ("unknown", "failed"),
            ("succeeded", "returned"),
        }
        for source in PayoutAttemptState.values:
            for target in PayoutAttemptState.values:
                with self.subTest(source=source, target=target):
                    attempt = self.attempt(source)
                    if (source, target) in allowed:
                        attempt.transition_to(target)
                        self.assertEqual(attempt.state, target)
                    else:
                        with self.assertRaises(PayoutAttemptTransitionError):
                            attempt.transition_to(target)

    @PRODUCTION
    def test_service_refuses_invalid_transitions_and_changes_nothing(self):
        attempt = self.execute(RecordingProvider(result="rejected"))["attempt"]
        for outcome in (contract.SETTLED, contract.ACCEPTED, contract.RETURNED):
            with self.subTest(outcome):
                with self.assertRaises((PayoutAttemptTransitionError, ValueError)):
                    PayoutAttemptService.record(
                        attempt, contract.Classified(outcome, "tr-1"),
                    )
                attempt.refresh_from_db()
                self.assertEqual(attempt.state, PayoutAttemptState.FAILED)
        self.assertFalse(self.payout_rows().exists())

    @PRODUCTION
    def test_idempotency_key_is_immutable_and_attempts_are_never_deleted(self):
        attempt = self.execute(RecordingProvider())["attempt"]
        attempt.idempotency_key = "something-else"
        with self.assertRaises(PayoutAttemptTransitionError):
            attempt.save()
        attempt.refresh_from_db()
        with self.assertRaises(PayoutAttemptTransitionError):
            attempt.delete()
        self.assertTrue(PayoutAttempt.objects.filter(pk=attempt.pk).exists())

    @PRODUCTION
    def test_database_allows_one_open_attempt_per_payout(self):  # 5
        attempt = self.execute(RecordingProvider())["attempt"]
        with self.assertRaises(IntegrityError), transaction.atomic():
            PayoutAttempt.objects.create(
                payout=self.winner, attempt_number=2, idempotency_key="k2",
                request_hash=attempt.request_hash, provider="recording",
            )
        with self.assertRaises(PayoutAttemptTransitionError):
            PayoutAttemptService.prepare(self.payout(), provider_name="recording")

    def test_attempts_hold_no_sensitive_data(self):
        fields = {f.name for f in PayoutAttempt._meta.get_fields()}
        self.assertFalse(fields & {"payload", "raw", "body", "account_number",
                                   "sort_code", "iban", "credentials"})


@PRODUCTION
class ReadApiConsistencyTests(AttemptFixture):

    def assert_treasury_consistent(self, reserved):
        body = self.treasury_api()
        balance = TreasuryEngine.current_balance(self.circle)
        self.assertEqual(Decimal(body["balance"]), balance)
        self.assertEqual(Decimal(body["reserved_for_payouts"]), Decimal(reserved))
        self.assertEqual(Decimal(body["available_balance"]), balance - Decimal(reserved))
        self.assertEqual(
            Decimal(body["totals"]["payout"]["total"]),
            TreasuryEngine.ledger_totals(self.circle)[TransactionType.PAYOUT]["total"],
        )
        return body

    def test_reads_match_the_engine_through_the_lifecycle(self):  # 11
        self.assert_treasury_consistent("0")

        attempt = self.execute(RecordingProvider(raises=True))["attempt"]
        self.assert_treasury_consistent("200.00")
        self.assertEqual(
            [(p["status"], p["attempt_state"], p["paid_at"]) for p in self.payouts_api()],
            [("processing", "unknown", None)],
        )

        PayoutAttemptService.record(
            attempt, contract.Classified(contract.ACCEPTED, "tr-9"),
            evidence_reference="operator-test",
        )
        PayoutEventService.process(event=event("tr-9", "settled", "evt-9"))
        body = self.assert_treasury_consistent("0")
        self.assertEqual(body["balance"], "50.00")
        self.assertEqual(
            [(p["status"], p["attempt_state"]) for p in self.payouts_api()],
            [("paid", "succeeded")],
        )

        PayoutEventService.process(event=event("tr-9", "returned", "evt-10"))
        body = self.assert_treasury_consistent("0")
        self.assertEqual(body["balance"], "250.00")
        self.assertEqual(body["totals"]["payout_return"], {"total": "200.00", "count": 1})
        self.assertEqual(
            [(p["status"], p["attempt_state"]) for p in self.payouts_api()],
            [("returned", "returned")],
        )

    def test_payouts_read_query_count_does_not_grow_with_attempts(self):
        self.authenticate(self.creator)
        url = reverse("circle-payouts", kwargs={"circle_id": self.circle.id})
        with CaptureQueriesContext(connection) as before:
            self.client.get(url)

        self.execute(RecordingProvider(result="rejected"))
        self.execute(RecordingProvider(result="rejected"))
        self.assertEqual(len(self.attempts()), 2)

        with self.assertNumQueries(len(before)):
            self.client.get(url)


@PRODUCTION
class DisabledPayoutsTests(AttemptFixture):

    def test_disabled_payouts_create_no_attempt(self):  # 12
        with self.assertRaises(PayoutProviderUnavailable):
            ExecutePayoutService.execute(self.winner)
        self.assertFalse(PayoutAttempt.objects.exists())
        self.assertEqual(self.payout().status, PayoutStatus.APPROVED)
        self.assertFalse(self.payout_rows().exists())

    def test_in_progress_is_answered_while_disabled(self):
        self.execute(RecordingProvider(raises=True))
        result = ExecutePayoutService.execute(self.winner)
        self.assertEqual(result["status"], "in_progress")


@PRODUCTION
class EventSafetyTests(AttemptFixture):

    def test_unverified_events_are_refused(self):
        with self.assertRaises(TypeError):
            PayoutEventService.process(event={"provider_reference": "x", "outcome": "settled"})
        with self.assertRaises(NotImplementedError):
            contract.PayoutEventVerifier().verify(body=b"{}", headers={})

    def test_event_for_unknown_reference_changes_nothing(self):
        self.execute(RecordingProvider())
        with self.assertRaises(UnknownPayoutEvent):
            PayoutEventService.process(event=event("nobody", "settled", "evt-x"))
        self.assertFalse(WebhookEvent.objects.exists())
        self.assertEqual(self.payout().status, PayoutStatus.PROCESSING)

    def test_event_amount_must_match(self):
        attempt = self.execute(RecordingProvider())["attempt"]
        with self.assertRaisesMessage(ValueError, "amount"):
            PayoutEventService.process(
                event=event(attempt, "settled", "evt-a", amount=Decimal("199.99")),
            )
        self.assertFalse(self.payout_rows().exists())

    def test_unknown_attempt_matched_by_echoed_idempotency_key(self):
        attempt = self.execute(RecordingProvider(raises=True))["attempt"]
        PayoutEventService.process(event=event(
            "tr-late", "settled", "evt-k", idempotency_key=attempt.idempotency_key,
        ))
        self.assertEqual(self.payout().status, PayoutStatus.PAID)
        self.assertEqual(self.payout_rows().get().payment_reference, "tr-late")

    def test_stored_event_holds_identifiers_only(self):
        attempt = self.execute(RecordingProvider())["attempt"]
        PayoutEventService.process(event=event(attempt, "accepted", "evt-p"))
        self.assertEqual(
            set(WebhookEvent.objects.get().payload),
            {"kind", "provider_reference", "outcome", "provider_status"},
        )


@PRODUCTION
class ReconciliationTests(AttemptFixture):

    def kinds(self, **kwargs):
        return sorted(f["kind"] for f in PayoutReconciliationService.report(**kwargs))

    def test_clean_settled_payout_has_no_findings(self):
        self.execute(SettlingProvider())
        self.assertEqual(self.kinds(), [])

    def test_unknown_and_stale_attempts_are_reported(self):
        self.execute(RecordingProvider(raises=True))
        self.assertEqual(self.kinds(), ["attempt_outcome_unknown"])

    def test_provider_report_mismatches(self):
        attempt = self.execute(SettlingProvider())["attempt"]
        records = [
            contract.ProviderTransferRecord("settling", attempt.provider_reference,
                                            Decimal("150.00"), "settled"),
            contract.ProviderTransferRecord("settling", "tr-unrecorded", Decimal("5.00"), "settled"),
        ]
        self.assertEqual(
            self.kinds(provider_records=records),
            ["provider_amount_mismatch", "provider_transfer_unrecorded"],
        )
        self.assertEqual(
            self.kinds(provider_records=[], provider_name="settling"),
            ["settled_attempt_missing_at_provider"],
        )
        self.assertEqual(self.kinds(provider_records=[], provider_name="other"), [])

    def test_report_writes_nothing(self):
        self.execute(RecordingProvider(raises=True))
        before = (PayoutAttempt.objects.values().get(), self.payout().status,
                  LedgerTransaction.objects.count(), AuditLog.objects.count())
        PayoutReconciliationService.report(provider_records=[])
        after = (PayoutAttempt.objects.values().get(), self.payout().status,
                 LedgerTransaction.objects.count(), AuditLog.objects.count())
        self.assertEqual(before, after)

    def test_legacy_payouts_are_flagged_for_information(self):
        Payout.objects.filter(pk=self.winner.pk).update(status=PayoutStatus.PAID)
        findings = PayoutReconciliationService.report()
        self.assertEqual([(f["kind"], f["severity"]) for f in findings],
                         [("legacy_payout_without_attempt", "info")])


class ClassificationTests(SimpleTestCase):

    def test_settlement_counts_only_when_the_contract_says_so(self):
        settled = {"outcome": "settled", "provider_reference": "tr"}
        self.assertEqual(contract.classify_result(RecordingProvider(), settled).outcome,
                         contract.ACCEPTED)
        self.assertEqual(contract.classify_result(SettlingProvider(), settled).outcome,
                         contract.SETTLED)

    def test_everything_ambiguous_is_unknown(self):
        for result in (None, {}, {"status": "failed"}, {"status": "sent"},
                       {"outcome": "accepted"}, {"outcome": "weird", "provider_reference": "x"},
                       "garbage", {"outcome": "accepted", "provider_reference": "x" * 151}):
            with self.subTest(result=result):
                self.assertEqual(contract.classify_result(RecordingProvider(), result).outcome,
                                 contract.UNKNOWN)
        for error in (TimeoutError(), ConnectionError(), ValueError("secret detail")):
            classified = contract.classify_exception(error)
            self.assertEqual(classified.outcome, contract.UNKNOWN)
            self.assertNotIn("secret", classified.error_class)
        self.assertEqual(contract.classify_exception(contract.PayoutNotSent()).outcome,
                         contract.NOT_SENT)


class ProviderBoundaryTests(TransactionTestCase):
    """
    Real commits: the attempt is durable BEFORE the provider is called,
    and no transaction or payout row lock is held during the call.
    """

    def setUp(self):
        User = get_user_model()
        creator = User.objects.create_user(
            username="creator", email="creator@example.com", password="StrongPassword123!",
        )
        member = User.objects.create_user(
            username="member", email="member@example.com", password="StrongPassword123!",
        )
        circle = CircleService.create_circle(
            creator=creator, name="Boundary Circle", member_limit=2,
            contribution_amount=Decimal("50.00"),
        )
        Circle.objects.filter(pk=circle.pk).update(status=CircleStatus.LOCKED)
        self.circle = Circle.objects.get(pk=circle.pk)
        LedgerService.record_transaction(
            circle=self.circle, member=creator,
            transaction_type=TransactionType.CONTRIBUTION,
            amount=Decimal("250.00"), period_number=1, payment_reference="fund",
        )
        self.payout = Payout.objects.create(
            circle=self.circle, member=member, payout_window=1,
            amount=Decimal("200.00"), status=PayoutStatus.APPROVED,
        )

    @PRODUCTION
    def test_attempt_is_committed_and_unlocked_during_the_provider_call(self):
        seen = {}
        payout_id = self.payout.pk

        def observe():
            try:
                with transaction.atomic():
                    row = Payout.objects.select_for_update(nowait=True).get(pk=payout_id)
                    seen["payout_status"] = row.status
                    seen["attempt_states"] = list(
                        PayoutAttempt.objects.filter(payout_id=payout_id)
                        .values_list("state", flat=True)
                    )
            except Exception as error:
                seen["error"] = repr(error)
            finally:
                connection.close()

        class ObservingProvider(RecordingProvider):
            def send(self, **kwargs):
                seen["in_atomic"] = connection.in_atomic_block
                thread = threading.Thread(target=observe)
                thread.start()
                thread.join(timeout=30)
                return super().send(**kwargs)

        result = ExecutePayoutService.execute(self.payout, provider=ObservingProvider())

        self.assertEqual(result["status"], "submitted")
        self.assertNotIn("error", seen)  # the row was not locked
        self.assertFalse(seen["in_atomic"])
        self.assertEqual(seen["payout_status"], PayoutStatus.PROCESSING)
        self.assertEqual(seen["attempt_states"], [PayoutAttemptState.PREPARED])

    @PRODUCTION
    def test_execute_refuses_to_run_inside_an_outer_transaction(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                ExecutePayoutService.execute(self.payout, provider=RecordingProvider())
        self.assertFalse(PayoutAttempt.objects.exists())

    @PRODUCTION
    def test_concurrent_duplicate_events_write_one_row(self):
        attempt = ExecutePayoutService.execute(
            self.payout, provider=RecordingProvider(),
        )["attempt"]
        barrier = threading.Barrier(6)
        errors = []

        def worker(n):
            try:
                barrier.wait()
                PayoutEventService.process(event=event(attempt, "settled", f"evt-{n % 2}"))
            except Exception as error:
                errors.append(error)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        # Same-id duplicates may lose the WebhookEvent insert race
        # (IntegrityError, rolled back, redeliverable); none may write.
        self.assertTrue(all(isinstance(e, IntegrityError) for e in errors), errors)
        self.assertEqual(
            LedgerTransaction.objects.filter(transaction_type=TransactionType.PAYOUT).count(), 1,
        )
        self.assertEqual(Payout.objects.get(pk=self.payout.pk).status, PayoutStatus.PAID)
        self.assertEqual(TreasuryEngine.current_balance(self.circle), Decimal("50.00"))
