class CircleHealthEngine:

    @staticmethod
    def score(features):

        score = 100

        score *= features["average_payment_rate"]

        score -= (
            features["overdue_members"] * 5
        )

        score = max(0, min(100, score))

        return round(score, 2)