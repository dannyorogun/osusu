from django.db import transaction

from finance.models import (
    UNRESOLVED_PAYOUT_STATUSES,
    Payout,
    PayoutStatus,
)

from services.payouts.eligibility_service import (
    PayoutEligibilityService,
)

from services.payouts.treasury_guard import (
    TreasuryGuard,
)

from services.audit.audit_service import (
    AuditService,
)


class PayoutEngine:

    @staticmethod
    @transaction.atomic
    def create_payout_window(
        *,
        circle,
        payout_window,
    ):

        # One payout in flight at a time: no new window while another is
        # open (PENDING candidates) or its recipient's payout is unresolved
        # (APPROVED / PROCESSING / FAILED / RETURNED). Re-calling for the
        # same open window is allowed and idempotent (get_or_create below).
        unresolved = (
            Payout.objects
            .filter(
                circle=circle,
                status__in=[
                    PayoutStatus.PENDING,
                    *UNRESOLVED_PAYOUT_STATUSES,
                ],
            )
            .exclude(
                payout_window=payout_window,
                status=PayoutStatus.PENDING,
            )
        )

        if unresolved.exists():
            raise ValueError(
                "Another payout window is still unresolved."
            )

        if Payout.objects.filter(
            circle=circle,
            payout_window=payout_window,
        ).exclude(status=PayoutStatus.PENDING).exists():
            raise ValueError(
                "This payout window has already been decided."
            )

        if not TreasuryGuard.can_pay(circle):
            raise ValueError(
                "Treasury cannot fund this payout."
            )

        eligible = (
            PayoutEligibilityService.eligible(circle)
        )

        if not eligible:
            raise ValueError(
                "No eligible members remain."
            )

        candidates = []

        for member in eligible:

            payout, created = (
                Payout.objects.get_or_create(
                    circle=circle,
                    member=member,
                    payout_window=payout_window,
                    defaults={
                        "amount": (
                            circle.constitution.payout_amount
                        ),
                        "status": PayoutStatus.PENDING,
                    },
                )
            )

            candidates.append(payout)

        AuditService.record(
            action="PAYOUT_WINDOW_CREATED",
            entity_type="Circle",
            entity_id=circle.id,
            user=circle.creator,
            metadata={
                "window": payout_window,
                "candidates": len(candidates),
            },
        )

        return candidates