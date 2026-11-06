import { useEffect, useRef, useState } from "react";
import { ApiError, request, type FeedbackRecord, type Material, type ReviewItem, type Progress, type Quiz, type Stats } from "./api";
import { feedbackNotice } from "./FeedbackPanel";
import { QuestionReviewList } from "./QuestionReviewList";
import { LearningSummary } from "./LearningSummary";
import { QuizCard } from "./QuizCard";
import { LoadingRing } from "./LoadingRing";

type Props = { lectureId?: string; taskId?: string; onActiveChange?: (active: boolean) => void; onComplete?: () => void };
const STORAGE = "xiaoman-practice-active-quiz-v1";
const VIEW = "xiaoman-practice-view-v1";
type View = "home" | "quiz" | "review";
function initialView(): View {
  try { const value = localStorage.getItem(VIEW); return value === "quiz" || value === "review" ? value : "home"; } catch { return "home"; }
}
const SELECTED = "xiaoman-practice-selected-lecture-v1";

export function PracticeWorkbench({ lectureId = "", taskId = "", onActiveChange, onComplete }: Props) {
  const [lecture, setLecture] = useState(lectureId);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [count, setCount] = useState("5");
  const [view, setView] = useState<View>(initialView);
  const [difficulty, setDifficulty] = useState("easy");
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [pausedQuizzes, setPausedQuizzes] = useState<Quiz[]>([]);
  const [mistakes, setMistakes] = useState<ReviewItem[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const pending = useRef(false);
  const refreshVersion = useRef(0);
  const active = Boolean(view === "quiz" && quiz && !quiz.completed && !quiz.progress?.paused);
  const requestedCount = Number(count);
  const validCount = count.trim() !== "" && Number.isInteger(requestedCount) && requestedCount >= 1 && requestedCount <= 15;
  const selected = materials.find((item) => item.lecture_id === lecture);

  async function refresh(id = lecture) {
    const version = ++refreshVersion.current;
    const query = `?lecture_id=${encodeURIComponent(id)}`;
    const [library, summary] = await Promise.all([
      request<{ items: ReviewItem[] }>(`/api/practice/learning${query}`), request<Stats>(`/api/practice/stats${query}`),
    ]);
    if (version !== refreshVersion.current) return;
    setMistakes(library.items); setStats(summary);
  }

  async function refreshFromHome(record: FeedbackRecord) {
    setMessage(feedbackNotice(record));
    await refresh();
    if (quiz?.completed) {
      const fresh = await request<Quiz>(`/api/quizzes/${quiz.quiz_id}`);
      setQuiz(fresh);
    }
  }

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const session = await fetch("/api/session", { method: "POST", credentials: "include" });
        if (!session.ok) throw new Error("后端尚未接通，请先启动后端再刷新。");
        const [files, paused] = await Promise.all([
          request<{ items: Material[] }>("/api/practice/materials"),
          request<{ items: Quiz[] }>("/api/practice/paused"),
        ]);
        if (cancelled) return;
        setMaterials(files.items);
        setPausedQuizzes(paused.items);
        const preferred = lectureId || localStorage.getItem(SELECTED);
        const initial = files.items.find((item) => item.lecture_id === preferred)?.lecture_id || files.items[0]?.lecture_id || "";
        setLecture(initial);
        const saved = localStorage.getItem(STORAGE);
        if (saved) {
          try {
            const restored = await request<Quiz>(`/api/quizzes/${encodeURIComponent(saved)}`);
            if (!cancelled) {
              if (!restored.completed && restored.progress?.paused) {
                setPausedQuizzes((items) => [restored, ...items.filter((item) => item.quiz_id !== restored.quiz_id)]);
                localStorage.removeItem(STORAGE);
                if (view === "quiz") navigate("home");
              } else if (!restored.completed || restored.lecture_id === initial) {
                setQuiz(restored);
                if (!restored.completed) {
                  setPausedQuizzes((items) => [restored, ...items.filter((item) => item.quiz_id !== restored.quiz_id)]);
                  setLecture(restored.lecture_id);
                }
              } else if (view === "quiz") navigate("home");
            }
          } catch (err) {
            if (err instanceof ApiError && err.status === 404) { localStorage.removeItem(STORAGE); navigate("home"); }
            else throw err;
          }
        } else if (view === "quiz") navigate("home");
        if (!cancelled) { await refresh(initial); setReady(true); }
      } catch (err) { if (!cancelled) setError(err instanceof Error ? err.message : "加载失败，请刷新。"); }
    })();
    return () => { cancelled = true; };
  }, [lectureId]);

  useEffect(() => { if (ready) void refresh(lecture).catch(() => setError("练习记录暂未刷新，请重试。")); }, [lecture, ready]);

  useEffect(() => { onActiveChange?.(active); }, [active, onActiveChange]);

  function navigate(next: View) { setView(next); localStorage.setItem(VIEW, next); setMessage(""); setError(""); window.scrollTo({ top: 0, behavior: "instant" }); }

  function changeQuiz(next: Quiz) {
    if (!next.completed && next.progress?.paused) {
      setPausedQuizzes((items) => [next, ...items.filter((item) => item.quiz_id !== next.quiz_id)]);
      setQuiz(null); localStorage.removeItem(STORAGE); navigate("home");
    } else {
      setPausedQuizzes((items) => items.filter((item) => item.quiz_id !== next.quiz_id));
      localStorage.setItem(STORAGE, next.quiz_id); setQuiz(next);
    }
  }

  async function resume(saved: Quiz) {
    if (pending.current || active) return;
    pending.current = true; setBusy(true); setError(""); setPhase("正在恢复之前的进度…");
    try {
      const fresh = await request<Quiz>(`/api/quizzes/${saved.quiz_id}`);
      if (!fresh.completed) {
        const progress: Progress = { question_id: fresh.progress?.question_id || fresh.questions[0].id,
          answer: fresh.progress?.answer || "", seconds: fresh.progress?.seconds || 0, paused: false };
        await request(`/api/quizzes/${fresh.quiz_id}/progress`, progress, "PATCH");
        setLecture(fresh.lecture_id); localStorage.setItem(SELECTED, fresh.lecture_id); changeQuiz({ ...fresh, progress }); navigate("quiz");
      } else { changeQuiz(fresh); navigate("quiz"); }
    } catch (err) { setError(err instanceof Error ? err.message : "暂时没能恢复，请重试。"); }
    finally { pending.current = false; setBusy(false); setPhase(""); }
  }

  function selectLecture(id: string) {
    setLecture(id); localStorage.setItem(SELECTED, id);
    setQuiz(null); setStats(null); setMistakes([]); localStorage.removeItem(STORAGE); setMessage("");
    // 重复上传会复用同一 lecture_id，依赖变化的 effect 不会再次触发。
    if (id === lecture) void refresh(id).catch(() => setError("学习概览未刷新，请重试。"));
  }

  async function upload(file: File, input: HTMLInputElement) {
    if (pending.current || active) return;
    pending.current = true; setBusy(true); setError(""); setMessage("");
    setPhase("正在上传并按页读取 PDF…");
    try {
      const body = new FormData(); body.append("file", file);
      const material = await request<Material>("/api/practice/materials", body);
      setMaterials((list) => [material, ...list.filter((item) => item.lecture_id !== material.lecture_id)]);
      selectLecture(material.lecture_id);
      setMessage(`已读取 ${material.page_count} 页，可以开始练习。`);
    } catch (err) { setError(err instanceof Error ? err.message : "PDF 没能读取，请重试。"); }
    finally { input.value = ""; pending.current = false; setBusy(false); setPhase(""); }
  }

  async function start(review?: ReviewItem[]) {
    if (pending.current || active || (!review && !validCount)) return;
    if (review && (!review.length || review.length > 15 || review.some((item) => !item.has_attempt || item.excluded))) {
      setError("请选择1到15道可复习的题目。"); return;
    }
    pending.current = true; setBusy(true); setError(""); setMessage("");
    setPhase(review ? "正在生成变式题…" : "稍等哦~正在把知识点按在地上，摩擦成题~");
    try {
      const data = await request<Quiz>("/api/quizzes", {
        lecture_id: review?.[0]?.lecture_id || lecture, count: review ? review.length : requestedCount, difficulty,
        mode: review ? "review" : "practice", question_ids: review?.map((item) => item.question_id) || [],
        task_id: review ? "" : taskId,
      });
      localStorage.setItem(STORAGE, data.quiz_id); setQuiz(data); navigate("quiz");
    } catch (err) { setError(err instanceof Error ? err.message : "出题失败，请重试。"); }
    finally { pending.current = false; setBusy(false); setPhase(""); }
  }

  const recent = pausedQuizzes[0];
  const filename = (id: string) => materials.find((item) => item.lecture_id === id)?.filename || "之前的 PDF";
  return <main className={`stream practice-app practice-view-${view}`}>
    {error && <p role="alert">{error}</p>}
    {message && <p role="status" className="practice-notice">{message}</p>}
    {busy && <LoadingRing text={phase} />}
    {!ready ? <p role="status">正在读取学习记录…</p> : view === "quiz" && quiz ?
      <QuizCard key={quiz.quiz_id} quiz={quiz} pdfName={filename(quiz.lecture_id)} onChange={changeQuiz}
        onHome={() => navigate("home")} onRecordsChange={() => refresh(quiz.lecture_id)} onComplete={() => {
          void refresh(quiz.lecture_id).catch(() => setError("作答已保存，概览未刷新，请重试。")); onComplete?.();
        }} /> : view === "review" ? <>
      <header className="practice-topbar"><button className="practice-link" disabled={busy} onClick={() => navigate("home")}>← 返回首页</button><span>{filename(lecture)}</span></header>
      <h1>做题历史</h1><p className="aux">当前 PDF · 全部已答题</p>
      <QuestionReviewList key={lecture} items={mistakes} busy={busy} onStart={(items) => void start(items)} onFeedback={refreshFromHome} />
    </> : <>
      <h1>小满 · 练一练</h1>
      {recent && <section className="card practice-resume" aria-label="待继续的练习"><h2 className="practice-sr-only">继续练习</h2>
        <div className="practice-resume-latest">
          <p className="practice-resume-file" title={filename(recent.lecture_id)}>{filename(recent.lecture_id)}</p>
          <span className="practice-resume-progress">已答 {Object.keys(recent.results || {}).length}/{recent.questions.length} 题</span>
          <button className="btn primary" disabled={busy} onClick={() => void resume(recent)}>继续练习</button>
        </div>
        {pausedQuizzes.length > 1 && <details><summary>更多（{pausedQuizzes.length - 1}）</summary>
          {pausedQuizzes.slice(1).map((saved) => <div className="practice-resume-row" key={saved.quiz_id}>
            <span title={filename(saved.lecture_id)}>{filename(saved.lecture_id)} · 已答 {Object.keys(saved.results || {}).length}/{saved.questions.length} 题</span>
            <button className="practice-link" data-resume-id={saved.quiz_id} disabled={busy} onClick={() => void resume(saved)}>继续这套练习</button>
          </div>)}
        </details>}
      </section>}
      <section className="card practice-create" aria-label="新建练习"><h2>新建练习</h2>
        <div className="practice-material-row">
          <label className="practice-material-select">选择已有 PDF <select aria-label="当前学习资料" value={lecture} disabled={busy || !materials.length} onChange={(e) => selectLecture(e.target.value)}>
            {!materials.length && <option value="">暂无可用 PDF</option>}
            {materials.map((item) => <option key={item.lecture_id} value={item.lecture_id}>{item.filename}</option>)}
          </select></label>
          <label className="practice-upload practice-link" aria-disabled={busy}>上传 PDF<input type="file" accept="application/pdf,.pdf" aria-label="上传学习 PDF" disabled={busy}
            onChange={(event) => { const file = event.currentTarget.files?.[0]; if (file) void upload(file, event.currentTarget); }} /></label>
        </div>
        {selected && <p className="aux">{selected.page_count} 页 · 已读取</p>}
        <details className="practice-stat-details"><summary>资料要求</summary><p>文字版 PDF，每份不超过20 MB、100页。</p></details>
        <div className="practice-settings"><label>题数 <input aria-label="题目数量" type="number" min="1" max="15" step="1" inputMode="numeric" value={count} disabled={busy} onChange={(e) => setCount(e.target.value)} /><span className="aux">1–15 题</span></label>
          <label>难度 <select aria-label="题目难度" value={difficulty} disabled={busy} onChange={(e) => setDifficulty(e.target.value)}><option value="easy">易</option><option value="medium">中</option><option value="hard">难</option></select></label>
        </div>
        {!validCount && <p role="alert">请输入1到15之间的整数。</p>}
        <div className="practice-primary-action"><button className={recent ? "btn" : "btn primary"} disabled={busy || !selected || !validCount} onClick={() => void start()}>开始练习</button></div>
      </section>
      {selected && stats && <section className="card"><LearningSummary summary={stats} title="学习概览"
        action={<button className="practice-link" disabled={busy} onClick={() => navigate("review")}>去复习 →</button>} />
      </section>}
    </>}
  </main>;
}
