import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import { useExam } from "../api/hooks";
import type { AttemptStart, Exam } from "../api/types";
import Header from "../components/Header";
import Icon from "../components/Icon";
import MiniBar from "../components/MiniBar";
import { driveExam } from "../lib/driver";
import { describeError } from "../lib/format";

export default function Making() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const exam = useExam(id);
  const [tick, setTick] = useState(0);
  const [driveError, setDriveError] = useState<unknown>(null);
  const started = useRef(false);
  const driven = useRef<string | null>(null);

  // A filling bar while we wait; it never reaches the end on its own.
  useEffect(() => {
    const t = window.setInterval(() => setTick((x) => Math.min(x + 1, 8)), 500);
    return () => window.clearInterval(t);
  }, []);

  // Drive the backend's processing step until the exam is ready or failed.
  useEffect(() => {
    if (driven.current === id) return;
    driven.current = id;
    setDriveError(null);
    driveExam(qc, id).catch((e) => setDriveError(e));
  }, [id, qc]);

  const start = useMutation({
    mutationFn: () => api.post<AttemptStart>(`/exams/${id}/attempts`),
    onSuccess: (a) => nav(`/attempts/${a.attempt_id}`, { replace: true }),
  });

  const retry = useMutation({
    mutationFn: () => api.post<Exam>(`/exams/${id}/next-set`),
    onSuccess: (e) => { driven.current = null; nav(`/exams/${e.id}/making`, { replace: true }); },
  });

  useEffect(() => {
    if (exam.data?.status === "ready" && !started.current) {
      started.current = true;
      start.mutate();
    }
  }, [exam.data?.status, start]);

  const e = exam.data;
  const failed = e?.status === "failed" || start.isError || retry.isError || !!driveError;
  const message = e?.status === "failed"
    ? describeError(new ApiError(0, e.error_code ?? "GENERATION_FAILED", e.error_message ?? ""))
    : describeError(driveError ?? start.error ?? retry.error);

  return (
    <div id="app">
      <Header back={{ to: e ? `/reviewers/${e.reviewer_id}` : "/", label: "Reviewer" }} />
      <main className="wrap">
        <div className="gen">
          {!failed ? (
            <>
              <h1 className="h1">Making {e?.requested_count ?? ""} questions</h1>
              <div><MiniBar value={e?.status === "ready" ? 10 : tick} total={10} /></div>
              {e && e.status === "ready" && e.shortfall > 0 && (
                <p className="muted small">Only {e.actual_count} items were left</p>
              )}
            </>
          ) : (
            <>
              <h1 className="h1">Couldn't make it</h1>
              <p className="err"><Icon name="warn" />{message}</p>
              {e?.error_message && e.status === "failed" && <p className="muted small" style={{ maxWidth: "48ch" }}>{e.error_message}</p>}
              <div className="row">
                <button className="btn primary" onClick={() => retry.mutate()} disabled={retry.isPending}>
                  <Icon name="restart" />Try again
                </button>
                <button className="btn" onClick={() => nav(e ? `/reviewers/${e.reviewer_id}` : "/")}>Back</button>
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
