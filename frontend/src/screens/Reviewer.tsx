import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { keys, useReviewer, useReviewerExams } from "../api/hooks";
import type { AttemptStart, DocumentSummary, Exam, ReviewerDetail, ReviewerDoc } from "../api/types";
import { uploadFile } from "../api/upload";
import Header from "../components/Header";
import Icon from "../components/Icon";
import MiniBar from "../components/MiniBar";
import { docPending, driveDocument, useDriveDocuments } from "../lib/driver";
import { describeError, shortDate, TYPE_SHORT } from "../lib/format";
import { useToast } from "../lib/toast";
import ConfirmSheet from "../sheets/ConfirmSheet";
import ExportSheet from "../sheets/ExportSheet";
import NewExam from "../sheets/NewExam";
import ReviewerMenu from "../sheets/ReviewerMenu";

type SheetName = "start" | "export" | "menu" | null;

export default function Reviewer() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const rv = useReviewer(id);
  const exams = useReviewerExams(id);
  const [sheet, setSheet] = useState<SheetName>(null);
  const [removing, setRemoving] = useState<ReviewerDoc | null>(null);
  const [deleting, setDeleting] = useState<{ exam: Exam; n: number } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useDriveDocuments(qc, rv.data?.documents);

  const addFiles = useMutation({
    mutationFn: async (files: File[]) => {
      const out: DocumentSummary[] = [];
      for (const f of files) {
        const d = await uploadFile(f, { reviewerId: id });
        out.push(d);
        if (docPending(d.status)) driveDocument(qc, d.id);
      }
      return out;
    },
    onSuccess: (docs) => {
      qc.invalidateQueries({ queryKey: keys.reviewer(id) });
      qc.invalidateQueries({ queryKey: keys.reviewers });
      const dup = docs.filter((d) => d.duplicate).length;
      toast(dup ? `Added · ${dup} already uploaded, reused` : docs.length > 1 ? `Added ${docs.length} files · reading…` : "Added · reading…");
    },
    onError: (e) => toast(describeError(e)),
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.reviewer(id) });
    qc.invalidateQueries({ queryKey: keys.reviewerExams(id) });
    qc.invalidateQueries({ queryKey: keys.reviewers });
  };

  const removeFile = useMutation({
    mutationFn: (docId: string) =>
      api.del<ReviewerDetail & { deleted_file: boolean; deleted_exams: number }>(`/reviewers/${id}/documents/${docId}?delete_file=true`),
    onSuccess: (res) => {
      setRemoving(null);
      refresh();
      toast(res.deleted_exams ? `File deleted · ${res.deleted_exams} exam${res.deleted_exams > 1 ? "s" : ""} removed` : res.deleted_file ? "File deleted" : "File removed");
    },
    onError: (e) => toast(describeError(e)),
  });

  const deleteExam = useMutation({
    mutationFn: (examId: string) => api.del(`/exams/${examId}`),
    onSuccess: () => {
      setDeleting(null);
      refresh();
      toast("Exam deleted");
    },
    onError: (e) => toast(describeError(e)),
  });

  const reprocess = useMutation({
    mutationFn: (docId: string) => api.post<DocumentSummary>(`/documents/${docId}/reprocess`),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: keys.reviewer(id) });
      driveDocument(qc, d.id);
      toast(d.resumed ? "Continuing…" : "Reading again…");
    },
    onError: (e) => toast(describeError(e)),
  });

  const openExam = useMutation({
    mutationFn: async (e: Exam) => {
      if (e.status === "generating") return `/exams/${e.id}/making`;
      if (e.status === "failed") throw new Error(e.error_message || "This exam failed");
      if (e.in_progress_attempt_id) return `/attempts/${e.in_progress_attempt_id}`;
      if (e.latest_attempt_id) return `/attempts/${e.latest_attempt_id}/summary`;
      const a = await api.post<AttemptStart>(`/exams/${e.id}/attempts`);
      return `/attempts/${a.attempt_id}`;
    },
    onSuccess: (to) => nav(to),
    onError: (e) => toast(describeError(e)),
  });

  const r = rv.data;
  const waiting = r?.documents.filter((d) => d.status === "uploaded" || d.status === "extracting").length ?? 0;
  const failed = r?.documents.filter((d) => d.status === "failed") ?? [];
  const canStart = !!r && r.status === "ready" && r.unused_items > 0 && r.document_count > 0;

  return (
    <div id="app">
      <Header back={{ to: "/", label: "Reviewers" }} />
      <main className="wrap">
        {rv.isError && <p className="err"><Icon name="warn" />{describeError(rv.error)}</p>}
        {rv.isLoading && <p className="loading">loading…</p>}
        {r && (
          <>
            <div className="rv-head">
              <h1 className="h1">{r.title}</h1>
              <div className="cov">
                <MiniBar value={r.used_items} total={r.item_count} slots={20} />
                <span><b>{r.used_items}</b>/{r.item_count} reviewed</span>
              </div>
            </div>
            <div className="rv-actions">
              <button className="btn primary big" disabled={!canStart} onClick={() => setSheet("start")}>
                <Icon name="play" />Start exam
              </button>
              <button className="btn big" onClick={() => setSheet("export")} disabled={r.item_count === 0}>
                <Icon name="down" /><span className="hide-xs">Export</span>
              </button>
              <button className="icon-btn boxed lg" onClick={() => setSheet("menu")} aria-label="More options">
                <Icon name="more" />
              </button>
            </div>
            {waiting > 0 && <p className="wait"><Icon name="dash" />Waiting for {waiting} file{waiting > 1 ? "s" : ""} to finish reading</p>}
            {failed.length > 0 && waiting === 0 && (
              <p className="wait"><Icon name="warn" />{failed.length} file{failed.length > 1 ? "s" : ""} failed · reprocess or remove</p>
            )}
            {r.status === "ready" && r.unused_items === 0 && r.item_count > 0 && (
              <p className="wait"><Icon name="dash" />All items reviewed · reset progress in <Icon name="more" /></p>
            )}
            <div className="ascii" aria-hidden="true">{"/".repeat(260)}</div>
            <div className="rv-grid">
              <section>
                <div className="sec-head">
                  <h2 className="sec"><span className="hl">Files</span></h2>
                  <button className="btn ghost" onClick={() => fileInput.current?.click()} disabled={addFiles.isPending}>
                    <Icon name="plus" />Add
                  </button>
                  <input
                    ref={fileInput}
                    type="file"
                    accept=".pdf,.pptx,.ppt"
                    multiple
                    hidden
                    onChange={(e) => {
                      const files = Array.from(e.target.files ?? []);
                      e.target.value = "";
                      if (files.length) addFiles.mutate(files);
                    }}
                  />
                </div>
                <div className="list">
                  {r.documents.map((d) => (
                    <div key={d.id} className="lr r-file">
                      <Icon name="file" />
                      <span className="t" style={{ fontSize: 14 }}>
                        {d.filename}
                        <br />
                        <span className="sub">{d.page_count ? `${d.page_count} ${d.page_unit}s` : d.file_type.toUpperCase()}</span>
                      </span>
                      {d.status === "ready" ? (
                        <span className="prog-cell">
                          <MiniBar value={d.used_items} total={d.item_count} /> <span className="muted">{d.used_items}/{d.item_count}</span>
                        </span>
                      ) : d.status === "failed" ? (
                        <span className="prog-cell">
                          <button className="btn ghost small" onClick={() => reprocess.mutate(d.id)} style={{ minHeight: 36, paddingInline: 8 }} title={d.error_code ?? ""}>
                            <Icon name="reset" />{d.error_code === "LLM_QUOTA_EXCEEDED" ? "Continue" : "Retry"}
                          </button>
                        </span>
                      ) : (
                        <span className="prog-cell muted">{d.steps_total ? `Reading ${Math.min(d.steps_done, d.steps_total)}/${d.steps_total}` : "Reading…"}</span>
                      )}
                      <button
                        className="icon-btn"
                        aria-label={`Remove ${d.filename}`}
                        disabled={r.document_count <= 1 || removeFile.isPending}
                        title={r.document_count <= 1 ? "A reviewer needs at least one file" : undefined}
                        onClick={() => setRemoving(d)}
                      >
                        <Icon name="x" />
                      </button>
                    </div>
                  ))}
                </div>
              </section>
              <section>
                <div className="sec-head"><h2 className="sec"><span className="hl">Exams</span></h2></div>
                {exams.data && exams.data.length === 0 && <p className="empty">No exams yet</p>}
                {exams.data && exams.data.length > 0 && (
                  <div className="list">
                    {exams.data.map((e, i) => {
                      const n = exams.data.length - i;
                      const score = e.best_score ?? e.latest_score;
                      return (
                        <div key={e.id} className="lr r-exam-row">
                          <button className="r-exam-main" onClick={() => openExam.mutate(e)} disabled={openExam.isPending}>
                            <span className="t">
                              Set {n} <span className="sub">· {e.types.map((t) => TYPE_SHORT[t]).join(" · ")}</span>
                            </span>
                            <span className="score-pill">
                              {e.status === "generating" ? "…" : e.status === "failed" ? "✗" : e.in_progress_attempt_id ? "▶" : score ? `${score.correct_count}/${score.total}` : "—"}
                            </span>
                            <span className="muted sub-cell">{shortDate(e.created_at)}</span>
                            <Icon name="chev" />
                          </button>
                          <button className="icon-btn" aria-label={`Delete set ${n}`} onClick={() => setDeleting({ exam: e, n })}>
                            <Icon name="trash" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </section>
            </div>
          </>
        )}
      </main>
      {r && sheet === "start" && <NewExam reviewer={r} onClose={() => setSheet(null)} />}
      {r && sheet === "export" && <ExportSheet kind="reviewer" id={r.id} title={r.title} onClose={() => setSheet(null)} />}
      {r && sheet === "menu" && <ReviewerMenu reviewer={r} onClose={() => setSheet(null)} />}
      {removing && (
        <ConfirmSheet
          title="Delete file?"
          confirmLabel="Delete"
          busy={removeFile.isPending}
          onConfirm={() => removeFile.mutate(removing.id)}
          onClose={() => setRemoving(null)}
        >
          <p className="confirm-name">{removing.filename}</p>
          {removing.shared ? (
            <p className="muted small">Also used by another reviewer, so it's only removed from this one.</p>
          ) : removing.exam_count > 0 ? (
            <p className="muted small">{removing.exam_count} exam{removing.exam_count > 1 ? "s" : ""} built from it will be deleted too.</p>
          ) : null}
        </ConfirmSheet>
      )}
      {deleting && (
        <ConfirmSheet
          title={`Delete set ${deleting.n}?`}
          confirmLabel="Delete"
          busy={deleteExam.isPending}
          onConfirm={() => deleteExam.mutate(deleting.exam.id)}
          onClose={() => setDeleting(null)}
        >
          <p className="muted small">
            Its {deleting.exam.actual_count} questions and scores are deleted. Those items can appear in new sets again.
          </p>
        </ConfirmSheet>
      )}
    </div>
  );
}
