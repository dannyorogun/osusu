from django.db.models import Count

from finance.models import (
    Payout,
)


class PayoutResultService:

    @staticmethod
    def winner(circle, payout_window):

        payouts = (
            Payout.objects.filter(
                circle=circle,
                payout_window=payout_window,
            )
            .annotate(
                vote_count=Count("votes")
            )
            .order_by(
                "-vote_count",
                "created_at",
            )
        )

        return payouts.first()