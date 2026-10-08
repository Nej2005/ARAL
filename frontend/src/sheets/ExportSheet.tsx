import { useState } from "react";

import { api } from "../api/client";
import Icon from "../components/Icon";
import Sheet from "../components/Sheet";
import { describeError } from "../lib/format";
import { useToast } from "../lib/toast";

type Props = { kind: "reviewer"; id: string; title: string; onClose: () => void } | { kind: "exam"; id: string; onClose: () => void };

export default function ExportSheet(props: Props) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<string>) => {
    setBusy(true);
    try {
      const name = await fn();
      toast(`Saved ${name}`);
      props.onClose();
    } catch (e) {
      toast(describeError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet title="Export" onClose={props.onClose}>
      <div className="menu">
        {props.kind === "reviewer" ? (
          <>
            <button disabled={busy} onClick={() => run(() => api.download(`/reviewers/${props.id}/export`, { format: "pdf" }, "study-sheet.pdf"))}>
              <Icon name="down" />Study sheet<span className="muted">PDF</span>
            </button>
            <button disabled={busy} onClick={() => run(() => api.download(`/reviewers/${props.id}/export`, { format: "csv" }, "anki.csv"))}>
              <Icon name="down" />Flashcards<span className="muted">Anki CSV</span>
            </button>
          </>
        ) : (
          <>
            <button disabled={busy} onClick={() => run(() => api.download(`/exams/${props.id}/export?format=pdf`, undefined, "exam.pdf"))}>
              <Icon name="down" />Printable exam<span className="muted">PDF · answer key at the end</span>
            </button>
            <button disabled={busy} onClick={() => run(() => api.download(`/exams/${props.id}/export?format=pdf&answer_key=none`, undefined, "exam.pdf"))}>
              <Icon name="down" />Printable exam<span className="muted">PDF · no answer key</span>
            </button>
            <button disabled={busy} onClick={() => run(() => api.download(`/exams/${props.id}/export?format=csv`, undefined, "exam.csv"))}>
              <Icon name="down" />Flashcards<span className="muted">Anki CSV</span>
            </button>
          </>
        )}
      </div>
    </Sheet>
  );
}
