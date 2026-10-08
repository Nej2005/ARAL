/** Drives processing: the backend does one step per POST .../process; we keep calling until done.
 *
 * One loop per document / exam, shared across components (the Set below), so opening the same
 * reviewer in two places never doubles the Gemini calls.
 */

import type { QueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { api, ApiError } from "../api/client";
import { keys } from "../api/hooks";
import type { DocumentSummary, Exam } from "../api/types";

const running = new Set<string>();
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export const docPending = (s: string | undefined) => s === "uploaded" || s === "extracting";

export function driveDocument(qc: QueryClient, id: string): void {
  const key = `doc:${id}`;
  if (running.has(key)) return;
  running.add(key);
  void (async () => {
    let failures = 0;
    try {
      for (let i = 0; i < 400; i++) {
        let d: DocumentSummary;
        try {
          d = await api.post<DocumentSummary>(`/documents/${id}/process`);
          failures = 0;
        } catch (e) {
          // 401 = passcode sheet is open; network = backend restarting. Wait and try again.
          if (e instanceof ApiError && e.status >= 400 && e.status !== 401 && e.status !== 409) return;
          if (++failures > 100) return;
          await sleep(3000);
          continue;
        }
        qc.setQueryData(keys.document(id), d);
        void qc.invalidateQueries({ queryKey: ["reviewer"] });
        void qc.invalidateQueries({ queryKey: keys.reviewers });
        if (!docPending(d.status)) return;
        if (d.busy) await sleep(2500); // another tab/request holds the step
      }
    } finally {
      running.delete(key);
    }
  })();
}

/** Call from a screen that shows these documents; pending ones get driven. */
export function useDriveDocuments(qc: QueryClient, docs: { id: string; status: string }[] | undefined): void {
  const pendingKey = (docs ?? []).filter((d) => docPending(d.status)).map((d) => d.id).join(",");
  useEffect(() => {
    if (!pendingKey) return;
    for (const id of pendingKey.split(",")) driveDocument(qc, id);
  }, [pendingKey, qc]);
}

export async function driveExam(qc: QueryClient, id: string): Promise<Exam> {
  const key = `exam:${id}`;
  if (running.has(key)) {
    // Someone else is driving it; wait for the cache to settle.
    for (let i = 0; i < 600; i++) {
      await sleep(500);
      const e = qc.getQueryData<Exam>(keys.exam(id));
      if (e && e.status !== "generating") return e;
    }
    throw new ApiError(0, "TIMEOUT", "Exam took too long");
  }
  running.add(key);
  try {
    let failures = 0;
    for (let i = 0; i < 200; i++) {
      let e: Exam;
      try {
        e = await api.post<Exam>(`/exams/${id}/process`);
        failures = 0;
      } catch (err) {
        if (err instanceof ApiError && err.status >= 400 && err.status !== 401 && err.status !== 409) throw err;
        if (++failures > 60) throw err;
        await sleep(3000);
        continue;
      }
      qc.setQueryData(keys.exam(id), e);
      if (e.status !== "generating") {
        void qc.invalidateQueries({ queryKey: keys.reviewerExams(e.reviewer_id) });
        void qc.invalidateQueries({ queryKey: keys.reviewer(e.reviewer_id) });
        void qc.invalidateQueries({ queryKey: keys.reviewers });
        return e;
      }
      await sleep(e.busy ? 2500 : 500);
    }
    throw new ApiError(0, "TIMEOUT", "Exam took too long");
  } finally {
    running.delete(key);
  }
}
