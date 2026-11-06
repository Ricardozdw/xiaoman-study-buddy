import type { PlanCard } from "../plan/types";
import type { Answer, Frame, Handoff, Reference } from "./types";
export function emptyAnswer(id: string): Answer {
  return { id, messageId: "", threadId: "", role: "assistant", text: "", references: [], status: "streaming", mock: false, label: "AI 整理，可以改" };
}
export function applyFrame(answer: Answer, frame: Frame): Answer {
  if (typeof frame.delta === "string") return { ...answer, text: answer.text + frame.delta };
  switch (frame.type) {
    case "meta": return { ...answer, messageId: String(frame.message_id || ""), threadId: String(frame.thread_id || ""), mock: frame.mock === true, intent: String(frame.intent || "qa"), label: String(frame.label || answer.label) };
    case "references": {
      const refs = Array.isArray(frame.references) ? frame.references.filter((r): r is Reference => Boolean(r && typeof r === "object" && typeof r.lecture_id === "string" && Number.isInteger(r.page) && r.page > 0 && typeof r.quote === "string" && r.quote.trim())) : [];
      return { ...answer, references: refs };
    }
    case "handoff": return frame.intent === "quiz" || frame.intent === "plan" ? { ...answer, handoff: { intent: frame.intent, data: frame.data as Handoff["data"] } } : answer;
    case "complete": return { ...answer, status: frame.ok === false ? "error" : "done", mock: frame.mock === true || answer.mock, error: frame.ok === false ? "回答未完成，请重试。" : answer.error };
    case "error": return { ...answer, status: "error", error: String(frame.message || "回答失败") };
    default: return answer;
  }
}

export function nextCurrentLectureId(current: string, frame: Frame): string {
  return frame.type === "meta" && (frame.intent === "qa" || frame.intent === "quiz") && typeof frame.lecture_id === "string" && frame.lecture_id.trim() ? frame.lecture_id : current;
}

export function advancePlanCard(current: PlanCard, result: PlanCard & { next_card?: PlanCard | null }) {
  const executed = { ...current, ...result };
  return { card: result.next_card || executed, previous: result.next_card && result.status === "executed" ? executed : null };
}

export function appendLocalNotice(messages: Answer[], text: string): Answer[] {
  return [...messages, { ...emptyAnswer(crypto.randomUUID()), text, status: "done", mock: true }];
}

export function restorePlanAfterUndo(parent: PlanCard): { card: PlanCard; previous: null } {
  return { card: parent, previous: null };
}
