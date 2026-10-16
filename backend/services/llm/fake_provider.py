"""
Deterministic development/test provider. NOT a language model.

Default behaviour: pick the supplied source sharing the most words with
the question and quote its matching lines verbatim, citing that source.
With no word overlap it answers "insufficient_context". It never produces
text that is not in the supplied context.

Tests can script the raw output (`script=`) or an exception (`error=`)
to exercise ExplanationService's validation and error handling. Every
call is recorded in `calls` so tests can inspect exactly what a provider
receives.
"""

import json
import re

from services.llm.prompts import INSUFFICIENT_CONTEXT_ANSWER
from services.llm.provider import LLMProvider, LLMResult


_WORD = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset({
    "the", "and", "for", "are", "was", "what", "why", "how", "who",
    "when", "does", "did", "has", "have", "this", "that", "with", "about",
    "our", "your", "you", "can", "tell", "much", "many", "will", "is",
    "my", "me", "of", "in", "to", "a", "an", "on", "it", "be", "do",
})

MAX_QUOTED_LINES = 3


def _words(text):
    return {
        w for w in _WORD.findall(text.lower())
        if len(w) >= 3 and w not in _STOPWORDS
    }


class FakeLLMProvider(LLMProvider):

    name = "fake-extractive"
    model = "fake-extractive-v1"

    def __init__(self, *, script=None, error=None):
        """
        script: raw text to return, or callable(system, user, context)
                returning raw text.
        error:  exception instance to raise instead of answering.
        """
        self.script = script
        self.error = error
        self.calls = []

    def generate(self, *, system_prompt, user_prompt, context):
        self.calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "context": tuple(context),
        })

        if self.error is not None:
            raise self.error

        if callable(self.script):
            text = self.script(system_prompt, user_prompt, tuple(context))
        elif self.script is not None:
            text = self.script
        else:
            text = json.dumps(self._extract(user_prompt, context))

        return LLMResult(text=text, provider=self.name, model=self.model)

    @staticmethod
    def _extract(user_prompt, context):
        question = user_prompt.rsplit("<question>", 1)[-1]
        question_words = _words(question)

        best, best_score = None, 0
        for item in context:  # context arrives ranked; ties keep order
            score = len(question_words & _words(item.content))
            if score > best_score:
                best, best_score = item, score

        lines = [] if best is None else [
            line.strip().lstrip("-# ").strip()
            for line in best.content.split("\n")[1:]  # skip title line
            if question_words & _words(line)
        ][:MAX_QUOTED_LINES]

        if not lines:
            return {
                "status": "insufficient_context",
                "answer": INSUFFICIENT_CONTEXT_ANSWER,
                "citations": [],
            }

        return {
            "status": "answered",
            "answer": " ".join(lines),
            "citations": [best.source_id],
        }
