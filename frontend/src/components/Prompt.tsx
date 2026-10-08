import { Fragment } from "react";

/** Renders `**term**` as emphasis and `_____` as a marked blank. Lesson text is otherwise untouched. */
export default function Prompt({ text, className = "qprompt" }: { text: string; className?: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|_____)/g);
  return (
    <p className={className}>
      {parts.map((p, i) => {
        if (p === "_____") return <span key={i} aria-label="blank">_____</span>;
        if (p.startsWith("**") && p.endsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
        return <Fragment key={i}>{p}</Fragment>;
      })}
    </p>
  );
}
