# Provider verification notes (Sprint 26)

Verified **2026-09-30** against official documentation and the installed
SDKs. Re-verify before relying on these; providers change them.

Installed SDKs: `anthropic` 1.9.0 everywhere; `openai` 3.20.0 (project
venv, Python 3.14.0), 3.22.1 (fresh isolated venv, Python 3.12.7), 2.20.0
(Anaconda base env); `redis` 8.1.0.

## Anthropic (Messages API)

Sources: platform.claude.com/docs (models overview, pricing
`/about-claude/pricing`, migration guide for Claude Opus 5, refusals and
fallback), privacy.claude.com (retention, training).

| Item | Finding | Effect on Osusu |
|---|---|---|
| Model id | `claude-opus-5` is current and valid (no date suffix). `claude-opus-5-5` is launching. | Default unchanged; `OSUSU_LLM_MODEL` is validated against `claude-[a-z0-9-]+`. |
| Structured output | `output_config.format` with `json_schema` is GA (old `output_format` deprecated). | Unchanged. |
| Thinking | On `claude-opus-5` thinking is **on by default** (adaptive) when `thinking` is omitted. Raw thinking is never returned. | We never send `thinking`; see budget below. |
| `max_tokens` | A **hard cap on thinking plus answer text**. Above ~16K the SDK needs streaming (HTTP timeouts). | Budget reduced from 16000 to **4096** (allowed 1024-16000); truncation fails closed. |
| Effort | `output_config.effort` (`low`..`max`, default `high`) is the primary cost/depth lever; low/medium are strong on Opus 5. | New `OSUSU_LLM_EFFORT`, default `medium` (allowed low/medium/high). |
| Refusals | HTTP 200 with `stop_reason: "refusal"` (+ `stop_details`). `fallbacks: "default"` with beta `server-side-fallback-2026-07-01` re-runs a declined request server-side; `usage.iterations` contains a `fallback_message` entry and `content` a `fallback` block when it happened. | Refusal -> `LLMRefusal` (an `LLMProviderError`, 502, no answer). Text before a `fallback` block is discarded. `fallback_used` recorded for observability only. |
| SDK errors | 1.x adds `OverloadedError` (529), `ServiceUnavailableError` (503), `DeadlineExceededError` (504), `RequestTooLargeError` (413) as **direct `APIStatusError` subclasses (not `InternalServerError`)**, plus `CredentialsError` which is **not** an `APIError`. | **Bug fixed**: 503/529 were mapped to "rejected the request" (502) instead of unavailable (503); 504 now maps to timeout; any other `AnthropicError` maps to a fixed "unavailable" message instead of escaping. |
| Retries / timeout | Default `max_retries=2` (retries 408/409/429/5xx and connection errors); timeouts are retried, so wall clock can reach `timeout x (max_retries + 1)`. | With `OSUSU_LLM_TIMEOUT_SECONDS=60`, worst case is ~180 s per request - documented; consider lowering after live latency data. |
| Pricing | Claude Opus 5: $5 / MTok input, $25 / MTok output (thinking billed as output). | Worst-case output per request: 4096 x $25/M = **$0.10** (was $0.40 at 16000). |
| Data | API inputs/outputs are deleted within 30 days by default (exceptions apply); commercial API data is **not used for training by default**. Opus 5 is not a "Covered Model" requiring 30-day retention (Fable 5.x is). | Only authorized, allowlisted evidence is sent (unchanged). |

## OpenAI (Embeddings API)

Sources: developers.openai.com/api/docs (guides/embeddings,
models/text-embedding-3-small, guides/your-data).

| Item | Finding | Effect on Osusu |
|---|---|---|
| Model | `text-embedding-3-small`, 1536 dimensions by default; `dimensions` may shorten it; max 8192 input tokens. | Model allowlist + dimension <= native size now validated at construction. |
| Similarity | Vectors are normalized to length 1 (cosine == dot product). | Metric remains cosine. |
| Request | `client.embeddings.create(input=[...], model=..., dimensions=...)`. | Unchanged. |
| Pricing | $0.02 / 1M tokens. | Negligible at circle scale. |
| Data | `/v1/embeddings`: not used for training; abuse-monitoring retention 30 days; ZDR-eligible. | - |
| SDK errors | Typed `APIStatusError` hierarchy plus other `OpenAIError`s (e.g. response validation). | Catch-all `OpenAIError` -> fixed "unavailable" message. |

## Dependency conflict (`idna`)

`pip check` in the shared Anaconda base environment (Python 3.12.7)
reports `aider-chat 0.86.2 has requirement idna==3.11, but you have idna
3.20`. `aider-chat` is a global developer CLI, not an Osusu dependency;
`idna` 3.20 came in with `httpx2` (required by `anthropic` 1.x). The same
base env also has unrelated conflicts (streamlit, gensim, s3fs).

- Osusu itself does not import `aider-chat`; `idna` minor releases are
  backwards compatible for Osusu's use (hostname encoding inside httpx2).
- The project venv (Python 3.14) reports **no broken requirements**.
- A fresh, isolated Python 3.12.7 venv built only from
  `requirements.txt` also reports no broken requirements (see Sprint 26
  report) - so the project is reproducible without the global env.
- The fresh venv resolved newer versions than the existing one (Django
  6.1.1 vs 6.1, openai 3.22.1 vs 3.20.0): `requirements.txt` uses bounded
  ranges, so installs drift over time. Recommendation: add a lock file
  (e.g. pip-tools `requirements.lock`) per supported Python version.
- Nothing was downgraded. Recommendation: run Osusu from its own venv,
  not the Anaconda base env, and give aider its own environment
  (e.g. `pipx install aider-chat`) if the pin matters to it.
