"""
Deterministic, structure-aware chunking.

Knowledge documents are written as paragraphs separated by blank lines,
with "## " section headings. The chunker packs WHOLE paragraphs into
chunks; only a paragraph larger than a chunk is split, at line
boundaries (repeating its heading), and only a single over-long line is
split at word boundaries. Overlap re-uses whole trailing lines. Every
chunk is prefixed with the document title so it stands alone.

Pure functions only: no database access, no network, no LLM.
"""

from dataclasses import dataclass


DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 200
MIN_CHUNK_SIZE = 200


@dataclass(frozen=True)
class TextChunk:
    index: int
    count: int
    content: str


def chunk_text(
    *,
    title,
    content,
    chunk_size=DEFAULT_CHUNK_SIZE,
    chunk_overlap=DEFAULT_CHUNK_OVERLAP,
):
    if chunk_size < MIN_CHUNK_SIZE:
        raise ValueError(f"chunk_size must be at least {MIN_CHUNK_SIZE}.")

    if not 0 <= chunk_overlap < chunk_size // 2:
        raise ValueError(
            "chunk_overlap must be >= 0 and less than half of chunk_size."
        )

    prefix = f"{title}\n\n"
    budget = chunk_size - len(prefix)

    if budget < MIN_CHUNK_SIZE // 2:
        raise ValueError("Title is too long for the chunk size.")

    blocks = []
    for paragraph in _paragraphs(content):
        blocks.extend(_fit_paragraph(paragraph, budget))

    bodies = _pack(blocks, budget, chunk_overlap)

    return [
        TextChunk(index=i, count=len(bodies), content=prefix + body)
        for i, body in enumerate(bodies)
    ]


def _paragraphs(content):
    return [
        paragraph.strip("\n")
        for paragraph in content.strip().split("\n\n")
        if paragraph.strip()
    ]


def _fit_paragraph(paragraph, budget):
    """Split an over-sized paragraph into line groups under budget."""
    if len(paragraph) <= budget:
        return [paragraph]

    lines = paragraph.split("\n")
    heading = lines[0] if lines[0].startswith("## ") else None
    body_lines = lines[1:] if heading else lines

    pieces = []
    current = [heading] if heading else []

    for line in body_lines:
        for part in _fit_line(line, budget - len(heading or "") - 1):
            candidate = "\n".join(current + [part])
            has_body = len(current) > (1 if heading else 0)

            if len(candidate) > budget and has_body:
                pieces.append("\n".join(current))
                current = ([heading] if heading else []) + [part]
            else:
                current.append(part)

    if current and len(current) > (1 if heading else 0):
        pieces.append("\n".join(current))

    return pieces


def _fit_line(line, budget):
    if len(line) <= budget:
        return [line]

    parts, current = [], ""
    for word in line.split(" "):
        candidate = f"{current} {word}".strip()
        if len(candidate) > budget and current:
            parts.append(current)
            current = word
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _pack(blocks, budget, overlap):
    bodies = []
    current = ""

    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block

        if len(candidate) <= budget or not current:
            current = candidate
            continue

        bodies.append(current)

        tail = _overlap_tail(current, overlap)
        with_tail = f"{tail}\n\n{block}" if tail else block
        current = with_tail if len(with_tail) <= budget else block

    if current:
        bodies.append(current)

    return bodies


def _overlap_tail(text, overlap):
    """Whole trailing lines totalling at most `overlap` characters."""
    if overlap == 0:
        return ""

    kept = []
    size = 0
    for line in reversed(text.split("\n")):
        if not line.strip():
            continue
        if size + len(line) + 1 > overlap:
            break
        kept.append(line)
        size += len(line) + 1

    return "\n".join(reversed(kept))
