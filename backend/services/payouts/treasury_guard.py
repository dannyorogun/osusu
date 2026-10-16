from services.finance.treasury_engine import TreasuryEngine


class TreasuryGuard:

    @staticmethod
    def can_pay(circle):

        # Reserved (in-progress) payouts are not available.
        balance = TreasuryEngine.available_balance(circle)

        required = circle.constitution.payout_amount

        return balance >= required