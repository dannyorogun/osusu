# Assistant evaluation and live validation

Nothing here runs in the normal test suite against a paid API. The
offline pieces run in every `manage.py test`; the live pieces run only
when explicitly requested.

## Layout

```
evaluation/
  retrieval/
    questions.json          labelled retrieval dataset (fixed; do not tune)
    results/
      <model>-d<dim>.json   machine-readable evaluation results
  SPRINT26_PROVIDER_NOTES.md
```

`questions.json` is scored against the **synthetic fixture corpus**
(`knowledge/tests/fixtures.py`) inside a throwaway test database - never
production data. Categories: `RELEVANT`, `PARAPHRASE`,
`NO_ANSWER_IN_KB`, `IRRELEVANT`, `ADVERSARIAL`; tags cover money, dates,
periods, member and circle information.

## Offline (development provider)

```
OSUSU_EVALUATION_OUTPUT_DIR=evaluation/retrieval/results \
  python manage.py test knowledge.tests.test_retrieval_threshold.HashingEvaluationTests
```

Writes `results/hashing-lexical-v2-d4096.json`. These numbers describe the
local lexical stand-in only and **must not** be used for OpenAI.

## Live (paid; explicit opt-in)

Requires `OSUSU_LLM_API_KEY` and `OSUSU_EMBEDDING_API_KEY` in the
environment. The tests fail (not skip) if requested without keys, never
print keys, and touch only the throwaway test database.

```
OSUSU_RUN_EXTERNAL_AI_TESTS=true \
OSUSU_EVALUATION_OUTPUT_DIR=evaluation/results-live \
  python manage.py test \
    services.llm.test_external_providers \
    knowledge.tests.test_retrieval_threshold.OpenAIRetrievalEvaluationLive \
    knowledge.tests.test_rag_pipeline.AssistantLiveValidation
```

Outputs:

- `retrieval/text-embedding-3-small-d1536.json` - score distributions,
  selected threshold, false positives/negatives, provisional reasons;
- `assistant-validation-<llm>-<embedding>-d<dim>.json` - provider checks,
  retrieval summary, pipeline scenarios A-G, refusal observations. This
  is the file `OSUSU_ASSISTANT_VALIDATION_REPORT` must point to.

Optional live Redis check (a disposable Redis database):

```
OSUSU_RUN_REDIS_TESTS=true OSUSU_RATE_LIMIT_REDIS_URL=redis://localhost:6379/15 \
  python manage.py test services.llm.test_rate_limiter.LiveRedisRateLimiterTests
```

## Threshold rule

Implemented in `services/knowledge/retrieval_evaluation.py`:

- positives: best expected-document score within the pipeline's top-5
  for each `relevant` question; negatives: top-1 score of each `none`
  question (`unconstrained` questions are reported, not used);
- separable: midpoint of the gap; overlapping: `max(negative)` (zero
  false positives, recall cost reported);
- **provisional** unless live, >= 100 relevant and >= 50 negative
  questions, margin >= 0.05, and no relevant question missed.

The current dataset (58 questions: 28 relevant, 14 negative, 16 unconstrained) is deliberately too small to produce a
non-provisional threshold, so the readiness gate stays closed until a
larger labelled set is evaluated live.

## Enabling the paid assistant

`python manage.py assistant_readiness` lists every gate. The assistant is
served only when all pass; a provisional threshold or a report that does
not match the configured models keeps it disabled (503).
