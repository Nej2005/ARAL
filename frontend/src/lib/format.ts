import { ApiError } from "../api/client";
import type { QuestionType } from "../api/types";

export const TYPE_LABEL: Record<QuestionType, string> = {
  mcq: "Multiple choice",
  true_false: "True / False",
  identification: "Identification",
};

export const TYPE_SHORT: Record<QuestionType, string> = { mcq: "MC", true_false: "TF", identification: "ID" };

/** Backend error codes -> the one-line messages from FRONTEND.md §8. */
const MESSAGES: Record<string, string> = {
  UNSUPPORTED_FILE_TYPE: "Only PDF, PPTX or PPT",
  FILE_TOO_LARGE: "Over 25 MB",
  NO_EXTRACTABLE_TEXT: "No text found (scanned PDF?)",
  PPT_CONVERSION_UNAVAILABLE: "Save as .pptx, or install LibreOffice",
  PPT_CONVERSION_FAILED: "Could not convert this .ppt",
  NO_SOURCE_ITEMS: "No definitions or facts found",
  LLM_QUOTA_EXCEEDED: "Gemini daily limit reached · try later",
  LLM_ERROR: "Gemini didn't respond",
  EXTRACTION_FAILED: "Could not read this file",
  GENERATION_FAILED: "Could not build the exam",
  INTERRUPTED: "Interrupted · reprocess to continue",
  DOCUMENTS_NOT_READY: "Waiting for a file to finish reading",
  ALL_ITEMS_REVIEWED: "All items reviewed",
  INVALID_SCOPE: "Check the slide numbers",
  EMPTY_REVIEWER: "Add a file first",
  DOCUMENT_IN_USE: "File is used by a reviewer",
  ALREADY_ANSWERED: "Already answered",
  ATTEMPT_COMPLETED: "Exam already finished",
  ATTEMPT_NOT_FINISHED: "Finish the exam first",
  NO_MISTAKES: "Nothing to retry",
  EXAM_NOT_READY: "Exam not ready",
  OFFLINE: "Backend not running (port 8000)",
  NOT_FOUND: "Not found",
};

export function describeError(e: unknown): string {
  if (e instanceof ApiError) return MESSAGES[e.code] ?? e.message;
  if (e instanceof Error) return e.message;
  return "Something went wrong";
}

export function errorCode(e: unknown): string | null {
  return e instanceof ApiError ? e.code : null;
}

export function pad(n: number): string {
  return String(n).padStart(2, "0");
}

export function pct(a: number, b: number): number {
  return b ? Math.round((100 * a) / b) : 0;
}

export function shortDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
