class ReliabilityEngine:

    @staticmethod
    def score(features):

        score = 100

        score -= features["overdue_count"] * 20

        score += features["payment_rate"] * 10

        score += features["invite_success"] * 5

        score = max(0, min(100, score))

        return round(score, 2)