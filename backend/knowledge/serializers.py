from rest_framework import serializers

from services.llm.explanation_service import MAX_QUESTION_LENGTH


class AssistantQuestionSerializer(serializers.Serializer):
    """
    Exactly one field. Unknown fields (e.g. a "circle_id") are rejected:
    the circle always comes from the URL.
    """

    question = serializers.CharField(
        max_length=MAX_QUESTION_LENGTH,
        trim_whitespace=True,
    )

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"non_field_errors": ["Only 'question' is accepted."]}
            )
        return attrs


class AssistantCitationSerializer(serializers.Serializer):
    document_id = serializers.CharField()
    document_type = serializers.CharField()
    document_version = serializers.IntegerField()
    chunk_id = serializers.CharField()
    title = serializers.CharField()


class AssistantAnswerSerializer(serializers.Serializer):
    """
    The complete public response. Prompts, context, scores, vectors,
    provider details and internal metadata are deliberately absent.
    """

    request_id = serializers.CharField()
    status = serializers.CharField()
    answer = serializers.CharField()
    citations = AssistantCitationSerializer(many=True)
    prompt_version = serializers.CharField()
    knowledge_schema_version = serializers.CharField()
    informational_only = serializers.SerializerMethodField()

    def get_informational_only(self, obj):
        return True
