from decimal import Decimal

from models.payout import Payout


class PayoutEngine:

    @staticmethod
    def can_process_payout(available_balance, payout_amount):
        return available_balance >= payout_amount

    @staticmethod
    def process_payout(
        member,
        period,
        payout_amount,
        available_balance
    ):

        payout_amount = Decimal(str(payout_amount))

        if not PayoutEngine.can_process_payout(
            available_balance,
            payout_amount
        ):
            payout = Payout(
                member_id=member.member_id,
                period=period,
                amount=payout_amount
            )

            payout.block()

            return payout

        member.record_payout(payout_amount)

        payout = Payout(
            member_id=member.member_id,
            period=period,
            amount=payout_amount
        )

        payout.complete()

        return payout