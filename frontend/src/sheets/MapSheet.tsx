import type { AttemptMap } from "../api/types";
import QuestionMap from "../components/QuestionMap";
import Sheet from "../components/Sheet";

export default function MapSheet({
  map,
  current,
  done,
  onJump,
  onFinish,
  onClose,
}: {
  map: AttemptMap;
  current: number;
  done: boolean;
  onJump: (i: number) => void;
  onFinish: () => void;
  onClose: () => void;
}) {
  return (
    <Sheet title="Cards" onClose={onClose}>
      <QuestionMap map={map} current={current} onJump={onJump} />
      <button className="btn block" onClick={onFinish}>{done ? "Results" : "Finish"}</button>
    </Sheet>
  );
}
