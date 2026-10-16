class RiskEngine:

    @staticmethod
    def calculate_risk(profile):

        risk = 0

        risk += profile.defaults * 50
        risk += profile.missed_payments * 10

        risk -= profile.completed_cycles * 5

        return max(risk, 0)