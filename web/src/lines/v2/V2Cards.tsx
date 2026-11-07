import { useEffect, useState } from "react";
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
import { pickInitialView, readLaterDay, rememberLater, stepIndex, submitGuard, viewAfterReport } from "./cards";
import { CompletionCard } from "./CompletionCard";
import { publishGoalDone } from "./done";
import { ReportCard } from "./ReportCard";

type View = "loading" | "done" | "suggest" | "confirm" | "invite" | "quiz" | "report" | "idle";

export function V2Cards() {
  const [today, setToday] = useState("");
  const [completion, setCompletion] = useState<CompletionStatus | null>(null);
  const [stage, setStage] = useState<StageView | null>(null);
  const [view, setView] = useState<View>("loading");
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
      const [date, status, due] = await Promise.all([getPlanDate(), getCompletion(), getAssessmentDue()]);
      if (cancelled) return;
      const day = date || "";
      setToday(day);
      setCompletion(status);
      setStage(due?.stage ?? null);
      publishGoalDone(status?.done === true);
      setView(pickInitialView({
        done: status?.done === true,
        suggest: status?.suggest === true,
        due: due?.due === true,
        laterDay: readLaterDay(),
        today: day,
      }));
    })();
    return () => { cancelled = true; };
  }, []);

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
  const showFinishedEntry = view === "idle" && Boolean(completion?.card) && completion?.done !== true;
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
