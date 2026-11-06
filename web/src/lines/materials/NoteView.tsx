import { useEffect, useRef, useState } from "react";
import { Badge, Button } from "../../components/ui";
import { saveNote, type Citation, type MaterialNote, type NoteContent } from "./api";
import { cloneNoteContent, contentForSave, noteDraftError, quoteParts } from "./notes";

type Props = { note: MaterialNote; onSaved: (note: MaterialNote) => void; onCitation: (citation: Citation) => void };

function Source({ citation, onClick }: { citation: Citation; onClick: (citation: Citation) => void }) {
  return <Button onClick={() => onClick(citation)} aria-label={`查看第 ${citation.page} 页出处`}>第 {citation.page} 页</Button>;
}

export function OriginalView({ text, citation }: { text: string; citation: Citation | null }) {
  const parts = quoteParts(text, citation?.quote);
  return (
    <div>
      {citation && <p className="aux">第 {citation.page} 页出处{parts.match ? " · 原句已高亮" : " · 原句可能因 PDF 排版而有差异，请核对原文"}</p>}
      <pre className="page">{parts.before}{parts.match && <mark>{parts.match}</mark>}{parts.after}</pre>
    </div>
  );
}

export function NoteView({ note, onSaved, onCitation }: Props) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(note.title);
  const [draft, setDraft] = useState<NoteContent>(() => cloneNoteContent(note.content));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const operation = useRef<AbortController | null>(null);

  useEffect(() => {
    setEditing(false); setTitle(note.title); setDraft(cloneNoteContent(note.content)); setError(""); setMessage(""); setSaving(false);
    return () => { operation.current?.abort(); };
  }, [note.id]);

  useEffect(() => {
    // 新的读取结果只刷新阅读态，不能覆盖用户正在输入的草稿。
    if (!editing) { setTitle(note.title); setDraft(cloneNoteContent(note.content)); }
  }, [note, editing]);

  function cancel() {
    setEditing(false); setTitle(note.title); setDraft(cloneNoteContent(note.content)); setError(""); setMessage("");
  }

  async function save() {
    const invalid = noteDraftError(title, draft);
    if (invalid) { setError(invalid); return; }
    operation.current?.abort();
    const controller = new AbortController(); operation.current = controller;
    setSaving(true); setError(""); setMessage("");
    try {
      const saved = await saveNote(note.id, contentForSave(draft), title.trim(), controller.signal);
      if (controller.signal.aborted) return;
      onSaved(saved); setEditing(false); setMessage("已保存，刷新后也会保留你的修改。");
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "保存失败，你的修改还在，请重试。");
    } finally {
      if (!controller.signal.aborted) setSaving(false);
    }
  }

  return (
    <section aria-label="学习笔记" aria-busy={saving}>
      <Badge>{note.label}</Badge>
      {note.edited_by_user && <p className="aux">你已修改并保存这份笔记，重新整理不会覆盖它。</p>}
      {editing ? (
        <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
          <label><p>笔记标题</p><input aria-label="笔记标题" value={title} maxLength={160} disabled={saving} onChange={(event) => setTitle(event.target.value)} /></label>
          <h3>本讲重点</h3>
          {draft.summaries.map((item, index) => (
            <div key={index}>
              <label><p>重点 {index + 1}</p><textarea className="page" aria-label={`重点 ${index + 1}`} rows={3} cols={24} value={item.text} disabled={saving} onChange={(event) => setDraft((current) => ({ ...current, summaries: current.summaries.map((row, at) => at === index ? { ...row, text: event.target.value } : row) }))} /></label>
              <p className="aux">出处：第 {item.page} 页 · {item.quote}</p>
            </div>
          ))}
          <h3>知识点</h3>
          {draft.knowledge_points.map((item, index) => (
            <div key={item.id || index}>
              <label><p>知识点 {index + 1} 名称</p><input aria-label={`知识点 ${index + 1} 名称`} value={item.name} disabled={saving} onChange={(event) => setDraft((current) => ({ ...current, knowledge_points: current.knowledge_points.map((row, at) => at === index ? { ...row, name: event.target.value } : row) }))} /></label>
              <label><p>解释</p><textarea className="page" aria-label={`知识点 ${index + 1} 解释`} rows={3} cols={24} value={item.explanation} disabled={saving} onChange={(event) => setDraft((current) => ({ ...current, knowledge_points: current.knowledge_points.map((row, at) => at === index ? { ...row, explanation: event.target.value } : row) }))} /></label>
              <p className="aux">出处：第 {item.page} 页 · {item.quote}</p>
            </div>
          ))}
          <h3>术语</h3>
          {draft.terms.map((item, index) => (
            <div key={index}>
              <label><p>术语 {index + 1}</p><input aria-label={`术语 ${index + 1}`} value={item.term} disabled={saving} onChange={(event) => setDraft((current) => ({ ...current, terms: current.terms.map((row, at) => at === index ? { ...row, term: event.target.value } : row) }))} /></label>
              <label><p>解释</p><textarea className="page" aria-label={`术语 ${index + 1} 解释`} rows={3} cols={24} value={item.definition} disabled={saving} onChange={(event) => setDraft((current) => ({ ...current, terms: current.terms.map((row, at) => at === index ? { ...row, definition: event.target.value } : row) }))} /></label>
              <p className="aux">出处：第 {item.page} 页 · {item.quote}</p>
            </div>
          ))}
          {error && <p role="alert">{error}</p>}
          <div className="btns"><Button type="submit" variant="primary" disabled={saving}>{saving ? "正在保存……" : "保存修改"}</Button><Button disabled={saving} onClick={cancel}>取消</Button></div>
        </form>
      ) : (
        <div>
          <h3>{note.title}</h3>
          <p className="aux">{note.content.knowledge_points.length} 个知识点 · {note.content.terms.length} 个术语</p>
          <Button onClick={() => { setError(""); setMessage(""); setEditing(true); }}>修改笔记</Button>
          <h3>本讲重点</h3>
          <ol>{note.content.summaries.map((item, index) => <li key={index}><p>{item.text}</p><Source citation={item} onClick={onCitation} /></li>)}</ol>
          <h3>知识点</h3>
          {note.content.knowledge_points.map((item, index) => <section key={item.id || index}><h4>{item.name}</h4><p>{item.explanation}</p><Source citation={item} onClick={onCitation} /></section>)}
          <h3>术语</h3>
          {note.content.terms.map((item, index) => <section key={index}><h4>{item.term}</h4><p>{item.definition}</p><Source citation={item} onClick={onCitation} /></section>)}
        </div>
      )}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
