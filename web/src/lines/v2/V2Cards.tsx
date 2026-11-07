import { useEffect, useRef, useState } from "react";
import { Button } from "../../components/ui";
import {
  confirmCompletion,
  getAssessmentDue,
  getCompletion,
  getPlanDate,
  startAssessment,
  submitAssessment,
  undoCompletion,
  type AssessmentReport,
  type CompletionStatus,
  type Quiz,
  type StageView,
} from "./api";
import { AssessmentCard } from "./AssessmentCard";
import { loadCardsForTasks, readLaterDay, rememberLater, stepIndex, submitGuard, syncAfterTasks, viewAfterReport, type CardView } from "./cards";
import { CompletionCard } from "./CompletionCard";
import { publishGoalDone } from "./done";
import { ReportCard } from "./ReportCard";

/**
 * examInPlan：今天三件里有「考试」时（V2.1），阶段测验从考试进入，不再单独弹邀请卡。
 * allLearned：全部讲次学完后才露出「我学完了」入口。
 */
export function V2Cards({ doneCount = 0, examInPlan = false, allLearned = true }: { doneCount?: number; examInPlan?: boolean; allLearned?: boolean }) {
  const [today, setToday] = useState("");
  const [completion, setCompletion] = useState<CompletionStatus | null>(null);
  const [stage, setStage] = useState<StageView | null>(null);
  const [view, setView] = useState<CardView>("loading");
  const viewRef = useRef(view);
  viewRef.current = view;
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [report, setReport] = useState<AssessmentReport | null>(null);
  const [reportLabel, setReportLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [warn, setWarn] = useState("");
  const [canForce, setCanForce] = useState(false);
  const [restNote, setRestNote] = useState("");

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const loaded = await loadCardsForTasks(doneCount, {
        planDate: getPlanDate,
        completion: getCompletion,
        due: getAssessmentDue,
      });
      if (cancelled) return;
      if (!loaded.completion || !loaded.due) {
        if (viewRef.current === "loading") setView("idle");
        return;
      }
      const next = syncAfterTasks({
        view: viewRef.current,
        today: loaded.today,
        laterDay: readLaterDay(),
        done: loaded.completion.done === true,
        suggest: loaded.completion.suggest === true,
        due: loaded.due.due === true,
      });
      setToday(loaded.today);
      setCompletion(loaded.completion);
      setStage(loaded.due.stage ?? null);
      publishGoalDone(loaded.completion.done === true);
      setView(examInPlan && next.view === "invite" ? "idle" : next.view);
    })();
    return () => { cancelled = true; };
  }, [doneCount, examInPlan]);

  async function refreshCompletion() {
    const status = await getCompletion();
    if (!status) return null;
    setCompletion(status);
    publishGoalDone(status.done);
    return status;
  }

  async function begin() {
    setBusy(true);
    setError("");
    const result = await startAssessment();
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setQuiz(result.quiz);
    setStage(result.quiz.stage);
    setIndex(0);
    setAnswers({});
    setWarn("");
    setCanForce(false);
    setReportLabel(result.quiz.label || "");
    setView("quiz");
  }

  function laterExam() {
    if (today) rememberLater(today);
    setError("");
    setView("idle");
  }

  function pick(questionId: string, optionId: string) {
    setAnswers((current) => ({ ...current, [questionId]: optionId }));
    setWarn("");
    setCanForce(false);
  }

  async function submit(force: boolean) {
    if (!quiz) return;
    const ids = quiz.questions.map((question) => question.id);
    const guard = submitGuard(ids, answers);
    if (!force && !guard.ok) {
      setWarn(guard.message);
      setCanForce(guard.canForce);
      return;
    }
    if (!guard.ok && !guard.canForce) {
      setWarn(guard.message);
      setCanForce(false);
      return;
    }
    const payload = Object.fromEntries(Object.entries(answers).filter(([, value]) => value));
    setBusy(true);
    setError("");
    const result = await submitAssessment(quiz.id, payload);
    if (!result.ok) {
      setError(result.message);
      setBusy(false);
      return;
    }
    setReport(result.report);
    setReportLabel(quiz.label || reportLabel);
    await refreshCompletion();
    setBusy(false);
    setWarn("");
    setCanForce(false);
    setView("report");
  }

  async function acknowledge() {
    const status = completion ?? await refreshCompletion();
    setView(viewAfterReport({ done: status?.done === true, suggest: status?.suggest === true }));
  }

  async function complete(reason: "suggested" | "user_said") {
    setBusy(true);
    setError("");
    const result = await confirmCompletion(reason);
    if (!result.ok) {
      setError(result.message);
      setBusy(false);
      return;
    }
    setCompletion({ suggest: false, reason: null, card: result.card, done: true });
    publishGoalDone(true);
    setBusy(false);
    setView("done");
  }

  async function undo() {
    setBusy(true);
    setError("");
    const result = await undoCompletion();
    if (!result.ok) {
      setError(result.message);
      setBusy(false);
      return;
    }
    const status = await refreshCompletion();
    setBusy(false);
    setView(status?.suggest ? "suggest" : "idle");
  }

  if (view === "loading") return null;
  const showFinishedEntry = allLearned && view === "idle" && Boolean(completion?.card) && completion?.done !== true;
  if (view === "idle" && !showFinishedEntry && !restNote) return null;

  return (
    <section className="v2-cards" aria-label="阶段测验与完成">
      {view === "invite" && (
        <AssessmentCard mode="invite" stage={stage} busy={busy} error={error} onStart={() => void begin()} onLater={laterExam} />
      )}
      {view === "quiz" && quiz && (
        <AssessmentCard
          mode="quiz"
          quiz={quiz}
          index={index}
          answers={answers}
          busy={busy}
          error={error}
          warn={warn}
          canForce={canForce}
          onPick={pick}
          onPrev={() => setIndex((current) => stepIndex(current, quiz.questions.length, -1))}
          onNext={() => setIndex((current) => stepIndex(current, quiz.questions.length, 1))}
          onSubmit={() => void submit(false)}
          onForce={() => void submit(true)}
        />
      )}
      {view === "report" && report && <ReportCard report={report} label={reportLabel} onOk={() => void acknowledge()} />}
      {(view === "suggest" || view === "confirm") && (
        <CompletionCard
          mode="suggest"
          userSaid={view === "confirm"}
          busy={busy}
          error={error}
          onComplete={() => void complete(view === "confirm" ? "user_said" : "suggested")}
          onLater={() => { setError(""); setView("idle"); }}
        />
      )}
      {view === "done" && completion?.card && (
        <CompletionCard
          mode="done"
          card={completion.card}
          busy={busy}
          error={error}
          onUndo={() => void undo()}
          onRest={() => { setRestNote("好，先休息一阵。学习记录都留着。"); setView("idle"); }}
        />
      )}
      {showFinishedEntry && (
        <div className="btns">
          <Button onClick={() => { setError(""); setRestNote(""); setView("confirm"); }}>我学完了</Button>
        </div>
      )}
      {restNote && view === "idle" && <p role="status">{restNote}</p>}
    </section>
  );
}
