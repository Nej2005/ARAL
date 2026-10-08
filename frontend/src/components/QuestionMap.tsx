import type { AttemptMap } from "../api/types";

export default function QuestionMap({ map, current, onJump }: { map: AttemptMap; current: number; onJump: (i: number) => void }) {
  return (
    <>
      <div className="map" role="list">
        {map.cards.map((c) => (
          <button
            key={c.index}
            className={`cell ${c.status === "correct" ? "c-ok" : c.status === "wrong" ? "c-bad" : ""} ${c.index === current ? "c-cur" : ""}`}
            onClick={() => onJump(c.index)}
            aria-label={`Card ${c.index}, ${c.status === "unanswered" ? "not answered" : c.status}`}
            aria-current={c.index === current ? "true" : undefined}
          >
            {c.index}
          </button>
        ))}
      </div>
      <div className="legend">
        <span><i className="ok" />Right</span>
        <span><i className="bad" />Wrong</span>
        <span><i className="un" />Open</span>
      </div>
    </>
  );
}
