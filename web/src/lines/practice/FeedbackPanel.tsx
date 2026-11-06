import { useId, useRef, useState } from "react";
import { request, type FeedbackRecord } from "./api";

export const feedbackNotice = (record: FeedbackRecord) => record.active ? "已记录，本题暂不计入统计。" : "已撤回，本题已恢复参与统计。";
type Props = { questionId: string; quizId?: string; attemptId?: string; disabled?: boolean; inlineNotice?: boolean; report?: FeedbackRecord | null;
  onSaved: (record: FeedbackRecord) => Promise<void> };
export function FeedbackPanel({ questionId, quizId = "", attemptId = "", disabled = false, inlineNotice = true, report, onSaved }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [editing, setEditing] = useState(false);
  const [category, setCategory] = useState(report?.category || "");
  const [reason, setReason] = useState(report?.reason || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [saved, setSaved] = useState<FeedbackRecord | null>(null);
  const pending = useRef(false);
  const current = saved || report;
  const active = Boolean(current?.active);
  async function send(withdraw = false) {
    if (pending.current || (!withdraw && !category)) return;
    pending.current = true; setBusy(true); setError(""); setMessage("");
    try {
      const value = withdraw
        ? await request<FeedbackRecord>(`/api/practice/reports/${encodeURIComponent(current?.question_id || questionId)}`, undefined, "DELETE")
        : await request<FeedbackRecord>("/api/practice/reports", { question_id: current?.question_id || questionId,
          quiz_id: current?.question_id && current.question_id !== questionId ? "" : quizId,
          attempt_id: current?.question_id && current.question_id !== questionId ? "" : attemptId, category, reason });
      setSaved(value); setMessage(feedbackNotice(value)); setEditing(false);
      // 先关闭弹窗再刷新，避免撤回后筛选隐藏题目时留下遮罩。
      dialog.current?.close();
      try { await onSaved(value); setSaved(null); } catch { setError("反馈已保存，列表未刷新，请刷新页面查看。"); }
    } catch {
      setError(withdraw ? "撤回未保存，请重试。原反馈仍然有效。" : "反馈未保存，请重试。你填写的内容已保留。");
    } finally { pending.current = false; setBusy(false); }
  }
  return <div className="question-feedback">
    <button className="practice-link" disabled={busy || disabled} onClick={() => {
      setEditing(!active);
      setError(""); dialog.current?.showModal();
    }}>{active ? "已反馈 · 查看" : "反馈题目问题"}</button>
    {inlineNotice && message && <p role="status" className="aux">{message}</p>}
    {error && !dialog.current?.open && <p role="alert">{error}</p>}
    <dialog className="practice-dialog" ref={dialog} aria-labelledby={titleId} onCancel={(event) => { if (pending.current) event.preventDefault(); }}>
      <h2 id={titleId}>反馈题目问题</h2>
      {active && !editing ? <>
        <p className="aux">本题暂不计入学习统计和推荐复习，原作答记录仍保留。</p>
        <p>问题类型：{current?.category_label}</p><p>补充说明：{current?.reason || "未填写"}</p>
        <p className="aux">已保存在服务端{current?.updated_at && ` · ${new Date(current.updated_at).toLocaleString()}`}</p>
        <div className="btns"><button className="btn" disabled={busy} onClick={() => { setCategory(current?.category || ""); setReason(current?.reason || ""); setEditing(true); }}>编辑反馈</button>
          <button className="btn" disabled={busy} onClick={() => void send(true)}>{busy ? "提交中…" : "撤回反馈"}</button>
          <button className="practice-link" disabled={busy} onClick={() => dialog.current?.close()}>关闭</button></div>
        <p className="aux">撤回后，按原作答恢复分类和统计。</p>
      </> : <>
        <p className="aux">提交后，本题暂不计入统计，仍可查看原题和解析。</p>
        <label>问题类型 <select aria-label="问题类型" value={category} disabled={busy} onChange={(e) => setCategory(e.target.value)}>
          <option value="">请选择</option><option value="answer">答案或解析不对</option><option value="ambiguous">题干或选项有歧义</option><option value="source">出处对不上</option><option value="other">其他问题</option>
        </select></label>
        <p><label>补充说明（选填）<textarea value={reason} disabled={busy} maxLength={1000} rows={3} onChange={(e) => setReason(e.target.value)} /></label></p>
        <div className="btns practice-dialog-actions"><button className="btn" disabled={busy} onClick={() => { dialog.current?.close(); }}>取消</button>
          <button className="btn primary" disabled={busy || !category} onClick={() => void send()}>{busy ? "提交中…" : "提交反馈"}</button></div>
      </>}
      {error && <p role="alert">{error}</p>}
    </dialog>
  </div>;
}
