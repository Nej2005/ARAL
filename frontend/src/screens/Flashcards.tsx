import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { keys, useAttemptMap, useCard } from "../api/hooks";
import type { AnswerResult, AttemptMap, Card, Summary } from "../api/types";
import { ThemeButton } from "../components/Header";
import FeedbackBlock from "../components/FeedbackBlock";
import Icon from "../components/Icon";
import MiniBar from "../components/MiniBar";
import Prompt from "../components/Prompt";
import QuestionMap from "../components/QuestionMap";
import { describeError, pad, TYPE_LABEL } from "../lib/format";
import { useToast } from "../lib/toast";
import ExitExam from "../sheets/ExitExam";
import FinishSheet from "../sheets/FinishSheet";
import MapSheet from "../sheets/MapSheet";

const LETTERS = "ABCD";

export default function Flashcards() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const map = useAttemptMap(id);
  const [sheet, setSheet] = useState<"exit" | "map" | "finish" | null>(null);
  const [justAnswered, setJustAnswered] = useState(false);
  const identInput = useRef<HTMLInputElement>(null);

  // The card index lives in the URL (?i=) so refresh / back keep the place; defaults to where you left off.
  const indexParam = Number(params.get("i"));
  const index = indexParam >= 1 ? indexParam : map.data?.last_viewed_index ?? null;
  const card = useCard(id, index);

  const goTo = useCallback(
    (i: number) => {
      setJustAnswered(false);
      setParams({ i: String(i) }, { replace: true });
    },
    [setParams],
  );

  useEffect(() => {
    document.getElementById("app")?.classList.add("fit");
    return () => document.getElementById("app")?.classList.remove("fit");
  }, []);

  const answer = useMutation({
    mutationFn: ({ questionId, response }: { questionId: string; response: string }) =>
      api.post<AnswerResult>(`/attempts/${id}/answer`, { question_id: questionId, response }),
    onSuccess: (res, vars) => {
      // Update the card in place so the feedback shows without a refetch.
      qc.setQueryData<Card>(keys.card(id, index ?? 0), (old) =>
        old ? { ...old, answered: true, feedback: res.feedback, next_unanswered_index: res.next_unanswered_index, finished: res.finished } : old,
      );
      qc.setQueryData<AttemptMap>(keys.attempt(id), (old) =>
        old
          ? {
              ...old,
              progress: res.progress,
              status: res.finished ? "completed" : old.status,
              cards: old.cards.map((c) => (c.question_id === vars.questionId ? { ...c, status: res.feedback.is_correct ? "correct" : "wrong" } : c)),
            }
          : old,
      );
      setJustAnswered(true);
    },
    onError: (e) => {
      toast(describeError(e));
      qc.invalidateQueries({ queryKey: keys.card(id, index ?? 0) });
      qc.invalidateQueries({ queryKey: keys.attempt(id) });
    },
  });

  const finish = useMutation({
    mutationFn: () => api.post<Summary>(`/attempts/${id}/finish`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.attempt(id) });
      nav(`/attempts/${id}/summary`);
    },
    onError: (e) => toast(describeError(e)),
  });

  const m = map.data;
  const c = card.data;
  const answered = !!c?.answered;
  const done = m?.status === "completed" || !!c?.finished;
  const total = m?.total ?? c?.total ?? 0;

  const next = useCallback(() => {
    if (!c || index === null) return;
    if (done) {
      nav(`/attempts/${id}/summary`);
      return;
    }
    if (index < total) goTo(index + 1);
    else if (c.next_unanswered_index) goTo(c.next_unanswered_index);
  }, [c, done, goTo, id, index, nav, total]);

  const skip = useCallback(() => {
    if (!c || index === null) return;
    if (index < total) goTo(index + 1);
    else if (c.next_unanswered_index && c.next_unanswered_index !== index) goTo(c.next_unanswered_index);
    else toast("Last open card");
  }, [c, goTo, index, toast, total]);

  const back = useCallback(() => {
    if (index !== null && index > 1) goTo(index - 1);
  }, [goTo, index]);

  const pick = useCallback(
    (response: string) => {
      if (!c || answered || done || answer.isPending) return;
      answer.mutate({ questionId: c.question.id, response });
    },
    [answer, answered, c, done],
  );

  const onFinishClick = () => {
    if (!m) return;
    if (m.status === "completed") nav(`/attempts/${id}/summary`);
    else if (m.progress.unanswered > 0) setSheet("finish");
    else finish.mutate();
  };

  // Keyboard: A–D / 1–4, T / F, Enter next, ← back, → skip/next.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (sheet || !c || e.metaKey || e.ctrlKey || e.altKey) return;
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      const k = e.key.toLowerCase();
      if (e.key === "Enter" && answered) {
        e.preventDefault();
        next();
        return;
      }
      if (e.key === "ArrowLeft") return back();
      if (e.key === "ArrowRight") return answered ? next() : skip();
      if (answered || done) return;
      if (c.question.type === "mcq" && c.question.choices) {
        const i = "abcd".indexOf(k) >= 0 ? "abcd".indexOf(k) : "1234".indexOf(k);
        if (i >= 0 && c.question.choices[i]) pick(c.question.choices[i].id);
      }
      if (c.question.type === "true_false" && (k === "t" || k === "f")) pick(k === "t" ? "true" : "false");
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [answered, back, c, done, next, pick, sheet, skip]);

  useEffect(() => {
    if (c && !answered && c.question.type === "identification" && window.matchMedia("(pointer: fine)").matches) {
      identInput.current?.focus();
    }
  }, [c, answered]);

  const submitIdent = (e: FormEvent) => {
    e.preventDefault();
    const v = identInput.current?.value.trim();
    if (v) pick(v);
    else identInput.current?.focus();
  };

  const fb = c?.feedback ?? null;
  const q = c?.question;

  return (
    <div id="app" className="fit">
      <main className="wrap">
        <div className="cardbar">
          <button className="icon-btn" onClick={() => (done ? nav(`/attempts/${id}/summary`) : setSheet("exit"))} aria-label="Exit exam">
            <Icon name="x" />
          </button>
          <div className="prog">
            {m && (
              <>
                <MiniBar value={m.progress.answered} total={m.total} /> {m.progress.answered}/{m.total}
                {m.kind === "mistakes" && <> · <span className="hl">Mistakes</span></>}
              </>
            )}
          </div>
          <button className="icon-btn phone-only" onClick={() => setSheet("map")} aria-label="Question map">
            <Icon name="grid" />
          </button>
          <span className="phone-only" style={{ display: "contents" }}><ThemeButton /></span>
        </div>

        <div className="fc">
          <div className="fc-main">
            <article className="card" id="card" key={index ?? 0}>
              {(map.isError || card.isError) && <p className="err"><Icon name="warn" />{describeError(map.error ?? card.error)}</p>}
              {!c && !card.isError && <p className="loading">loading…</p>}
              {c && q && (
                <>
                  <div className="card-head">
                    <span className="qtype"><span className="hl">{TYPE_LABEL[q.type]}</span></span>
                    <span className="qnum">{pad(c.index)}</span>
                  </div>
                  <Prompt text={q.prompt} />

                  {q.type === "mcq" && q.choices && (
                    <div className="choices">
                      {q.choices.map((ch, i) => {
                        let cls = "";
                        let mark: "check" | "x" | null = null;
                        if (fb) {
                          if (ch.id === fb.correct_answer.id) { cls = "is-correct"; mark = "check"; }
                          else if (ch.id === fb.your_answer?.id) { cls = "is-wrong"; mark = "x"; }
                          else cls = "is-dim";
                        } else if (done && c.correct_answer) {
                          cls = ch.id === c.correct_answer.id ? "is-correct" : "is-dim";
                        }
                        return (
                          <button key={ch.id} className={`choice ${cls}`} disabled={answered || done || answer.isPending} onClick={() => pick(ch.id)}>
                            <span className="key">{LETTERS[i]}</span>
                            <span>{ch.text}</span>
                            <span className="mark">{mark && <Icon name={mark} />}</span>
                          </button>
                        );
                      })}
                    </div>
                  )}

                  {q.type === "true_false" && (
                    <div className="tf">
                      {(["true", "false"] as const).map((v) => {
                        let cls = "";
                        const correct = fb?.correct_answer.text ?? c.correct_answer?.text;
                        if (fb || done) {
                          if (v === correct) cls = "is-correct";
                          else if (fb && v === fb.your_answer?.text) cls = "is-wrong";
                          else cls = "is-dim";
                        }
                        return (
                          <button key={v} className={`tfb ${cls}`} disabled={answered || done || answer.isPending} onClick={() => pick(v)}>
                            {v}
                          </button>
                        );
                      })}
                    </div>
                  )}

                  {q.type === "identification" && (
                    answered || done ? (
                      <div className="ident">
                        <div className={`pinput ${fb ? (fb.is_correct ? "is-correct" : "is-wrong") : ""}`}>
                          <input value={fb?.your_answer?.text ?? ""} disabled aria-label="Your answer" placeholder={done && !fb ? "Not answered" : ""} readOnly />
                        </div>
                      </div>
                    ) : (
                      <form className="ident" onSubmit={submitIdent}>
                        <div className="pinput">
                          <input ref={identInput} autoComplete="off" autoCapitalize="off" spellCheck={false} placeholder="Type the term" aria-label="Your answer" />
                        </div>
                        <button className="btn primary" type="submit" disabled={answer.isPending}><Icon name="check" />Check</button>
                      </form>
                    )
                  )}

                  {fb && <FeedbackBlock fb={fb} focus={justAnswered} spelled={fb.match_note ? fb.correct_answer.text : null} />}
                  {!fb && done && c.correct_answer && (
                    <div className="fb"><div className="vline"><span className="verdict bad"><Icon name="dash" />Skipped</span><span>Answer: <b>{c.correct_answer.text}</b></span></div></div>
                  )}
                </>
              )}
            </article>
            <div className="fc-actions">
              <button className="btn" onClick={back} disabled={!index || index <= 1} aria-label="Previous card">
                <Icon name="prev" /><span className="hide-xs">Back</span>
              </button>
              <span className="grow" />
              {answered || done ? (
                <button className="btn primary next" onClick={next}>{done ? "Results" : "Next"}<Icon name="next" /></button>
              ) : (
                <button className="btn next" onClick={skip}>Skip<Icon name="skip" /></button>
              )}
            </div>
          </div>
          <aside className="fc-side">
            {m && index !== null && <QuestionMap map={m} current={index} onJump={goTo} />}
            <button className="btn block" onClick={onFinishClick} disabled={!m || finish.isPending}>{done ? "Results" : "Finish"}</button>
            <ThemeButton />
          </aside>
        </div>
      </main>

      {sheet === "exit" && m && (
        <ExitExam
          unanswered={m.progress.unanswered}
          onClose={() => setSheet(null)}
          onFinish={() => { setSheet(null); finish.mutate(); }}
          examId={m.exam_id}
        />
      )}
      {sheet === "map" && m && index !== null && (
        <MapSheet map={m} current={index} onJump={(i) => { setSheet(null); goTo(i); }} onFinish={() => { setSheet(null); onFinishClick(); }} done={done} onClose={() => setSheet(null)} />
      )}
      {sheet === "finish" && m && (
        <FinishSheet
          unanswered={m.progress.unanswered}
          onClose={() => setSheet(null)}
          onAnswer={() => { setSheet(null); if (c?.next_unanswered_index) goTo(c.next_unanswered_index); }}
          onFinish={() => { setSheet(null); finish.mutate(); }}
        />
      )}
    </div>
  );
}
