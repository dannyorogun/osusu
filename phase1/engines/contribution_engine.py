from decimal import Decimal

from models.contribution import ContributionStatus


class ContributionEngine:

    @staticmethod
    def create_contribution(member_id, period, amount, due_date):
        from models.contribution import Contribution

        return Contribution(
            member_id=member_id,
            period=period,
            amount_due=Decimal(str(amount)),
            due_date=due_date
        )

    @staticmethod
    def record_payment(contribution, amount):
        contribution.make_payment(
            Decimal(str(amount))
        )

    @staticmethod
    def calculate_expected(contributions):
        return sum(
            contribution.amount_due
            for contribution in contributions
        )

    @staticmethod
    def calculate_collected(contributions):
        return sum(
            contribution.amount_paid
            for contribution in contributions
        )

    @staticmethod
    def calculate_shortfall(contributions):
        expected = ContributionEngine.calculate_expected(
            contributions
        )

        collected = ContributionEngine.calculate_collected(
            contributions
        )

        return max(expected - collected, Decimal("0"))

    @staticmethod
    def get_unpaid(contributions):
        return [
            contribution
            for contribution in contributions
            if contribution.status != ContributionStatus.PAID
        ]