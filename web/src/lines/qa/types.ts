import type { PlanCard } from "../plan/types";
export type Reference = { lecture_id: string; page: number; quote: string };
export type Lecture = { id: string; title: string; mock: boolean };
export type Frame = Record<string, unknown>;
export type Question = { id: string; kind: string; stem: string; options: (string | { id?: string; key?: string; label?: string; text?: string })[] };
export type Handoff = { intent: "quiz" | "plan"; data: { card?: PlanCard | null; understood?: boolean; reply?: string; id?: string; status?: string; label?: string; questions?: Question[]; suggestion?: { title?: string; body?: string; label?: string } } };
export type Answer = {
  id: string; messageId: string; threadId: string; role: "user" | "assistant";
  text: string; references: Reference[]; status: "streaming" | "done" | "error";
  mock: boolean; label: string; intent?: string; error?: string; handoff?: Handoff;
};
