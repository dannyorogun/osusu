/**
 * Shared API shapes. Django REST Framework conventions:
 * - DecimalField values arrive as strings ("50.00"); never do arithmetic
 *   on them in the browser - the backend is authoritative.
 * - Datetimes are ISO 8601 strings; UUIDs are strings.
 */

/** A decimal amount exactly as serialized by Django, e.g. "50.00". */
export type DecimalString = string;

/** ISO 8601 datetime string. */
export type IsoDateTime = string;

export type Uuid = string;

/**
 * Error bodies the backend actually returns:
 * - DRF defaults: {"detail": "..."} (401/403/404/405)
 * - serializer validation: {"field": ["msg", ...], "non_field_errors": [...]}
 * - domain errors from circle/invitation views: {"error": "...", ...}
 * - assistant/risk: {"detail": "...", "code": "...", "request_id"?: "..."}
 */
export type ApiErrorBody = {
  detail?: string;
  code?: string;
  error?: string;
  request_id?: string;
  [field: string]: unknown;
};

/** Field-level validation messages keyed by backend field name. */
export type FieldErrors = Record<string, string[]>;
