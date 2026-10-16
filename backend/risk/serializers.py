from rest_framework import serializers


class DefaultRiskPredictionSerializer(serializers.Serializer):
    """
    User-visible shape of a DefaultRiskPredictor.predict() result.

    Privacy boundary: the predictor also returns the raw model inputs
    ("features"), several of which summarize the member's behaviour
    across ALL their circles (payments_made, late_payments, defaults,
    completed_cycles, trust connections). Those stay internal; only the
    fields declared here are ever serialized, so peers cannot learn a
    member's history from circles they do not share.

    default_probability is an informational risk signal for the positive
    class DEFAULTED. It does not approve or reject payouts, move money,
    alter obligations, or override governance.
    """

    member_id = serializers.UUIDField()
    circle_id = serializers.UUIDField()
    default_probability = serializers.FloatField(
        min_value=0.0,
        max_value=1.0,
    )
    model_version = serializers.CharField()
    feature_version = serializers.CharField()
    informational_only = serializers.BooleanField()
