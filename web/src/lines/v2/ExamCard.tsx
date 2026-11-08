import { useEffect, useState } from "react";
import { Badge, Button, Card } from "../../components/ui";
import { startExam, submitAssessment, submitExam, type AssessmentReport, type DailyExamReport, type Quiz } from "./api";
import { AssessmentCard } from "./AssessmentCard";
import { stepIndex, submitGuard } from "./cards";
import { ReportCard } from "./ReportCard";

/** 块3：今天的考试（第 3 件）。阶段当天就是阶段测验，交卷只勾考试这一件。 */
export function ExamCard({ onDone }: { onDone: () => void }) {
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [kind, setKind] = useState<"daily" | "stage">("daily");
  const [mistakes, setMistakes] = useState(0);
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [daily, setDaily] = useState<DailyExamReport | null>(null);
  const [stageReport, setStageReport] = useState<AssessmentReport | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [warn, setWarn] = useState("");
  const [canForce, setCanForce] = useState(false);

  async function load() {
    setBusy(true);
    setError("");
    const result = await startExam();
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    const paper = result.paper;
    if (paper.type === "stage") {
      setKind("stage");
      setQuiz(paper);
      return;
    }
    setKind("daily");
    setMistakes(paper.mistake_count);
    if (paper.submitted && paper.report) setDaily(paper.report);
    setQuiz({ id: paper.id, label: paper.label, mock: paper.mock, questions: paper.questions,
      stage: { no: 0, title: `考试 · 第 ${paper.lecture_no} 讲`, unit_nos: [] } });
  }

  useEffect(() => { void load(); }, []);

  async function submit(force: boolean) {
    if (!quiz) return;
    const guard = submitGuard(quiz.questions.map((question) => question.id), answers);
    if (!guard.ok && (!force || !guard.canForce)) {
      setWarn(guard.message);
      setCanForce(guard.canForce);
      return;
    }
    const payload = Object.fromEntries(Object.entries(answers).filter(([, value]) => value));
    setBusy(true);
    setError("");
    if (kind === "stage") {
      const result = await submitAssessment(quiz.id, payload);
      setBusy(false);
      if (!result.ok) { setError(result.message); return; }
      setStageReport(result.report);
    } else {
      const result = await submitExam(quiz.id, payload);
      setBusy(false);
      if (!result.ok) { setError(result.message); return; }
      setDaily(result.report);
    }
    setWarn("");
    setCanForce(false);
  }

  if (stageReport) return <ReportCard report={stageReport} label={quiz?.label || ""} onOk={onDone} />;
  if (daily) {
    return (
      <Card aria-label="考试成绩" data-v2-card="exam-report" className="card-read">
        <header>
          <h3>{quiz?.stage.title || "今天的考试"}</h3>
          {quiz?.label && <Badge sim={quiz.label === "模拟"}>{quiz.label}</Badge>}
        </header>
        <p className="v2-score">{daily.score} 分</p>
        <p>{daily.summary}</p>
        <div className="btns"><Button variant="primary" onClick={onDone}>好的</Button></div>
      </Card>
    );
  }
  if (!quiz) {
    return (
      <Card aria-label="今天的考试" className="card-read">
        <h3>今天的考试</h3>
        {busy && <p role="status">小满正在出题，大概要十几秒…</p>}
        {error && <p role="alert">{error}</p>}
        {error && <div className="btns"><Button onClick={() => void load()}>再试一次</Button></div>}
      </Card>
    );
  }
  return (
    <>
      <AssessmentCard
        mode="quiz"
        quiz={quiz}
        intro={kind === "stage" ? "学完一个阶段了，今天的考试就是阶段测验" : mistakes ? `前 ${mistakes} 题是之前做错的，再试一次` : "都是今天这一讲的题"}
        index={index}
        answers={answers}
        busy={busy}
        error={error}
        warn={warn}
        canForce={canForce}
        onPick={(questionId, optionId) => { setAnswers((current) => ({ ...current, [questionId]: optionId })); setWarn(""); setCanForce(false); }}
        onPrev={() => setIndex((current) => stepIndex(current, quiz.questions.length, -1))}
        onNext={() => setIndex((current) => stepIndex(current, quiz.questions.length, 1))}
        onSubmit={() => void submit(false)}
        onForce={() => void submit(true)}
      />
    </>
  );
}
