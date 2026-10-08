import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { keys } from "../api/hooks";
import type { ReviewerDetail } from "../api/types";
import Icon from "../components/Icon";
import Sheet from "../components/Sheet";
import { describeError } from "../lib/format";
import { useToast } from "../lib/toast";

export default function ReviewerMenu({ reviewer, onClose }: { reviewer: ReviewerDetail; onClose: () => void }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [mode, setMode] = useState<"menu" | "rename" | "reset" | "delete">("menu");
  const [title, setTitle] = useState(reviewer.title);

  const done = (msg?: string) => {
    qc.invalidateQueries({ queryKey: keys.reviewer(reviewer.id) });
    qc.invalidateQueries({ queryKey: keys.reviewers });
    qc.invalidateQueries({ queryKey: keys.reviewerExams(reviewer.id) });
    if (msg) toast(msg);
    onClose();
  };

  const rename = useMutation({
    mutationFn: () => api.patch(`/reviewers/${reviewer.id}`, { title: title.trim() }),
    onSuccess: () => done("Renamed"),
    onError: (e) => toast(describeError(e)),
  });
  const reset = useMutation({
    mutationFn: () => api.post(`/reviewers/${reviewer.id}/coverage/reset`),
    onSuccess: () => done("Progress reset"),
    onError: (e) => toast(describeError(e)),
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/reviewers/${reviewer.id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: keys.reviewers }); onClose(); nav("/"); },
    onError: (e) => toast(describeError(e)),
  });

  if (mode === "rename") {
    return (
      <Sheet title="Rename" onClose={onClose}>
        <form onSubmit={(e) => { e.preventDefault(); if (title.trim()) rename.mutate(); }} style={{ display: "grid", gap: 14 }}>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Reviewer name" />
          <div className="row">
            <button className="btn primary" type="submit" disabled={!title.trim() || rename.isPending}>Save</button>
            <button className="btn" type="button" onClick={() => setMode("menu")}>Cancel</button>
          </div>
        </form>
      </Sheet>
    );
  }
  if (mode === "reset") {
    return (
      <Sheet title="Reset progress?" onClose={onClose}>
        <p>All {reviewer.item_count} items become new again. Scores stay.</p>
        <div className="row">
          <button className="btn primary" onClick={() => reset.mutate()} disabled={reset.isPending}>Reset</button>
          <button className="btn" onClick={() => setMode("menu")}>Cancel</button>
        </div>
      </Sheet>
    );
  }
  if (mode === "delete") {
    return (
      <Sheet title="Delete reviewer?" onClose={onClose}>
        <p>Exams and scores for “{reviewer.title}” are deleted. The files stay in your library.</p>
        <div className="row">
          <button className="btn primary" onClick={() => remove.mutate()} disabled={remove.isPending}><Icon name="trash" />Delete</button>
          <button className="btn" onClick={() => setMode("menu")}>Cancel</button>
        </div>
      </Sheet>
    );
  }
  return (
    <Sheet title={reviewer.title} onClose={onClose}>
      <div className="menu">
        <button onClick={() => setMode("rename")}><Icon name="edit" />Rename</button>
        <button onClick={() => setMode("reset")} disabled={reviewer.used_items === 0}>
          <Icon name="reset" />Reset progress<span className="muted">{reviewer.used_items}/{reviewer.item_count} reviewed</span>
        </button>
        <button onClick={() => setMode("delete")}><Icon name="trash" />Delete</button>
      </div>
    </Sheet>
  );
}
