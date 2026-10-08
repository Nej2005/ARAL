import { useState } from "react";
import { Link } from "react-router-dom";

import { useReviewers } from "../api/hooks";
import Header from "../components/Header";
import Icon from "../components/Icon";
import MiniBar from "../components/MiniBar";
import { describeError } from "../lib/format";
import NewReviewer from "../sheets/NewReviewer";

export default function Reviewers() {
  const q = useReviewers();
  const [creating, setCreating] = useState(false);

  return (
    <div id="app">
      <Header />
      <main className="wrap">
        <div className="page-head">
          <h1 className="h1">Reviewers</h1>
          <button className="btn primary big" onClick={() => setCreating(true)}>
            <Icon name="plus" />New
          </button>
        </div>
        {q.isError && <p className="err"><Icon name="warn" />{describeError(q.error)}</p>}
        {q.isLoading && <p className="loading">loading…</p>}
        {q.data && q.data.length === 0 && <p className="empty">No reviewers yet</p>}
        {q.data && q.data.length > 0 && (
          <div className="list">
            {q.data.map((r) => (
              <Link key={r.id} className="lr r-rev" to={`/reviewers/${r.id}`}>
                <span className="t">
                  {r.title}
                  <br />
                  <span className="sub">
                    {r.document_count} file{r.document_count === 1 ? "" : "s"}
                    {r.status === "processing" ? " · reading…" : r.status === "needs_attention" ? " · needs attention" : ""}
                  </span>
                </span>
                <span className="prog-cell">
                  <MiniBar value={r.used_items} total={r.item_count} /> <span className="muted">{r.used_items}/{r.item_count}</span>
                </span>
                <span className="score-pill">{r.last_score ? `${r.last_score.correct_count}/${r.last_score.total}` : "—"}</span>
                <Icon name="chev" />
              </Link>
            ))}
          </div>
        )}
      </main>
      {creating && <NewReviewer onClose={() => setCreating(false)} />}
    </div>
  );
}
