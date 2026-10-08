import Sheet from "../components/Sheet";

export default function FinishSheet({ unanswered, onClose, onAnswer, onFinish }: { unanswered: number; onClose: () => void; onAnswer: () => void; onFinish: () => void }) {
  return (
    <Sheet title="Finish?" onClose={onClose}>
      <p>{unanswered} open card{unanswered === 1 ? "" : "s"} will count as wrong.</p>
      <div className="row">
        <button className="btn primary" onClick={onAnswer}>Answer them</button>
        <button className="btn" onClick={onFinish}>Finish</button>
      </div>
    </Sheet>
  );
}
