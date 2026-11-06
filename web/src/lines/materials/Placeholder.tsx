import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Badge, Button, Card } from "../../components/ui";
import { ensureSession } from "../../api/client";
import { beginParsing, beginSummary, createUpload, isProcessing, listFiles, readNote, readPages, readStatus, statusText, uploadBytes, validatePdf, type MaterialNote, type MaterialPage, type MaterialStatus } from "./api";

export type MaterialsHandle = { chooseFile: () => void; uploadFile: (file: File) => void; rejectDrop: () => void; openNote: () => void };
type Props = {
  lectureId: string;
  enabled: boolean;
  currentNote?: MaterialNote | null;
  onOpenOriginal: (pages: MaterialPage[], lectureId: string) => void;
  onOpenNote: (note: MaterialNote | null) => void;
  onReady?: () => void;
  onTextReady?: () => void;
  showIdle?: boolean;
};

function pause(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const onAbort = () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); };
    const timer = window.setTimeout(() => { signal.removeEventListener("abort", onAbort); resolve(); }, 600);
    signal.addEventListener("abort", onAbort, { once: true });
    if (signal.aborted) onAbort();
  });
}

export const MaterialsLine = forwardRef<MaterialsHandle, Props>(function MaterialsLine({ lectureId, enabled, currentNote, onOpenOriginal, onOpenNote, onReady, onTextReady, showIdle = true }, ref) {
  const input = useRef<HTMLInputElement>(null);
  const operation = useRef<AbortController | null>(null);
  const lastFile = useRef<File | null>(null);
  const active = useRef(false);
  const announcedNote = useRef("");
  const announcedText = useRef("");
  const [status, setStatus] = useState<MaterialStatus | null>(null);
  const [preview, setPreview] = useState<MaterialNote | null>(null);
  const [filename, setFilename] = useState("");
  const [phase, setPhase] = useState<"idle" | "uploading" | "processing" | "summarizing" | "opening">("idle");
  const [error, setError] = useState("");
  const busy = phase !== "idle";
  const displayNote = currentNote && currentNote.lecture_id === lectureId && currentNote.id === status?.note_id ? currentNote : preview?.lecture_id === lectureId ? preview : null;

  function announceText(current: MaterialStatus) {
    if (["parsed", "ready"].includes(current.parse_status) && announcedText.current !== current.id) {
      announcedText.current = current.id; onTextReady?.();
    }
  }

  async function loadPreview(current: MaterialStatus, signal: AbortSignal) {
    announceText(current);
    if (!current.notes_ready || !current.note_id) { setPreview(null); return; }
    const note = await readNote(current.note_id, signal);
    if (signal.aborted) return;
    if (note.lecture_id !== current.lecture_id) throw new Error("笔记与当前讲次不一致，请重新加载。");
    setPreview(note);
    if (announcedNote.current !== note.id) { announcedNote.current = note.id; onReady?.(); }
  }

  async function follow(current: MaterialStatus, signal: AbortSignal) {
    const deadline = Date.now() + 240_000;
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");
    setStatus(current); announceText(current);
    while (isProcessing(current)) {
      if (Date.now() > deadline) throw new Error("处理时间较长，文件已保留。稍后重新打开页面查看进度。");
      await pause(signal);
      current = await readStatus(current.id, signal);
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      setStatus(current); announceText(current);
    }
    await loadPreview(current, signal);
    return current;
  }

  useEffect(() => {
    setStatus(null); setPreview(null); setFilename(""); setError(""); setPhase("idle"); lastFile.current = null; announcedNote.current = ""; announcedText.current = "";
    if (!enabled) return;
    const controller = new AbortController();
    operation.current = controller;
    void listFiles(controller.signal).then(async ({ items }) => {
      const latest = items.find((item) => item.lecture_id === lectureId);
      if (!latest || controller.signal.aborted) return;
      setFilename(latest.filename); setStatus(latest);
      if (isProcessing(latest)) {
        active.current = true; setPhase("processing");
        await follow(latest, controller.signal);
      } else await loadPreview(latest, controller.signal);
    }).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "读取上传记录失败，请重试。");
    }).finally(() => {
      if (!controller.signal.aborted) { active.current = false; setPhase("idle"); }
    });
    return () => { controller.abort(); operation.current?.abort(); active.current = false; };
  }, [lectureId, enabled]);

  async function run(file: File | null, retry = false) {
    if (active.current || !enabled) return;
    if (file) { const invalid = validatePdf(file); if (invalid) { setError(invalid); return; } }
    const chosenLecture = lectureId;
    operation.current?.abort();
    const controller = new AbortController();
    operation.current = controller; active.current = true;
    setError(""); setPhase(retry ? "processing" : "uploading");
    if (file) { lastFile.current = file; setFilename(file.name); setStatus(null); setPreview(null); }
    try {
      if (!await ensureSession()) throw new Error("没有连上后端，请确认服务已启动后重试。");
      if (controller.signal.aborted) return;
      let fileId = retry ? status?.id : undefined;
      if (!fileId && file) {
        const target = await createUpload(file, controller.signal);
        fileId = target.file_id;
        const uploaded = await uploadBytes(target, file, controller.signal);
        if (controller.signal.aborted) return;
        setStatus(uploaded);
      }
      if (!fileId) throw new Error("请重新选择 PDF 文件。");
      setPhase("processing");
      await follow(await beginParsing(fileId, chosenLecture, controller.signal), controller.signal);
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "处理失败，请重试。");
    } finally {
      if (!controller.signal.aborted) { active.current = false; setPhase("idle"); }
    }
  }

  async function summarize() {
    if (active.current || !status) return;
    operation.current?.abort();
    const controller = new AbortController(); operation.current = controller; active.current = true;
    setError(""); setPhase("summarizing");
    try { await follow(await beginSummary(status.id, controller.signal), controller.signal); }
    catch (err) { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "整理暂未完成，可以重试。"); }
    finally { if (!controller.signal.aborted) { active.current = false; setPhase("idle"); } }
  }

  async function openNote() {
    if (active.current) return;
    if (!status?.note_id || !status.notes_ready) { onOpenNote(null); return; }
    operation.current?.abort();
    const controller = new AbortController(); operation.current = controller; active.current = true;
    setPhase("opening"); setError("");
    try {
      const note = await readNote(status.note_id, controller.signal);
      if (controller.signal.aborted) return;
      if (note.lecture_id !== lectureId) throw new Error("笔记与当前讲次不一致，请重新加载。");
      setPreview(note); onOpenNote(note);
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "打开笔记失败，请重试。");
    } finally { if (!controller.signal.aborted) { active.current = false; setPhase("idle"); } }
  }

  function chooseFile() { if (!active.current && enabled) input.current?.click(); }
  useImperativeHandle(ref, () => ({ chooseFile, uploadFile: (file) => { void run(file); }, rejectDrop: () => { if (!active.current) setError("一次只上传一份 PDF，请重新拖入。"); }, openNote: () => { void openNote(); } }));

  async function openOriginal() {
    if (active.current || !status) return;
    const controller = new AbortController();
    operation.current?.abort(); operation.current = controller; active.current = true;
    setPhase("opening"); setError("");
    try {
      const result = await readPages(status.lecture_id, controller.signal, status.id);
      if (controller.signal.aborted) return;
      if (!result.pages.length) throw new Error("这一讲还没有可用的正文，请重试读取。");
      if (result.pages.some((page) => page.mock !== false)) throw new Error("原文接口返回的是模拟内容，请重新读取真实 PDF。");
      onOpenOriginal(result.pages, status.lecture_id);
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "打开原文失败，请重试。");
    } finally { if (!controller.signal.aborted) { active.current = false; setPhase("idle"); } }
  }

  const hasText = status?.parse_status === "parsed" || status?.parse_status === "ready";
  return (
    <>
      <input ref={input} type="file" accept="application/pdf,.pdf" aria-label="选择 PDF 文件" hidden onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void run(file); }} />
      {(showIdle || filename || error || status || busy) && <Card aria-label="资料读取" aria-busy={busy}>
      <header><h3>交课件，整理成学习笔记</h3><Badge>真实 PDF</Badge></header>
      <p className="aux">支持文字版 PDF，最多 20 MB。可以点「＋ 交资料」，也可以把文件拖进对话。扫描件暂不支持。</p>
      {filename && <p>{filename}</p>}
      <p aria-live="polite">{phase === "uploading" ? "正在上传并保存文件……" : phase === "opening" ? "正在打开……" : phase === "summarizing" && status?.summary_status !== "generating" ? "正在开始整理笔记……" : status ? statusText(status) : enabled ? "选择当前讲次后，交一份课件试试。" : "正在连接后端……"}</p>
      {status?.parse_status === "reading" && status.page_count > 0 && <progress value={status.processed_pages} max={status.page_count} aria-label="PDF 读取进度" />}
      {displayNote && status?.notes_ready && <div aria-label="笔记摘要"><Badge>{displayNote.label}</Badge><ul>{displayNote.content.summaries.map((item, index) => <li key={index}>{item.text}</li>)}</ul><p className="aux">{displayNote.content.knowledge_points.length} 个知识点 · {displayNote.content.terms.length} 个术语{displayNote.edited_by_user ? " · 已保留你的修改" : ""}</p></div>}
      {hasText && !status?.notes_ready && status?.summary_status !== "generating" && <p className="aux">逐页正文已经保存，整理暂未完成时也能查看原文。</p>}
      {error && <p role="alert">{error}</p>}
      <div className="btns">
        <Button disabled={busy || !enabled} onClick={chooseFile}>{filename ? "换一份 PDF" : "选择 PDF"}</Button>
        {status?.notes_ready && status.note_id && <Button variant="primary" disabled={busy} onClick={() => void openNote()}>打开学习笔记</Button>}
        {hasText && !status?.notes_ready && <Button variant="primary" disabled={busy} onClick={() => void summarize()}>{status?.summary_status === "failed" || status?.summary_status === "unavailable" ? "重试整理笔记" : "整理成笔记"}</Button>}
        {hasText && <Button disabled={busy} onClick={() => void openOriginal()}>查看逐页原文</Button>}
        {status?.parse_status === "failed" && status.can_retry && <Button disabled={busy} onClick={() => void run(null, true)}>重试读取</Button>}
        {error && lastFile.current && status?.parse_status !== "failed" && !hasText && <Button disabled={busy} onClick={() => void run(lastFile.current)}>重试上传</Button>}
      </div>
      </Card>}
    </>
  );
});
