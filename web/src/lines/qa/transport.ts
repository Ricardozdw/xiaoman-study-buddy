import type { PlanCard } from "../plan/types";
import type { PlanToday } from "../../api/types";
import type { Frame, Reference } from "./types";

type Envelope<T> = { ok: boolean; mock: boolean; data: T };
export async function requestJson<T>(path: string, init: RequestInit = {}): Promise<Envelope<T>> {
  const response = await fetch(path, { ...init, credentials: "include", headers: { ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers } });
  if (!response.ok) throw new Error(`请求失败（${response.status}），请重试。`);
  const result = await response.json() as Envelope<T>;
  if (!result.ok) throw new Error("操作未成功，请重试。");
  return result;
}

/** Parse real UTF-8 byte boundaries and SSE lines; EOF never implies successful completion. */
export async function consumeSse(response: Response, onFrame: (frame: Frame) => void, signal?: AbortSignal): Promise<void> {
  if (!response.ok || !response.body) throw new Error(`对话连接失败（${response.status}）。`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "", data: string[] = [], done = false, messageId = "", completed = false;
  const abort = () => { void reader.cancel().catch(() => {}); };
  signal?.addEventListener("abort", abort, { once: true });
  function checkAbort() { if (signal?.aborted) throw new DOMException("已停止生成", "AbortError"); }
  function dispatch() {
    if (!data.length) return;
    const raw = data.join("\n"); data = [];
    if (raw.trim() === "[DONE]") {
      if (!completed) throw new Error("缺少回答完成确认，请重试。");
      done = true; return;
    }
    let frame: Frame;
    try { frame = JSON.parse(raw) as Frame; } catch { throw new Error("回答数据格式错误，请重试。"); }
    if (!frame || typeof frame !== "object" || Array.isArray(frame)) throw new Error("回答数据格式错误。");
    if (frame.type === "meta") messageId = typeof frame.message_id === "string" ? frame.message_id.trim() : "";
    if (frame.type === "complete") {
      if (frame.ok !== true || !messageId || frame.message_id !== messageId) throw new Error("回答完成信息无效，请重试。");
      completed = true;
    }
    onFrame(frame);
    if (frame.type === "error") throw new Error(typeof frame.message === "string" ? frame.message : "回答生成失败。");
    if (frame.type === "complete" && frame.ok === false) throw new Error("回答未完成，请重试。");
  }
  function processLines() {
    let end: number;
    while (!done && (end = buffer.indexOf("\n")) >= 0) {
      let line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
      if (line.endsWith("\r")) line = line.slice(0, -1);
      if (!line) dispatch();
      else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
  }
  try {
    while (!done) {
      checkAbort();
      const step = await reader.read(); checkAbort();
      if (step.done) { buffer += decoder.decode(); processLines(); break; }
      buffer += decoder.decode(step.value, { stream: true });
      processLines();
    }
    if (!done) throw new Error("连接中断，回答尚未完成，请重试。");
  } finally {
    signal?.removeEventListener("abort", abort);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export async function loadSource(reference: Reference, signal?: AbortSignal): Promise<{ text: string; mock: boolean }> {
  const response = await requestJson<{ pages: { page: number; text: string; mock?: boolean; sample?: boolean }[] }>(`/api/lectures/${encodeURIComponent(reference.lecture_id)}/pages`, { signal });
  const page = response.data.pages.find(item => item.page === reference.page);
  if (!page) throw new Error("没有找到这一页原文。");
  if (!page.text.includes(reference.quote)) throw new Error("当前原文与引用不一致，请重新提问。");
  return { text: page.text, mock: page.mock === true || page.sample === true };
}

/** All mounted QA consumers share one non-abortable session request.
 * Aborting a StrictMode mount must never trigger a second user-creating POST. */
export function createSessionInitializer(request: typeof fetch = (...args) => fetch(...args)): () => Promise<void> {
  let initialization: Promise<void> | null = null;
  return () => {
    if (!initialization) initialization = request("/api/session", { method: "POST", credentials: "include" })
      .then(response => { if (!response.ok) throw new Error("会话连接失败"); })
      .catch(error => { initialization = null; throw error; });
    return initialization;
  };
}
export const ensureQaSession = createSessionInitializer();

export function submitPlanDecision(id: string, kind: "accept" | "dismiss" | "undo", option?: string, examDate?: string) {
  const encoded = encodeURIComponent(id);
  return requestJson<PlanCard & { plan?: PlanToday; next_card?: PlanCard }>(kind === "undo" ? `/api/actions/${encoded}/undo` : `/api/suggestions/${encoded}/${kind}`, { method: "POST", ...(kind === "accept" ? { body: JSON.stringify({ option, ...(examDate ? { exam_date: examDate } : {}) }) } : {}) });
}
