import { useRef, useState } from "react";
import { Button } from "../../components/ui";
import { FeedbackPanel, feedbackNotice } from "./FeedbackPanel";
import { AnswerDetails, LearningSummary } from "./LearningSummary";
import { QuestionReviewList } from "./QuestionReviewList";
import { request, type FeedbackRecord, type Progress, type Quiz, type Result, type ReviewItem } from "./api";

type Props = { quiz: Quiz; pdfName?: string; onChange: (quiz: Quiz) => void; onComplete: () => void;
  onRecordsChange: () => Promise<void>; onHome?: () => void };
const draftKey = (id: string) => `xiaoman-practice-draft-v1-${id}`;
function initialDraft(quiz: Quiz): Partial<Progress> {
  try {
    const local = JSON.parse(localStorage.getItem(draftKey(quiz.quiz_id)) || "null") as Progress | null;
    if (local && quiz.questions.some((q) => q.id === local.question_id) && (!quiz.progress || local.question_id === quiz.progress.question_id)) return { ...local, paused: quiz.progress?.paused ?? false };
  } catch { /* 服务端作答不受本机草稿损坏影响。 */ }
  return quiz.progress || {};
}

export function QuizCard({ quiz, pdfName = "当前 PDF", onChange, onComplete, onRecordsChange, onHome = () => {} }: Props) {
  const [draft] = useState(() => initialDraft(quiz));
  const first = quiz.questions.findIndex((q) => q.id === draft.question_id);
  const unanswered = quiz.questions.findIndex((q) => !quiz.results?.[q.id]);
  const [index, setIndex] = useState(first >= 0 ? first : Math.max(0, unanswered));
  const [complete, setComplete] = useState(Boolean(quiz.completed));
  const [reviewing, setReviewing] = useState(false);
  const [choice, setChoice] = useState(draft.answer || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const started = useRef(Date.now());
  const accumulated = useRef(draft.seconds || 0);
  const pending = useRef(false);
  const q = quiz.questions[index];
  const result = quiz.results?.[q.id];
  const elapsed = () => Math.min(86400, accumulated.current + Math.max(0, Math.round((Date.now() - started.current) / 1000)));

  function remember(answer: string) {
    try { localStorage.setItem(draftKey(quiz.quiz_id), JSON.stringify({ question_id: q.id, answer, seconds: elapsed() })); }
    catch { /* 本机草稿不可用时，提交和顶部返回仍由服务端保存。 */ }
  }
  async function action(work: () => Promise<void>) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError("");
    try { await work(); }
    catch (err) { setError(err instanceof Error ? err.message : "保存失败，请重试。"); }
    finally { pending.current = false; setBusy(false); }
  }
  async function submit() {
    if (!choice) return;
    await action(async () => {
      const data = await request<Result>("/api/attempts", { quiz_id: quiz.quiz_id, question_id: q.id, answer: choice, seconds: elapsed() });
      onChange({ ...quiz, results: { ...quiz.results, [q.id]: data } });
    });
  }
  async function saveAndExit() {
    await action(async () => {
      if (Object.keys(quiz.results || {}).length === quiz.questions.length) {
        onChange(await request<Quiz>(`/api/quizzes/${quiz.quiz_id}`)); onHome(); return;
      }
      const progress: Progress = { question_id: q.id, answer: result?.your_answer || choice, paused: true, seconds: elapsed() };
      try { await request(`/api/quizzes/${quiz.quiz_id}/progress`, progress, "PATCH"); }
      catch { throw new Error("进度未保存，请重试。当前选择已保留。"); }
      remember(progress.answer);
      onChange({ ...quiz, progress });
    });
  }
  async function next() {
    await action(async () => {
      if (index === quiz.questions.length - 1) {
        const fresh = await request<Quiz>(`/api/quizzes/${quiz.quiz_id}`);
        try { localStorage.removeItem(draftKey(quiz.quiz_id)); } catch { /* 服务器已有全部作答。 */ }
        onChange(fresh); setComplete(true); window.scrollTo({ top: 0, behavior: "instant" }); onComplete(); return;
      }
      const progress: Progress = { question_id: quiz.questions[index + 1].id, answer: "", paused: false, seconds: 0 };
      await request(`/api/quizzes/${quiz.quiz_id}/progress`, progress, "PATCH");
      try { localStorage.setItem(draftKey(quiz.quiz_id), JSON.stringify(progress)); } catch { /* 服务端进度优先。 */ }
      onChange({ ...quiz, progress }); setIndex(index + 1); setChoice(""); setNotice("");
      accumulated.current = 0; started.current = Date.now(); window.scrollTo({ top: 0, behavior: "instant" });
    });
  }
  async function refreshRecords(record: FeedbackRecord) {
    setNotice(feedbackNotice(record));
    const fresh = await request<Quiz>(`/api/quizzes/${quiz.quiz_id}`);
    onChange({ ...fresh, completed: quiz.completed }); await onRecordsChange();
  }
  if (complete) {
    const reviewItems = quiz.questions.filter((item) => quiz.results?.[item.id]).map((item) => ({
      ...item, ...quiz.results![item.id], question_id: item.id, lecture_id: quiz.lecture_id,
      root_id: item.id, has_attempt: true, next_review_on: "", history_count: 1, history: [],
    })) as ReviewItem[];
    return <article className={reviewing ? "practice-review" : "card practice-complete"} aria-label={reviewing ? "本套题回顾" : "练习结果"}>
      {reviewing ? <>
        <header className="practice-topbar"><button className="practice-link" onClick={() => setReviewing(false)}>← 返回结果</button><span>{pdfName} · 本套题回顾</span></header>
        <h1>回顾本套题</h1><p className="aux">仅本套 {quiz.questions.length} 题</p>
        {notice && <p role="status">{notice}</p>}
        <QuestionReviewList key={quiz.quiz_id} items={reviewItems} initialFilter="all" quizId={quiz.quiz_id} onFeedback={refreshRecords} />
      </> : <>
        <h1>练习完成</h1><p className="aux">{pdfName} · {quiz.questions.length} 题</p>
        {quiz.summary && <LearningSummary summary={quiz.summary} title="本次练习表现" />}
        <div className="btns"><Button variant="primary" onClick={() => setReviewing(true)}>回顾本套题</Button><Button onClick={onHome}>返回首页</Button></div>
      </>}
    </article>;
  }
  return <article className="practice-quiz" aria-label="练习题目" aria-busy={busy}>
    <header className="practice-topbar"><button className="practice-link" disabled={busy} title="保存进度并返回首页" onClick={() => void saveAndExit()}>← 返回</button>
      <span>{pdfName} · {index + 1}/{quiz.questions.length}</span></header>
    {quiz.mock && <p className="badge sim">模拟</p>}
    {quiz.notice && <p className="aux" role="status">{quiz.notice}</p>}
    <h1 className="practice-stem">{q.stem}</h1>
    <fieldset className="practice-options" disabled={busy || Boolean(result)}><legend className="practice-sr-only">选一个答案</legend>
      {q.options.map((o) => <label className="practice-option" key={o.id}><input type="radio" name={`answer-${q.id}`} value={o.id}
        checked={(result?.your_answer || choice) === o.id} onChange={() => { setChoice(o.id); remember(o.id); }} />
        <span>{o.id} {o.text}</span>
        {result && <span className="practice-option-note">{o.id === result.answer && "✓ 正确答案"}{o.id === result.your_answer && (o.id === result.answer ? " · 你的选择" : "你的选择")}</span>}
      </label>)}
    </fieldset>
    {result && <div aria-live="polite"><AnswerDetails result={result} /></div>}
    <div className="practice-primary-action">{result
      ? <Button variant="primary" disabled={busy} onClick={() => void next()}>{index === quiz.questions.length - 1 ? "完成练习" : "下一题"}</Button>
      : <Button variant="primary" disabled={!choice || busy} onClick={() => void submit()}>提交答案</Button>}</div>
    <FeedbackPanel disabled={busy} key={q.id} questionId={q.id} quizId={quiz.quiz_id} attemptId={result?.attempt_id}
      report={result?.report || quiz.reports?.[q.id]} onSaved={refreshRecords} />
    {busy && <p role="status" className="aux">正在保存…</p>}{error && <p role="alert">{error}</p>}
  </article>;
}
