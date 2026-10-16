"""
Knowledge schema: versioning, hashing and deterministic formatting.

Bump KNOWLEDGE_SCHEMA_VERSION whenever document templates change. It is
part of every content hash, so a template change regenerates every
document even when the underlying data is identical.
"""

import hashlib
import json
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal


# v2 (Sprint 26): user-authored circle descriptions are collapsed to one
# "Description: " line (USER_TEXT_PREFIX) so they cannot forge headings
# or paragraphs, and figures on that line never ground an answer.
KNOWLEDGE_SCHEMA_VERSION = "knowledge-v2"

# Lines starting with this prefix hold free text typed by a user, not
# figures derived from Osusu records.
USER_TEXT_PREFIX = "Description: "
# Short enough that the chunker never splits the line (which would leave
# a continuation without the prefix).
MAX_USER_TEXT_LENGTH = 500

CURRENCY_SYMBOL = "£"  # Payments are GBP (payments.Payment.currency).

NOT_RECORDED = "not recorded"


def sha256_hex(text):
    """Stable across processes, unlike built-in hash()."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def document_hash(*, document_type, entity_type, entity_id, title, content):
    canonical = json.dumps(
        {
            "schema_version": KNOWLEDGE_SCHEMA_VERSION,
            "document_type": document_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "title": title,
            "content": content,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return sha256_hex(canonical)


def money(value):
    """Decimal -> '£1,234.50'. Never goes through float."""
    amount = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if amount < 0 else ""
    return f"{sign}{CURRENCY_SYMBOL}{abs(amount):,.2f}"


def timestamp(value):
    """Aware datetime -> '2026-01-31 14:05 UTC'; None -> 'not recorded'."""
    if value is None:
        return NOT_RECORDED
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return str(value)


def display_name(user):
    """
    A human-readable name that never exposes an email address. Falls back
    to a stable pseudonym derived from the user's id.
    """
    if user is None:
        return "Unknown member"

    full_name = f"{user.first_name} {user.last_name}".strip()
    if full_name and "@" not in full_name:
        return full_name

    if user.username and "@" not in user.username:
        return user.username

    return f"Member {str(user.pk)[:8]}"


def humanize(value):
    """'paid_on_time' -> 'paid on time'."""
    return str(value).replace("_", " ")


def with_article(word):
    """'active' -> 'an active', 'left' -> 'a left'."""
    return f"{'an' if str(word)[:1].lower() in 'aeiou' else 'a'} {word}"


def plural(count, singular, plural_form=None):
    """(1, 'transaction') -> '1 transaction'; (2, ...) -> '2 transactions'."""
    word = singular if count == 1 else (plural_form or f"{singular}s")
    return f"{count} {word}"


def sort_name(user):
    """Case-insensitive, deterministic ordering key for members."""
    return (display_name(user).casefold(), str(user.pk))
