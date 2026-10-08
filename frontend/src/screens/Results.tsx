import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { keys, useExam, useSummary } from "../api/hooks";
import type { AttemptStart, Exam, SummaryCard } from "../api/types";
import Header from "../components/Header";
import Icon from "../components/Icon";
import Prompt from "../components/Prompt";
import { describeError, errorCode, pad } from "../lib/format";
import { useToast } from "../lib/toast";
import ExportSheet from "../sheets/ExportSheet";

function ReviewItem({ card, kind }: { card: SummaryCard; kind: "wrong" | "skipped" }) {
  return (
    <details>
      <summary>
        <Icon name={kind === "wrong" ? "x" : "dash"} />
        <Prompt text={card.prompt} className="qprompt" />
        <Icon name="chev" />
      </summary>
      <div className="body">
        <p>
          Answer: <b>{card.correct_answer.text}</b>
          {card.your_answer?.text && <span className="muted"> · yours: {card.your_answer.text}</span>}
        </p>
        {card.changed_span && (
          <p className="diff"><del>{card.changed_span.to}</del> → <ins>{card.changed_span.from}</ins></p>
        )}
        <p>{card.why}</p>
        {card.why_yours_is_wrong && !card.changed_span && <p className="why2">{card.why_yours_is_wrong}</p>}
        <p className="muted">{card.source.filename?.replace(/\.[^.]+$/, "")} · {card.source.location}</p>
      </div>
    </details>
  );
}

export default function Results() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const s = useSummary(id);
  const exam = useExam(s.data?.exam_id);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    if (s.isError && errorCode(s.error) === "ATTEMPT_NOT_FINISHED") nav(`/attempts/${id}`, { replace: true });
  }, [s.isError, s.error, id, nav]);

  const invalidate = () => {
    if (s.data) {
      qc.invalidateQueries({ queryKey: keys.exam(s.data.exam_id) });
      qc.invalidateQueries({ queryKey: keys.reviewers });
    }
    if (exam.data) {
      qc.invalidateQueries({ queryKey: keys.reviewer(exam.data.reviewer_id) });
      qc.invalidateQueries({ queryKey: keys.reviewerExams(exam.data.reviewer_id) });
    }
  };

  const retry = useMutation({
    mutationFn: () => api.post<AttemptStart>(`/attempts/${id}/retry-mistakes`),
    onSuccess: (a) => { invalidate(); nav(`/attempts/${a.attempt_id}`); },
    onError: (e) => toast(describeError(e)),
  });
  const restart = useMutation({
    mutationFn: () => api.post<AttemptStart>(`/exams/${s.data!.exam_id}/attempts`),
    onSuccess: (a) => { invalidate(); nav(`/attempts/${a.attempt_id}`); },
    onError: (e) => toast(describeError(e)),
  });
  const newSet = useMutation({
    mutationFn: () => api.post<Exam>(`/exams/${s.data!.exam_id}/next-set`),
    onSuccess: (e) => { invalidate(); nav(`/exams/${e.id}/making`); },
    onError: (e) => toast(describeError(e)),
  });

  const d = s.data;
  const miss = d?.retry_mistakes.count ?? 0;
  const left = d?.next_set.unused_items ?? 0;
  const busy = retry.isPending || restart.isPending || newSet.isPending;
  const strip = d
    ? [
        ...Array.from({ length: d.correct_count }, () => "ok"),
        ...d.wrong_cards.map(() => "bad"),
        ...d.skipped_cards.map(() => "un"),
      ]
    : [];

  return (
    <div id="app">
      <Header back={{ to: exam.data ? `/reviewers/${exam.data.reviewer_id}` : "/", label: "Reviewer" }} />
      <main className="wrap">
        {s.isError && errorCode(s.error) !== "ATTEMPT_NOT_FINISHED" && <p className="err"><Icon name="warn" />{describeError(s.error)}</p>}
        {s.isLoading && <p className="loading">loading…</p>}
        {d && (
          <>
            <p className="label">
              Attempt {d.attempt_no}{d.kind === "mistakes" ? " · mistakes" : ""}
            </p>
            <div className="score">{pad(d.correct_count)}<span>/{pad(d.total)}</span></div>
            <div className="strip" role="img" aria-label={`${d.correct_count} right, ${d.wrong_cards.length} wrong, ${d.skipped} skipped`}>
              {strip.map((k, i) => <i key={i} className={k} />)}
            </div>
            <div className="res-actions">
              <button className={`btn ${miss ? "primary" : ""}`} disabled={!miss || busy} onClick={() => retry.mutate()}>
                <Icon name="retry" />Retry {miss || ""} mistake{miss === 1 ? "" : "s"}
              </button>
              <button className="btn" disabled={busy} onClick={() => restart.mutate()}>
                <Icon name="restart" />Restart
              </button>
              <button className={`btn ${miss ? "" : "primary"}`} disabled={!left || busy} onClick={() => newSet.mutate()}>
                <Icon name="plus" />New set
              </button>
            </div>
            {!left && <p className="muted small" style={{ marginTop: 8 }}>All items reviewed · reset progress in the reviewer's <Icon name="more" /> menu</p>}
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn ghost" onClick={() => setExporting(true)}><Icon name="down" />Export</button>
            </div>
            {miss > 0 && (
              <>
                <div className="ascii" aria-hidden="true">{"*".repeat(260)}</div>
                <div className="sec-head"><h2 className="sec"><span className="hl">Review</span></h2><span className="muted small">{miss}</span></div>
                <div className="review">
                  {d.wrong_cards.map((c) => <ReviewItem key={c.question_id} card={c} kind="wrong" />)}
                  {d.skipped_cards.map((c) => <ReviewItem key={c.question_id} card={c} kind="skipped" />)}
                </div>
              </>
            )}
          </>
        )}
      </main>
      {exporting && d && <ExportSheet kind="exam" id={d.exam_id} onClose={() => setExporting(false)} />}
    </div>
  );
}
