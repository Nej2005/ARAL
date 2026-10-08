import { useEffect, useRef } from "react";

import type { Feedback } from "../api/types";
import Icon from "./Icon";

export default function FeedbackBlock({ fb, focus = false, spelled }: { fb: Feedback; focus?: boolean; spelled?: string | null }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!focus || !ref.current) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    ref.current.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
    ref.current.focus({ preventScroll: true });
  }, [focus]);

  return (
    <div className="fb" ref={ref} tabIndex={-1} aria-live="polite">
      <div className="vline">
        {fb.is_correct ? (
          <span className="verdict ok"><Icon name="check" />Correct</span>
        ) : (
          <>
            <span className="verdict bad"><Icon name="x" />Wrong</span>
            <span>Answer: <b>{fb.correct_answer.text}</b></span>
          </>
        )}
        {fb.match_note === "typo_tolerated" && spelled && <span className="muted small">Spelled “{spelled}”</span>}
      </div>
      {fb.changed_span && (
        <p className="diff">
          <del>{fb.changed_span.to}</del> → <ins>{fb.changed_span.from}</ins>
        </p>
      )}
      <p>{fb.why}</p>
      {!fb.is_correct && fb.why_yours_is_wrong && !fb.changed_span && <p className="why2">{fb.why_yours_is_wrong}</p>}
      {!fb.is_correct && fb.why_yours_is_wrong && fb.changed_span && (
        <p className="why2">{fb.why_yours_is_wrong.replace(/^The statement changed '[^']*' to '[^']*'\.\s*/, "")}</p>
      )}
      <details className="src">
        <summary>
          <Icon name="chev" />Source · {fb.source.filename ? `${fb.source.filename.replace(/\.[^.]+$/, "")} · ` : ""}{fb.source.location}
        </summary>
        <blockquote>{fb.source.quote}</blockquote>
      </details>
    </div>
  );
}
