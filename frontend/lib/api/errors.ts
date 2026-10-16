import type { ApiErrorBody, FieldErrors } from "@/types/api";

export type ApiErrorKind =
  | "network" // request never reached / no response
  | "validation" // 400 with field or domain messages
  | "unauthenticated" // 401 after the one refresh attempt
  | "forbidden" // 403
  | "not_found" // 404
  | "rate_limited" // 429
  | "unavailable" // 502/503/504
  | "server" // other 5xx
  | "unknown";

/** Messages shown to users. Never raw backend exception text. */
const MESSAGES: Record<ApiErrorKind, string> = {
  network: "We couldn't reach Osusu. Check your connection and try again.",
  validation: "Please check the highlighted details and try again.",
  unauthenticated: "Your session has ended. Please sign in again.",
  forbidden: "You don't have access to this.",
  not_found: "We couldn't find what you were looking for.",
  rate_limited: "Too many requests. Please wait a moment and try again.",
  unavailable: "This service is temporarily unavailable. Please try again later.",
  server: "Something went wrong on our side. Please try again later.",
  unknown: "Something went wrong. Please try again.",
};

function kindForStatus(status: number): ApiErrorKind {
  if (status === 0) return "network";
  if (status === 400) return "validation";
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 429) return "rate_limited";
  if (status === 502 || status === 503 || status === 504) return "unavailable";
  if (status >= 500) return "server";
  return "unknown";
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === "string");
}

/**
 * Extract DRF serializer messages ({"field": ["msg"]}). Only 400 bodies are
 * trusted for this: they are validation messages written for end users.
 */
export function parseFieldErrors(body: unknown): FieldErrors {
  if (!body || typeof body !== "object" || Array.isArray(body)) return {};
  const errors: FieldErrors = {};
  for (const [field, value] of Object.entries(body)) {
    if (isStringArray(value)) {
      errors[field] = value;
    } else if (field === "error" && typeof value === "string") {
      // Circle/invitation domain errors: {"error": "..."}.
      errors.non_field_errors = [value];
    }
  }
  return errors;
}

export class ApiError extends Error {
  readonly status: number;
  readonly kind: ApiErrorKind;
  /** Backend machine code when provided (e.g. "assistant_unavailable"). */
  readonly code: string | null;
  readonly fieldErrors: FieldErrors;
  readonly requestId: string | null;
  /**
   * The parsed body of a 400 response (domain details such as the failed
   * financial-lock checks); empty for every other status.
   */
  readonly details: ApiErrorBody;

  constructor(status: number, body?: unknown) {
    const kind = kindForStatus(status);
    super(MESSAGES[kind]);
    this.name = "ApiError";
    this.status = status;
    this.kind = kind;

    const parsed: ApiErrorBody =
      body && typeof body === "object" && !Array.isArray(body)
        ? (body as ApiErrorBody)
        : {};
    this.code = typeof parsed.code === "string" ? parsed.code : null;
    this.requestId =
      typeof parsed.request_id === "string" ? parsed.request_id : null;
    this.fieldErrors = kind === "validation" ? parseFieldErrors(body) : {};
    this.details = kind === "validation" ? parsed : {};
  }

  /** First message for a field, e.g. ApiError.fieldMessage("username"). */
  fieldMessage(field: string): string | undefined {
    return this.fieldErrors[field]?.[0];
  }

  /** Form-level validation messages (non_field_errors / domain errors). */
  get formMessages(): string[] {
    return this.fieldErrors.non_field_errors ?? [];
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/** A user-safe message for any thrown value. */
export function userMessage(error: unknown): string {
  if (isApiError(error)) {
    return error.formMessages[0] ?? error.message;
  }
  return MESSAGES.unknown;
}
