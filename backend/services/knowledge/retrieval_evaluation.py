"""
Retrieval evaluation and reproducible similarity-threshold selection.

Pure logic: no database, no network. The caller supplies a `search`
function that returns the UNFILTERED ranked results for one question
(threshold disabled), so the same code evaluates the local hashing
provider offline and the real OpenAI model in the opt-in live run.

Threshold rule (deterministic, conservative):
  positives = for each 'relevant' question, the best score of an
              expected-document chunk within the pipeline's top-k
              (a question with no expected chunk in the top-k is a
              retrieval miss at ANY threshold).
  negatives = for each 'none' question, its top-1 score.
  - separable (max(neg) < min(pos)): the midpoint, rounded to 3 decimals
    but kept strictly inside the gap.
  - overlapping: max(neg) - zero false positives, at the cost of the
    false negatives it causes (refusing is safer than grounding an
    answer on unrelated evidence).
Retrieval keeps chunks with score > threshold.

A threshold is PROVISIONAL unless the dataset is large enough, the gap
is wide enough, nothing is missed and the run used a live model. Small
datasets never produce a production threshold.
"""

import hashlib
import json
import statistics
from dataclasses import dataclass
from pathlib import Path


CATEGORIES = (
    "RELEVANT",
    "PARAPHRASE",
    "NO_ANSWER_IN_KB",
    "IRRELEVANT",
    "ADVERSARIAL",
)
EXPECTED_RETRIEVAL = ("relevant", "none", "unconstrained")

REPORT_VERSION = 1

# Evidence required before a threshold may be called non-provisional.
MIN_POSITIVES = 100
MIN_NEGATIVES = 50
MIN_MARGIN = 0.05


class EvaluationDatasetError(ValueError):
    pass


@dataclass(frozen=True)
class Hit:
    score: float
    document_type: str
    circle_id: str


def load_dataset(path):
    raw = Path(path).read_bytes()
    data = json.loads(raw)

    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise EvaluationDatasetError("Dataset has no questions.")

    seen = set()
    for q in questions:
        qid = q.get("id")
        if not qid or qid in seen:
            raise EvaluationDatasetError(f"Missing or duplicate id: {qid!r}")
        seen.add(qid)

        if q.get("category") not in CATEGORIES:
            raise EvaluationDatasetError(f"{qid}: unknown category.")
        if q.get("expected_retrieval") not in EXPECTED_RETRIEVAL:
            raise EvaluationDatasetError(f"{qid}: unknown expected_retrieval.")
        if not isinstance(q.get("question"), str) or not q["question"].strip():
            raise EvaluationDatasetError(f"{qid}: empty question.")
        if q["expected_retrieval"] == "relevant" and not q.get(
            "expected_document_types"
        ):
            raise EvaluationDatasetError(
                f"{qid}: relevant questions need expected_document_types."
            )

    data["sha256"] = hashlib.sha256(raw).hexdigest()
    return data


def _distribution(values):
    values = sorted(values)
    if not values:
        return {"count": 0}

    def pct(p):
        index = min(len(values) - 1, max(0, round(p * (len(values) - 1))))
        return round(values[index], 4)

    return {
        "count": len(values),
        "min": round(values[0], 4),
        "p10": pct(0.10),
        "median": round(statistics.median(values), 4),
        "p90": pct(0.90),
        "max": round(values[-1], 4),
    }


def score_questions(dataset, search, *, scope_circle_id, pipeline_top_k):
    """
    `search(question) -> list[Hit]` ranked, unfiltered. Returns one record
    per question. Any hit outside the scoped circle is recorded as a
    scope violation (it must never happen).
    """
    records = []
    for q in dataset["questions"]:
        hits = list(search(q["question"]))
        expected = set(q.get("expected_document_types") or ())
        top = hits[:pipeline_top_k]

        expected_scores = [h.score for h in top if h.document_type in expected]
        expected_rank = next(
            (i for i, h in enumerate(top, start=1) if h.document_type in expected),
            None,
        )

        records.append({
            "id": q["id"],
            "category": q["category"],
            "tags": q.get("tags", []),
            "question": q["question"],
            "expected_retrieval": q["expected_retrieval"],
            "expected_document_types": sorted(expected),
            "top1_score": round(hits[0].score, 6) if hits else None,
            "top1_document_type": hits[0].document_type if hits else None,
            "top1_is_expected": bool(hits and hits[0].document_type in expected),
            "best_expected_score": (
                round(max(expected_scores), 6) if expected_scores else None
            ),
            "first_expected_rank": expected_rank,
            "top_k": [
                {"score": round(h.score, 6), "document_type": h.document_type}
                for h in top
            ],
            "scope_violations": sum(
                1 for h in hits if h.circle_id != str(scope_circle_id)
            ),
        })

    return records


def _inside_gap(low, high):
    midpoint = (low + high) / 2
    rounded = round(midpoint, 3)
    return rounded if low < rounded < high else midpoint


def select_threshold(records):
    positives = [
        r["best_expected_score"] for r in records
        if r["expected_retrieval"] == "relevant"
        and r["best_expected_score"] is not None
    ]
    misses = [
        r["id"] for r in records
        if r["expected_retrieval"] == "relevant"
        and r["best_expected_score"] is None
    ]
    negatives = [
        r["top1_score"] if r["top1_score"] is not None else -1.0
        for r in records if r["expected_retrieval"] == "none"
    ]

    if not positives or not negatives:
        raise EvaluationDatasetError(
            "Need at least one relevant and one 'none' question."
        )

    max_negative = max(negatives)
    min_positive = min(positives)
    separable = max_negative < min_positive

    if separable:
        threshold = _inside_gap(max_negative, min_positive)
        rule = "midpoint of the gap between max(negative) and min(positive)"
    else:
        threshold = max_negative
        rule = "max(negative): zero false positives, overlap costs recall"

    return {
        "threshold": round(threshold, 6),
        "rule": rule,
        "separable": separable,
        "max_negative": round(max_negative, 6),
        "min_positive": round(min_positive, 6),
        "margin": round(min_positive - max_negative, 6),
        "retrieval_misses_at_any_threshold": misses,
    }


def apply_threshold(records, threshold):
    """False positives/negatives when keeping scores > threshold."""
    false_positives = [
        r["id"] for r in records
        if r["expected_retrieval"] == "none"
        and r["top1_score"] is not None and r["top1_score"] > threshold
    ]
    false_negatives = [
        r["id"] for r in records
        if r["expected_retrieval"] == "relevant"
        and not (
            r["best_expected_score"] is not None
            and r["best_expected_score"] > threshold
        )
    ]
    unconstrained_retrieving = [
        r["id"] for r in records
        if r["expected_retrieval"] == "unconstrained"
        and r["top1_score"] is not None and r["top1_score"] > threshold
    ]
    return {
        "threshold": threshold,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "unconstrained_with_evidence": unconstrained_retrieving,
    }


def provisional_reasons(records, selection, *, live):
    positives = sum(r["expected_retrieval"] == "relevant" for r in records)
    negatives = sum(r["expected_retrieval"] == "none" for r in records)
    reasons = []

    if not live:
        reasons.append("not measured with a live production embedding model")
    if positives < MIN_POSITIVES:
        reasons.append(f"only {positives} relevant questions (< {MIN_POSITIVES})")
    if negatives < MIN_NEGATIVES:
        reasons.append(f"only {negatives} negative questions (< {MIN_NEGATIVES})")
    if not selection["separable"]:
        reasons.append("relevant and irrelevant scores overlap")
    elif selection["margin"] < MIN_MARGIN:
        reasons.append(
            f"margin {selection['margin']:.4f} is below {MIN_MARGIN}"
        )
    if selection["retrieval_misses_at_any_threshold"]:
        reasons.append("some relevant questions miss at any threshold")
    if any(r["scope_violations"] for r in records):
        reasons.append("cross-circle results observed")

    return reasons


def build_report(
    dataset,
    records,
    *,
    provider,
    live,
    pipeline_top_k,
    generated_at,
    compare_thresholds=(),
):
    selection = select_threshold(records)
    reasons = provisional_reasons(records, selection, live=live)

    def scores(predicate, field="top1_score"):
        return [
            r[field] for r in records
            if predicate(r) and r[field] is not None
        ]

    categories = {}
    for r in records:
        categories[r["category"]] = categories.get(r["category"], 0) + 1

    return {
        "report_version": REPORT_VERSION,
        "generated_at": generated_at,
        "live": bool(live),
        "dataset": {
            "version": dataset.get("dataset_version"),
            "sha256": dataset["sha256"],
            "size": len(records),
            "categories": categories,
            "corpus": dataset.get("corpus"),
        },
        "embedding": {
            "provider": provider.name,
            "model": provider.model,
            "dimension": provider.dimension,
            "embedding_version": provider.embedding_version,
            "similarity": "cosine",
        },
        "pipeline_top_k": pipeline_top_k,
        "distributions": {
            "relevant_best_expected": _distribution(scores(
                lambda r: r["expected_retrieval"] == "relevant",
                "best_expected_score",
            )),
            "relevant_top1": _distribution(scores(
                lambda r: r["expected_retrieval"] == "relevant",
            )),
            "negative_top1": _distribution(scores(
                lambda r: r["expected_retrieval"] == "none",
            )),
            "unconstrained_top1": _distribution(scores(
                lambda r: r["expected_retrieval"] == "unconstrained",
            )),
        },
        "top1_accuracy": {
            "relevant": sum(
                r["top1_is_expected"] for r in records
                if r["expected_retrieval"] == "relevant"
            ),
            "of": sum(r["expected_retrieval"] == "relevant" for r in records),
        },
        "scope_violations": sum(r["scope_violations"] for r in records),
        "threshold_selection": {
            **selection,
            "at_selected": apply_threshold(records, selection["threshold"]),
            "provisional": bool(reasons),
            "provisional_reasons": reasons,
        },
        "comparisons": [
            apply_threshold(records, t) for t in compare_thresholds
        ],
        "questions": records,
    }


def write_report(report, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    e = report["embedding"]
    path = directory / f"{e['model']}-d{e['dimension']}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n")
    return path
