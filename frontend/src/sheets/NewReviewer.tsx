import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { keys } from "../api/hooks";
import type { DocumentSummary, ReviewerDetail } from "../api/types";
import { uploadFile } from "../api/upload";
import Icon from "../components/Icon";
import Sheet from "../components/Sheet";
import { docPending, driveDocument } from "../lib/driver";
import { describeError } from "../lib/format";
import { useToast } from "../lib/toast";

interface Row {
  name: string;
  id?: string;
  duplicate?: boolean;
  error?: string;
  progress?: string;
}

export function docStateLabel(d: DocumentSummary | undefined, duplicate?: boolean): string {
  if (!d) return "Reading…";
  if (d.status === "ready") return duplicate ? "Already uploaded · reused" : "Ready";
  if (d.status === "failed") return describeError(Object.assign(new Error(d.error_message ?? ""), { code: d.error_code }));
  if (d.steps_total) return `Reading ${Math.min(d.steps_done ?? 0, d.steps_total)}/${d.steps_total}`;
  return "Reading…";
}

export default function NewReviewer({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [rows, setRows] = useState<Row[]>([]);
  const [title, setTitle] = useState("");
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const patch = (name: string, p: Partial<Row>) => setRows((r) => r.map((x) => (x.name === name ? { ...x, ...p } : x)));

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      for (const f of files) {
        setRows((r) => [...r, { name: f.name, progress: "Checking…" }]);
        try {
          const d = await uploadFile(f, {
            onProgress: (p) => patch(f.name, { progress: p.phase === "hashing" ? "Checking…" : `Uploading ${Math.round((100 * p.sent) / p.total)}%` }),
          });
          qc.setQueryData(keys.document(d.id), d);
          patch(f.name, { id: d.id, duplicate: d.duplicate, progress: undefined });
          if (docPending(d.status)) driveDocument(qc, d.id);
        } catch (e) {
          patch(f.name, { error: describeError(e), progress: undefined });
        }
      }
    },
  });

  const ids = rows.filter((r) => r.id).map((r) => r.id!);
  const docs = useQueries({
    queries: ids.map((id) => ({
      queryKey: keys.document(id),
      queryFn: () => api.get<DocumentSummary>(`/documents/${id}`),
      refetchInterval: (q: { state: { data?: DocumentSummary } }) => (docPending(q.state.data?.status) ? 4000 : false),
    })),
  });
  const statusOf = (id: string) => docs.find((d) => d.data?.id === id)?.data;

  // If the sheet is closed and reopened, keep driving anything still pending.
  useEffect(() => {
    docs.forEach((d) => d.data && docPending(d.data.status) && driveDocument(qc, d.data.id));
  }, [docs, qc]);

  const create = useMutation({
    mutationFn: () => api.post<ReviewerDetail>("/reviewers", { title: title.trim() || defaultTitle(), document_ids: ids }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: keys.reviewers });
      onClose();
      nav(`/reviewers/${r.id}`);
    },
    onError: (e) => toast(describeError(e)),
  });

  const defaultTitle = () => (rows[0]?.name ?? "New reviewer").replace(/\.[^.]+$/, "");

  const addFiles = (list: FileList | null) => {
    const files = Array.from(list ?? []).filter((f) => !rows.some((r) => r.name === f.name));
    if (files.length) upload.mutate(files);
  };

  return (
    <Sheet title="New reviewer" onClose={onClose}>
      <button
        className={`drop ${over ? "over" : ""}`}
        onClick={() => input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); addFiles(e.dataTransfer.files); }}
      >
        <Icon name="up" />
        <b>Add files</b>
        <span className="muted" style={{ fontSize: 12 }}>PDF · PPTX · PPT · MD</span>
      </button>
      <input ref={input} type="file" accept=".pdf,.pptx,.ppt,.md,.txt" multiple hidden onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
      {rows.length > 0 && (
        <div>
          {rows.map((r) => (
            <div key={r.name} className="up">
              <Icon name="file" />
              <span>{r.name}</span>
              <span className="muted">{r.error ?? r.progress ?? docStateLabel(r.id ? statusOf(r.id) : undefined, r.duplicate)}</span>
            </div>
          ))}
        </div>
      )}
      {rows.length > 0 && (
        <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={defaultTitle()} aria-label="Reviewer name" />
      )}
      <p className="fine">Files are read by Gemini (free tier). Avoid private files.</p>
      <button className="btn primary big block" disabled={!ids.length || upload.isPending || create.isPending} onClick={() => create.mutate()}>
        Create
      </button>
    </Sheet>
  );
}
