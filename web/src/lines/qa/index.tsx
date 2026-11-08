import { Fragment, useEffect, useState } from "react";
import { Badge, Bubble, Button, Card } from "../../components/ui";
import { advancePlanCard, restorePlanAfterUndo } from "./state";
import type { PlanCard } from "../plan/types";
import type { PlanToday } from "../../api/types";
import type { Answer, Handoff, Lecture, Reference } from "./types";
import { requestJson, loadSource, submitPlanDecision } from "./transport";
import { OutlineCard } from "../v2/OutlineCard";
import { rememberAcceptance } from "../v2/GoalFlowV2";
import { acceptOutline, getPlanDate, patchOutline, type OutlineView, type UnitInput } from "../v2/api";
export { useQaConversation } from "./useQaConversation";
export type { Answer, Reference, Lecture } from "./types";

export function LecturePicker({ value, onChange, lectures, currentLectureId, disabled = false }: { value: string; onChange: (value: string) => void; lectures: Lecture[]; currentLectureId: string; disabled?: boolean }) {
  const current = lectures.find(item => item.id === currentLectureId);
  return <label className="lecture-pill">@ <select aria-label="指定讲次" value={value} disabled={disabled} onChange={event => onChange(event.target.value)}>
    <option value="">{current ? `当前学习：${current.title}${current.mock ? "（模拟）" : ""}` : "当前学习（暂无资料）"}</option>
    {lectures.map(item => <option key={item.id} value={item.id}>{item.title}{item.mock ? "（模拟）" : ""}</option>)}
  </select></label>;
}

export function QaSourceText({ text, quote }: { text: string; quote: string }) {
  const start = quote ? text.indexOf(quote) : -1;
  return <pre className="page">{start < 0 ? text : <>{text.slice(0, start)}<mark>{text.slice(start, start + quote.length)}</mark>{text.slice(start + quote.length)}</>}</pre>;
}

export function QaSourcePanel({ reference }: { reference: Reference }) {
  const [result, setResult] = useState<{ text: string; mock: boolean } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController(); setResult(null); setError("");
    loadSource(reference, controller.signal).then(setResult).catch(error => { if (error.name !== "AbortError") setError(error.message); });
    return () => controller.abort();
  }, [reference.lecture_id, reference.page, reference.quote]);
  return <section aria-label="引用原文"><h3>第 {reference.page} 页</h3>{error ? <p role="alert">{error}</p> : result ? <>{result.mock && <p className="badge sim">模拟资料</p>}<QaSourceText text={result.text} quote={reference.quote} /></> : <p role="status">正在读取原文…</p>}</section>;
}

export function CitedText({ answer, onReference }: { answer: Answer; onReference: (ref: Reference) => void }) {
  const parts = answer.text.split(/(【第\s*\d+\s*页】)/g);
  const occurrences = new Map<number, number>();
  return <span className="page">{parts.map((part, index) => {
    const marker = /^【第\s*(\d+)\s*页】$/.exec(part);
    if (!marker) return <Fragment key={index}>{part}</Fragment>;
    const page = Number(marker[1]);
    const occurrence = occurrences.get(page) || 0;
    occurrences.set(page, occurrence + 1);
    // Backend emits one marker per accepted reference, retaining reference order.
    const reference = answer.references.filter(ref => ref.page === page)[occurrence];
    return reference ? <Button key={index} type="button" aria-label={`查看第 ${reference.page} 页原文`} onClick={() => onReference(reference)}>{part}</Button> : <Fragment key={index}>{part}</Fragment>;
  })}</span>;
}

// 只有真正由模型回答的内容才标“AI 整理”、才收👍👎；定目标的固定提问、打开练习的提示不标。
const AI_INTENTS = new Set(["qa", "chat"]);

export function QaAnswer({ answer, onReference, onPlanChange, onQuickReply, onNextTask, onGoalAccepted, onRetry, active = true }: { answer: Answer; onReference: (ref: Reference) => void; onPlanChange?: (plan: PlanToday) => void; onQuickReply?: (text: string) => void; onNextTask?: () => void; onGoalAccepted?: () => void; onRetry?: () => void; active?: boolean }) {
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const [reason, setReason] = useState("");
  const [feedbackStatus, setFeedbackStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const [showReason, setShowReason] = useState(false);
  async function feedback(next: "up" | "down") {
    if (!answer.messageId || saving) return;
    setSaving(true); setFeedbackStatus("");
    try {
      await requestJson(`/api/qa/messages/${encodeURIComponent(answer.messageId)}/feedback`, { method: "POST", body: JSON.stringify({ rating: next, reason: next === "down" ? reason : "" }) });
      setRating(next); setFeedbackStatus("反馈已保存"); setShowReason(false);
    } catch (error) { setFeedbackStatus(error instanceof Error ? error.message : "反馈保存失败，请重试。"); }
    finally { setSaving(false); }
  }
  if (answer.role === "user") return <Bubble role="user">{answer.text}</Bubble>;
  const intent = answer.handoff?.intent || answer.intent || "qa";
  const aiMade = AI_INTENTS.has(intent);
  if (intent === "notice") return <p className="done-note" role="status">{answer.text}</p>;
  // 失败了且一个字都没出来：不留空气泡，只给一句说明 + “再试一次”。
  const empty = !answer.text.trim();
  return <div aria-label="小满回答" className="answer">{!(empty && answer.status !== "streaming") && <Bubble role="xiaoman">
    {aiMade && answer.status === "done" && <span className="ai-tag">AI 整理</span>}{aiMade && answer.mock && <Badge sim>模拟</Badge>}
    <CitedText answer={answer} onReference={onReference} /></Bubble>}
    {answer.status === "streaming" && <p className="aux" role="status">{empty ? "小满在想…" : "正在回答…"}</p>}
    {answer.error && <div className="answer-error" role="alert">{empty && answer.mock && <Badge sim>模拟</Badge>}<span>{answer.error}</span>{onRetry && active && <Button onClick={onRetry}>再试一次</Button>}</div>}
    {answer.references.length > 0 && <div className="btns">{answer.references.map((ref, i) => <Button key={i} type="button" onClick={() => onReference(ref)}>【第 {ref.page} 页】原句</Button>)}</div>}
    {aiMade && answer.status === "done" && answer.messageId && <div className="feedback-row" aria-label="回答反馈">
      <Button type="button" disabled={saving || rating === "up"} aria-label="赞同回答" onClick={() => void feedback("up")}>👍</Button>
      <Button type="button" disabled={saving} aria-label="反馈回答有误" onClick={() => { setShowReason(true); setFeedbackStatus(""); }}>👎</Button>
    </div>}
    {showReason && <form onSubmit={event => { event.preventDefault(); void feedback("down"); }}><label>哪里不对（可不填）<input aria-label="哪里不对" maxLength={1000} value={reason} onChange={event => setReason(event.target.value)} /></label><Button type="submit" disabled={saving}>提交反馈</Button><Button type="button" disabled={saving} onClick={() => setShowReason(false)}>取消</Button></form>}
    {feedbackStatus && <p role="status">{feedbackStatus}</p>}
    {answer.handoff && answer.status === "done" && <QaHandoff active={active} handoff={answer.handoff} onPlanChange={onPlanChange} onQuickReply={onQuickReply} onNextTask={onNextTask} onGoalAccepted={onGoalAccepted} />}
  </div>;
}

const QUIZ_KEY = "xm-open-quiz";
const todayKey = () => new Date().toLocaleDateString("sv-SE");
export function rememberQuiz(quizId: string) {
  try { localStorage.setItem(QUIZ_KEY, JSON.stringify({ quizId, day: todayKey() })); } catch { /* 存不了就不恢复 */ }
}
export function forgetQuiz(quizId?: string) {
  try {
    const raw = localStorage.getItem(QUIZ_KEY);
    if (raw && (!quizId || JSON.parse(raw).quizId === quizId)) localStorage.removeItem(QUIZ_KEY);
  } catch { /* 忽略 */ }
}
export function openQuizId(): string | null {
  try {
    const raw = localStorage.getItem(QUIZ_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw) as { quizId?: string; day?: string };
    return saved.day === todayKey() && typeof saved.quizId === "string" ? saved.quizId : null;
  } catch { return null; }
}

export function QaHandoff({ handoff, onPlanChange, onQuickReply, onNextTask, onGoalAccepted, active = true }: { handoff: Handoff; active?: boolean; onPlanChange?: (plan: PlanToday) => void; onQuickReply?: (text: string) => void; onNextTask?: () => void; onGoalAccepted?: () => void }) {
  if (handoff.intent === "goal") {
    return <GoalOutlineHandoff data={handoff.data} active={active} onQuickReply={onQuickReply} onAccepted={onGoalAccepted} />;
  }
  return handoff.intent === "plan" && handoff.data.card ? <NativePlanCard initial={handoff.data.card} active={active} onPlanChange={onPlanChange} /> : <LegacyHandoff handoff={handoff} active={active} onPlanChange={onPlanChange} onNextTask={onNextTask} />;
}

function GoalOutlineHandoff({ data, active, onQuickReply, onAccepted }: { data: Handoff["data"]; active: boolean; onQuickReply?: (text: string) => void; onAccepted?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState("");
  const [dismissed, setDismissed] = useState(false);
  const outline = data.outline as OutlineView | undefined;
  if (dismissed) return <p className="aux">已收起。今天的安排没有变。</p>;
  if (outline) {
    async function patch(units: UnitInput[]) {
      setBusy(true); setError("");
      const result = await patchOutline(outline!.id, units);
      setBusy(false);
      if (!result.ok) setError(result.message);
      return result.ok;
    }
    async function accept() {
      setBusy(true); setError("");
      const result = await acceptOutline(outline!.id);
      if (!result.ok) { setError(result.message); setBusy(false); return; }
      const day = await getPlanDate();
      if (day) rememberAcceptance(result.outline.id, day);
      // 不刷新页面：定目标的对话留在原处，左边和下面直接换成今天的安排。
      if (onAccepted) { setAccepted(true); setBusy(false); onAccepted(); }
      else window.location.reload();
    }
    if (accepted) return <p className="done-note" role="status">大纲定好了，共 {outline.units.length} 讲。今天的安排在下面。</p>;
    return <OutlineCard outline={outline} busy={busy} error={error} onPatch={patch} onAccept={() => void accept()} onDismiss={() => setDismissed(true)} />;
  }
  if (data.question && data.options) {
    // 问题本身已经在气泡里；这里只放快捷选项，答过之后收起，不再能点。
    if (!active) return null;
    return <div className="quick-replies" role="group" aria-label="定目标">
      {data.options.map((option) => (
        <Button key={option} disabled={!onQuickReply} onClick={() => onQuickReply?.(option)}>{option}</Button>
      ))}
    </div>;
  }
  return <Card as="section" aria-label="定目标"><h3>定目标</h3><p>好，我们来定「{data.goal}」。</p></Card>;
}
function LegacyHandoff({ handoff, onPlanChange, onNextTask, active = true }: { handoff: Handoff; active?: boolean; onPlanChange?: (plan: PlanToday) => void; onNextTask?: () => void }) {
  const [status, setStatus] = useState(handoff.data.status || "pending");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // 刷新后接着做：已经答过的题跳过，从第一道没答的开始。
  const answered = handoff.data.results || {};
  const firstOpen = Math.max(0, (handoff.data.questions || []).findIndex((item) => !answered[item.id]));
  const [questionIndex, setQuestionIndex] = useState(firstOpen);
  const [grade, setGrade] = useState<{ correct: boolean; analysis: string; label?: string; answer?: string; your_answer?: string } | null>(null);
  const [rightCount, setRightCount] = useState(() => Object.values(answered).filter((item) => item.correct).length);
  // 记住今天正在做的这组题，刷新页面后能接着做；做完就忘掉。
  useEffect(() => {
    if (handoff.intent === "quiz" && handoff.data.quiz_id && active) rememberQuiz(handoff.data.quiz_id);
  }, [handoff.intent, handoff.data.quiz_id, active]);
  const lastDone = Boolean(grade) && questionIndex + 1 >= (handoff.data.questions || []).length;
  useEffect(() => { if (lastDone) forgetQuiz(handoff.data.quiz_id); }, [lastDone, handoff.data.quiz_id]);
  const [dismissed, setDismissed] = useState(false);
  if (dismissed || (!active && status !== "executed" && status !== "undone")) return <p className="aux">已收起这张卡。未接受的建议不会改变安排。</p>;
  async function planAction(undo: boolean) {
    if (!handoff.data.id || busy) return;
    setBusy(true); setError("");
    try {
      const response = await requestJson<{ status: string; plan: PlanToday }>(undo ? `/api/actions/${encodeURIComponent(handoff.data.id)}/undo` : `/api/suggestions/${encodeURIComponent(handoff.data.id)}/accept`, { method: "POST" });
      setStatus(response.data.status); onPlanChange?.(response.data.plan);
    } catch (error) { setError(error instanceof Error ? error.message : "操作失败，请重试。"); }
    finally { setBusy(false); }
  }
  const questions = handoff.data.questions || [];
  const question = questions[questionIndex];
  async function attempt(answer: string) {
    if (!question || busy || grade) return;
    setBusy(true); setError("");
    try {
      const response = await requestJson<{ correct: boolean; analysis: string; label?: string; answer?: string; your_answer?: string }>("/api/attempts", { method: "POST", body: JSON.stringify({ question_id: question.id, answer, quiz_id: handoff.data.quiz_id || "", seconds: 0, confidence: "" }) });
      setGrade({ ...response.data, your_answer: response.data.your_answer || answer });
      if (response.data.correct) setRightCount(n => n + 1);
      // 做了就算完成：计划线会自动勾掉「练一练」，这里刷新左栏。
      try { onPlanChange?.((await requestJson<PlanToday>("/api/plan/today")).data); } catch { /* 刷新失败不影响作答 */ }
    } catch (error) { setError(error instanceof Error ? error.message : "答案提交失败，请重试。"); }
    finally { setBusy(false); }
  }
  return <Card as="section" aria-label={handoff.intent === "plan" ? "调整建议" : "练习题"} className={handoff.intent === "plan" ? undefined : "card-read"}>
    {(handoff.data.label === "模拟" || handoff.data.suggestion?.label === "模拟") && <p className="badge sim">模拟</p>}
    {handoff.intent === "plan" ? <><h3>{handoff.data.suggestion?.title || "调整建议"}</h3><p>{handoff.data.suggestion?.body}</p>
      {status === "executed" ? <><p>已按你的选择调整。</p><Button type="button" disabled={busy} onClick={() => void planAction(true)}>撤销</Button></> : status === "undone" ? <p>已撤销调整。</p> : <div className="btns"><Button type="button" variant="primary" disabled={busy || !handoff.data.id} onClick={() => void planAction(false)}>就这样</Button><Button type="button" disabled={busy} onClick={() => setDismissed(true)}>先不用</Button></div>}
    </> : question ? <>
      <div className="quiz-progress" aria-label={`第 ${questionIndex + 1} / ${questions.length} 题`}>
        <span style={{ width: `${((questionIndex + (grade ? 1 : 0)) / questions.length) * 100}%` }} />
      </div>
      <p className="aux">第 {questionIndex + 1} / {questions.length} 题</p>
      <h3>{question.stem}</h3>
      <div className="options">{question.options.map((option, i) => {
        const key = typeof option === "string" ? String.fromCharCode(65 + i) : option.id || option.key || String.fromCharCode(65 + i);
        const text = typeof option === "string" ? option : option.text || option.label || key;
        const mark = !grade ? "" : key === grade.answer ? "right" : key === grade.your_answer ? "wrong" : "dim";
        return <Button key={key} className={`option ${mark}`} type="button" disabled={busy || Boolean(grade)} aria-pressed={grade ? key === grade.your_answer : undefined} onClick={() => void attempt(key)}>
          <span className="option-key">{mark === "right" ? "✓" : mark === "wrong" ? "✗" : key}</span>{text}
        </Button>;
      })}</div>
      {grade && <div className={`quiz-feedback ${grade.correct ? "right" : "wrong"}`} role="status">
        <strong>{grade.correct ? "答对了！" : `差一点，正确答案是 ${grade.answer || ""}`}</strong>
        {grade.analysis && <p>{grade.analysis}</p>}
        {!grade.correct && <p className="aux">这题已放进错题本，过几天再练一次。</p>}
        {grade.label === "模拟" && <p className="badge sim">模拟判分</p>}
        {questionIndex + 1 < questions.length
          ? <Button variant="primary" type="button" onClick={() => { setQuestionIndex(i => i + 1); setGrade(null); }}>下一题</Button>
          : <>
            <p className="quiz-done">这组练完了：答对 {rightCount} / {questions.length} 题。</p>
            {onNextTask && <Button variant="primary" type="button" onClick={onNextTask}>继续下一件</Button>}
          </>}
      </div>}
    </> : <p>当前没有可用题目，请换一讲。</p>}
    {error && <p role="alert">{error}</p>}
  </Card>;
}

function NativePlanCard({ initial, active, onPlanChange }: { initial: PlanCard; active: boolean; onPlanChange?: (plan: PlanToday) => void }) {
  const [card, setCard] = useState(initial);
  const [previous, setPrevious] = useState<PlanCard | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [examDate, setExamDate] = useState("");
  async function decide(kind: "accept" | "dismiss" | "undo", option?: string) {
    setBusy(true); setError("");
    try {
      const response = await submitPlanDecision(card.id, kind, option, examDate);
      const next = advancePlanCard(card, response.data);
      setCard(next.card); if (next.previous) setPrevious(next.previous);
      if (response.data.plan) onPlanChange?.(response.data.plan);
    } catch (error) { setError(error instanceof Error ? error.message : "操作失败，请重试。"); }
    finally { setBusy(false); }
  }
  async function undoPrevious() {
    if (!previous) return;
    setBusy(true); setError("");
    try { const response = await submitPlanDecision(previous.id, "undo"); const restored = restorePlanAfterUndo(response.data); setCard(restored.card); setPrevious(restored.previous); if (response.data.plan) onPlanChange?.(response.data.plan); }
    catch (error) { setError(error instanceof Error ? error.message : "撤销失败，请重试。"); }
    finally { setBusy(false); }
  }
  if (!active && card.status !== "executed" && !previous) return <p className="aux">已收起这张建议，未确认的安排不会生效。</p>;
  return <Card aria-label="调整建议">{previous && <div className="btns"><span>{previous.collapsed_text || "上一项已确认"}</span><Button disabled={busy} onClick={()=>void undoPrevious()}>撤销上一项</Button></div>}<header><h3>{card.title}</h3><Badge sim={card.badge === "模拟"}>{card.badge}</Badge></header><ul>{card.lines.map((line,i)=><li key={i}>{line}</li>)}</ul>
    {card.status === "executed" ? <><p>{card.collapsed_text || "已按你的选择调整。"}</p><Button disabled={busy} onClick={()=>void decide("undo")}>撤销</Button></> : card.status === "pending" && active ? <>
      {card.options.some(option=>option.needs === "exam_date") && <label>新的考试日期<input type="date" value={examDate} onChange={event=>setExamDate(event.target.value)} /></label>}
      <div className="btns">{card.options.map((option,i)=><Button key={option.id} variant={i === 0 ? "primary" : "secondary"} disabled={busy || (option.needs === "exam_date" && !examDate)} onClick={()=>void decide("accept",option.id)}>{option.label}</Button>)}<Button disabled={busy} onClick={()=>void decide("dismiss")}>{card.decline_label || "先不用"}</Button></div>
    </> : <p>{card.status === "undone" ? "已撤销调整。" : "已收起，安排未改变。"}</p>}
    {error && <p role="alert">{error}</p>}
  </Card>;
}
