import type { Uuid } from "./api";

/** knowledge.serializers.AssistantCitationSerializer */
export type AssistantCitation = {
  document_id: Uuid;
  document_type: string;
  document_version: number;
  chunk_id: Uuid;
  title: string;
};

/** POST /api/circles/<id>/assistant/ 200 (AssistantAnswerSerializer). */
export type AssistantAnswer = {
  request_id: string;
  status: "answered" | "insufficient_context";
  answer: string;
  citations: AssistantCitation[];
  prompt_version: string;
  knowledge_schema_version: string;
  informational_only: true;
};
