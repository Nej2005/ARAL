import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { keys } from "../api/hooks";
import type { DocumentSummary, ReviewerDetail } from "../api/types";
import Icon from "../components/Icon";
import Sheet from "../components/Sheet";
import { describeError } from "../lib/format";
import { useToast } from "../lib/toast";

interface Row {
  name: string;
  id?: string;
  duplicate?: boolean;
  error?: string;
}

export default function NewReviewer({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [rows, setRows] = useState<Row[]>([]);
  const [title, setTitle] = useState("");
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      for (const f of files) {
        setRows((r) => [...r, { name: f.name }]);
        try {
          const d = await api.upload<DocumentSummary>("/documents", f);
          setRows((r) => r.map((x) => (x.name === f.name && !x.id && !x.error ? { ...x, id: d.id, duplicate: d.duplicate } : x)));
        } catch (e) {
          setRows((r) => r.map((x) => (x.name === f.name && !x.id && !x.error ? { ...x, error: describeError(e) } : x)));
        }
      }
    },
  });

  const ids = rows.filter((r) => r.id).map((r) => r.id!);
  const docs = useQueries({
    queries: ids.map((id) => ({
      queryKey: keys.document(id),
      queryFn: () => api.get<DocumentSummary>(`/documents/${id}`),
      refetchInterval: (q: { state: { data?: DocumentSummary } }) => {
        const s = q.state.data?.status;
        return s === "uploaded" || s === "extracting" ? 1500 : false;
      },
    })),
  });
  const statusOf = (id: string) => docs.find((d) => d.data?.id === id)?.data;

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
        <span className="muted" style={{ fontSize: 12 }}>PDF · PPTX · PPT</span>
      </button>
      <input ref={input} type="file" accept=".pdf,.pptx,.ppt" multiple hidden onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
      {rows.length > 0 && (
        <div>
          {rows.map((r) => {
            const d = r.id ? statusOf(r.id) : undefined;
            const state = r.error
              ? r.error
              : !r.id
                ? "Uploading…"
                : d?.status === "ready"
                  ? r.duplicate ? "Already uploaded · reused" : "Ready"
                  : d?.status === "failed"
                    ? describeError(Object.assign(new Error(d.error_message ?? ""), { code: d.error_code }))
                    : "Reading…";
            return (
              <div key={r.name} className="up">
                <Icon name="file" />
                <span>{r.name}</span>
                <span className="muted">{state}</span>
              </div>
            );
          })}
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
