import { useEffect, useRef, useState } from "react";
import { applyFrame, emptyAnswer, nextCurrentLectureId, appendLocalNotice } from "./state";
import { consumeSse, requestJson, ensureQaSession } from "./transport";
import type { Answer, Lecture } from "./types";

export function useQaConversation(options: { initialThreadId?: string } = {}) {
  const [messages, setMessages] = useState<Answer[]>([]);
  const [busy, setBusy] = useState(false);
  const [sessionReady, setSessionReady] = useState(false);
  const [lectures, setLectures] = useState<Lecture[]>([]);
  const [currentLectureId, setCurrentLectureId] = useState("");
  // Empty means implicit current lecture; defaults are never treated as explicit @ choice.
  const [lectureId, setLectureId] = useState("");
  const [lectureError, setLectureError] = useState("");
  const threadId = useRef(options.initialThreadId || "");
  const active = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    ensureQaSession()
      .then(() => { if (!controller.signal.aborted) setSessionReady(true); return requestJson<{ items: Lecture[]; current_lecture_id: string }>("/api/qa/lectures", { signal: controller.signal }); })
      .then(({ data }) => { setLectures(data.items); setCurrentLectureId(current => current || data.current_lecture_id); })
      .catch(error => { if (error.name !== "AbortError") setLectureError("资料列表未能读取，请检查连接后刷新。"); });
    return () => { controller.abort(); active.current?.abort(); };
  }, []);
  async function send(message: string, selectedLectureId?: string) {
    const text = message.trim();
    if (!text || active.current) return;
    if (!sessionReady) throw new Error("会话尚未就绪，请稍后再发。");
    if (text.length > 4000) throw new Error("一次最多发送 4000 字。");
    const id = crypto.randomUUID(), controller = new AbortController();
    active.current = controller; setBusy(true);
    setMessages(list => [...list, { ...emptyAnswer(crypto.randomUUID()), role: "user", text, status: "done" }, emptyAnswer(id)]);
    const update = (fn: (answer: Answer) => Answer) => setMessages(list => list.map(item => item.id === id ? fn(item) : item));
    try {
      const response = await fetch("/api/chat/stream", { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text, lecture_id: selectedLectureId ?? lectureId, thread_id: threadId.current }), signal: controller.signal });
      await consumeSse(response, frame => {
        if (frame.type === "meta" && typeof frame.thread_id === "string") threadId.current = frame.thread_id;
        setCurrentLectureId(current => nextCurrentLectureId(current, frame));
        update(answer => applyFrame(answer, frame));
      }, controller.signal);

    } catch (error) {
      const stopped = error instanceof Error && error.name === "AbortError";
      update(answer => ({ ...answer, status: "error", error: stopped ? "已停止生成，这条回答未完成。" : error instanceof Error ? error.message : "连接失败，请重试。" }));
    } finally { active.current = null; setBusy(false); }
  }
  return { messages, busy, sessionReady, addNotice: (text: string) => setMessages(list => appendLocalNotice(list, text)), send, stop: () => active.current?.abort(), lectures, lectureId, setLectureId, currentLectureId, lectureError, threadId };
}
