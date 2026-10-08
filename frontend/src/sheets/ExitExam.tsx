import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { keys } from "../api/hooks";
import type { Exam } from "../api/types";
import Icon from "../components/Icon";
import Sheet from "../components/Sheet";

export default function ExitExam({
  unanswered,
  examId,
  onClose,
  onFinish,
}: {
  unanswered: number;
  examId: string;
  onClose: () => void;
  onFinish: () => void;
}) {
  const nav = useNavigate();
  const exam = useQuery({ queryKey: keys.exam(examId), queryFn: () => api.get<Exam>(`/exams/${examId}`) });
  return (
    <Sheet title="Exit?" onClose={onClose}>
      <div className="menu">
        <button onClick={onFinish}>
          <Icon name="check" />Finish now{unanswered > 0 && <span className="muted">{unanswered} open = wrong</span>}
        </button>
        <button onClick={() => nav(exam.data ? `/reviewers/${exam.data.reviewer_id}` : "/")}>
          <Icon name="back" />Save &amp; exit<span className="muted">continue anytime</span>
        </button>
        <button onClick={onClose}><Icon name="play" />Keep going</button>
      </div>
    </Sheet>
  );
}
