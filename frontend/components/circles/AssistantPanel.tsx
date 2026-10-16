"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Field";
import { Alert, Card, CardTitle } from "@/components/ui/Surface";
import { osusu } from "@/lib/api/endpoints";
import { isApiError, userMessage } from "@/lib/api/errors";
import type { AssistantAnswer } from "@/types/assistant";

/**
 * Sends a question to the backend assistant endpoint and shows ONLY what
 * the backend returns. While the backend readiness gate keeps the
 * assistant disabled it answers 503, shown as "unavailable". Nothing is
 * generated or faked in the browser.
 */
export function AssistantPanel({ circleId }: { circleId: string }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AssistantAnswer | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    setAsking(true);
    setError(null);
    setAnswer(null);
    try {
      setAnswer(await osusu.assistant.ask(circleId, question.trim()));
    } catch (caught) {
      if (isApiError(caught) && caught.status === 503) setUnavailable(true);
      else setError(userMessage(caught));
    } finally {
      setAsking(false);
    }
  }

  return (
    <Card>
      <CardTitle>Ask about this circle</CardTitle>
      {unavailable ? (
        <Alert tone="info" title="AI assistance is currently unavailable.">
          The Osusu Assistant hasn&apos;t been switched on yet. Your circle records are unaffected.
        </Alert>
      ) : (
        <form onSubmit={onSubmit} className="space-y-4">
          <Textarea
            label="Question"
            maxLength={1000}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            hint="Informational only. The assistant cannot change payments, payouts or votes."
          />
          {error && <Alert tone="danger">{error}</Alert>}
          <Button type="submit" loading={asking} loadingText="Asking" disabled={!question.trim()}>
            Ask
          </Button>
        </form>
      )}
      {answer && (
        <div className="mt-5 space-y-3 text-sm">
          <p className="whitespace-pre-line text-ink">{answer.answer}</p>
          {answer.citations.length > 0 && (
            <ul className="list-disc pl-5 text-muted">
              {answer.citations.map((citation) => (
                <li key={citation.chunk_id}>{citation.title}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}
