import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useAvailability, useOutline } from "../api/hooks";
import type { Exam, QuestionType, ReviewerDetail, Scope } from "../api/types";
import Icon from "../components/Icon";
import Sheet from "../components/Sheet";
import { describeError, TYPE_LABEL } from "../lib/format";
import { useToast } from "../lib/toast";

const ALL: QuestionType[] = ["mcq", "true_false", "identification"];
const GLYPH: Record<QuestionType, string> = { mcq: "ABCD", true_false: "T/F", identification: "___" };

interface FileScope {
  on: boolean;
  from: string;
  to: string;
}

export default function NewExam({ reviewer, onClose }: { reviewer: ReviewerDetail; onClose: () => void }) {
  const nav = useNavigate();
  const toast = useToast();
  const [types, setTypes] = useState<QuestionType[]>(ALL);
  const [count, setCount] = useState(10);
  const [more, setMore] = useState(false);
  const [files, setFiles] = useState<Record<string, FileScope>>({});
  const [topics, setTopics] = useState<string[]>([]);
  const outline = useOutline(reviewer.id, more);

  const scope = useMemo<Scope | null>(() => {
    const docs = reviewer.documents
      .filter((d) => d.status === "ready")
      .map((d) => ({ d, f: files[d.id] ?? { on: true, from: "", to: "" } }))
      .filter(({ f }) => f.on)
      .map(({ d, f }) => {
        const from = Math.max(1, parseInt(f.from, 10) || 1);
        const to = Math.min(d.page_count, parseInt(f.to, 10) || d.page_count);
        const whole = from <= 1 && to >= d.page_count;
        return whole ? { document_id: d.id } : { document_id: d.id, pages: [[from, Math.max(from, to)] as [number, number]] };
      });
    const narrowedDocs = docs.length !== reviewer.documents.filter((d) => d.status === "ready").length || docs.some((d) => d.pages);
    if (!narrowedDocs && topics.length === 0) return null;
    const s: Scope = {};
    if (narrowedDocs) s.documents = docs;
    if (topics.length) s.topics = topics;
    return s;
  }, [files, reviewer.documents, topics]);

  const av = useAvailability(reviewer.id, types, scope);
  const max = av.data?.max_count_for_types ?? 0;
  useEffect(() => {
    if (av.data) setCount((c) => Math.max(max ? 1 : 0, Math.min(c, max)));
  }, [av.data, max]);

  const start = useMutation({
    mutationFn: () => api.post<Exam>(`/reviewers/${reviewer.id}/exams`, { types, count, scope }),
    onSuccess: (e) => { onClose(); nav(`/exams/${e.id}/making`); },
    onError: (e) => toast(describeError(e)),
  });

  const toggleType = (t: QuestionType) =>
    setTypes((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : ALL.filter((x) => x === t || cur.includes(x))));

  const setFile = (id: string, patch: Partial<FileScope>) =>
    setFiles((cur) => ({ ...cur, [id]: { ...(cur[id] ?? { on: true, from: "", to: "" }), ...patch } }));

  return (
    <Sheet title="New exam" onClose={onClose}>
      <div className="field">
        <span className="label">Type</span>
        <div className="types">
          {ALL.map((t) => (
            <button key={t} className="type" aria-pressed={types.includes(t)} onClick={() => toggleType(t)}>
              <span className="g">{GLYPH[t]}</span>
              <span className="n">{TYPE_LABEL[t]}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="field">
        <span className="label">Items</span>
        <div className="count-row">
          <div className="stepper">
            <button onClick={() => setCount((c) => Math.max(1, c - 1))} disabled={count <= 1} aria-label="Fewer"><Icon name="dash" /></button>
            <input
              id="count"
              inputMode="numeric"
              value={count}
              onChange={(e) => setCount(Math.max(1, Math.min(max || 1, parseInt(e.target.value, 10) || 1)))}
              aria-label="Number of items"
            />
            <button onClick={() => setCount((c) => Math.min(max, c + 1))} disabled={count >= max} aria-label="More"><Icon name="plus" /></button>
          </div>
          <span className="muted">/ {av.isLoading ? "…" : max}</span>
        </div>
        {av.data && av.data.unused_outside_scope > 0 && max === 0 && (
          <p className="fine">{av.data.unused_outside_scope} unused items outside this selection</p>
        )}
      </div>
      <details className="more" open={more} onToggle={(e) => setMore((e.target as HTMLDetailsElement).open)}>
        <summary><Icon name="chev" />Choose slides or topics</summary>
        <div className="scope">
          {reviewer.documents.filter((d) => d.status === "ready").map((d) => {
            const f = files[d.id] ?? { on: true, from: "", to: "" };
            return (
              <div key={d.id} className="sf">
                <input type="checkbox" id={`sf-${d.id}`} checked={f.on} onChange={(e) => setFile(d.id, { on: e.target.checked })} />
                <label htmlFor={`sf-${d.id}`}>{d.filename}</label>
                <div className="range">
                  {d.page_unit === "slide" ? "Slides" : "Pages"}
                  <input inputMode="numeric" placeholder="1" value={f.from} onChange={(e) => setFile(d.id, { from: e.target.value.replace(/\D/g, "") })} aria-label="From" />
                  –
                  <input inputMode="numeric" placeholder={String(d.page_count)} value={f.to} onChange={(e) => setFile(d.id, { to: e.target.value.replace(/\D/g, "") })} aria-label="To" />
                  <span>of {d.page_count}</span>
                </div>
              </div>
            );
          })}
          {outline.data && outline.data.topics.length > 0 && (
            <div className="chips">
              {outline.data.topics.map((t) => (
                <button
                  key={t.topic_key}
                  className="chip"
                  aria-pressed={topics.includes(t.topic)}
                  onClick={() => setTopics((cur) => (cur.includes(t.topic) ? cur.filter((x) => x !== t.topic) : [...cur, t.topic]))}
                >
                  {t.topic} <span style={{ opacity: 0.7 }}>{t.unused_count}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </details>
      <button className="btn primary big block" disabled={!types.length || !max || start.isPending} onClick={() => start.mutate()}>
        <Icon name="play" />Start
      </button>
    </Sheet>
  );
}
