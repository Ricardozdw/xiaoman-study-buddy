// V2 大纲接口。404 或连不上时，api() 会落到本地假数据；那种结果一律当成 V2 关闭或失败，不当真。
import { api } from "../../api/client";
import { isIsoDate, type DraftBody, type UnitInput } from "./logic";

export type { UnitInput };

export type OutlineUnit = { no?: number; title: string; points: string[] };
export type OutlineView = {
  id: string;
  title: string;
  status: string;
  units: OutlineUnit[];
  stages: { no: number; title: string; unit_nos: number[]; started_at?: string }[];
  label: string;
  mock: boolean;
  learned_up_to?: number;
};

type Fail = { ok: false; message: string };
type OutlineResult = { ok: true; outline: OutlineView } | Fail;

function asOutline(data: Partial<OutlineView> | undefined): OutlineView | null {
  if (!data || typeof data.id !== "string" || !Array.isArray(data.units) || typeof data.label !== "string") return null;
  return data as OutlineView;
}

/** 404 或连不上 = 关闭。只认真实接口里的 enabled: true。 */
export async function getStatus(): Promise<boolean> {
  const result = await api<{ enabled?: boolean }>("/api/v2/status");
  return result.source === "api" && result.envelope.ok !== false && result.envelope.data?.enabled === true;
}

export async function getPlanDate(): Promise<string | null> {
  const result = await api<{ date?: string }>("/api/plan/today");
  const date = result.envelope.data?.date;
  if (result.source !== "api" || typeof date !== "string" || !isIsoDate(date)) return null;
  return date;
}

/** 当前目标已确认的大纲；没有、没连上都返回 null。 */
export async function getCurrentOutline(): Promise<OutlineView | null> {
  const result = await api<{ outline?: OutlineView | null }>("/api/v2/outline/current");
  if (result.source !== "api" || result.envelope.ok === false) return null;
  return asOutline(result.envelope.data?.outline ?? undefined);
}

export async function draftOutline(body: DraftBody): Promise<OutlineResult> {
  const payload: DraftBody = { ...body };
  if (!payload.deadline) delete payload.deadline;
  const result = await api<OutlineView>("/api/v2/outline/draft", { method: "POST", body: JSON.stringify(payload) });
  const outline = result.source === "api" && result.envelope.ok !== false ? asOutline(result.envelope.data) : null;
  if (!outline) return { ok: false, message: "大纲没能生成，请检查连接后再试。" };
  return { ok: true, outline };
}

export async function patchOutline(id: string, units: UnitInput[]): Promise<OutlineResult> {
  const result = await api<OutlineView>(`/api/v2/outline/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ units }),
  });
  const outline = result.source === "api" && result.envelope.ok !== false ? asOutline(result.envelope.data) : null;
  if (!outline) return { ok: false, message: "没能保存修改，请检查单元后再试。" };
  return { ok: true, outline };
}

export async function acceptOutline(id: string): Promise<OutlineResult> {
  const result = await api<{ outline?: OutlineView }>(`/api/v2/outline/${encodeURIComponent(id)}/accept`, { method: "POST" });
  const outline = result.source === "api" && result.envelope.ok !== false ? asOutline(result.envelope.data?.outline) : null;
  if (!outline) return { ok: false, message: "还没能按这份大纲安排，请再试一次。" };
  return { ok: true, outline };
}

export async function undoOutline(id: string): Promise<{ ok: true } | Fail> {
  const result = await api<{ plan_today?: { needs_setup?: boolean } }>(`/api/v2/outline/${encodeURIComponent(id)}/undo`, { method: "POST" });
  if (result.source !== "api" || result.envelope.ok === false) return { ok: false, message: "今天没能撤销，可以稍后再试。" };
  return { ok: true };
}

export type DailyExamReport = { score: number; correct: number; total: number; summary: string };
export type ExamPaper =
  | ({ type: "stage" } & Quiz)
  | { type: "daily"; id: string; label: string; mock: boolean; lecture_no: number; mistake_count: number; submitted: boolean; report: DailyExamReport | null; questions: QuizQuestion[] };

/** 今天的考试：学完一个阶段那天返回阶段测验，其余是每日考试。 */
export async function startExam(): Promise<{ ok: true; paper: ExamPaper } | Fail> {
  const result = await request<ExamPaper>("/api/v2/exam/start", { method: "POST" });
  if (!result.ok) return result;
  const paper = result.data;
  if (!paper || typeof paper.id !== "string" || !Array.isArray(paper.questions) || !paper.questions.length) {
    return { ok: false, message: "题目还没准备好，请再试一次。" };
  }
  return { ok: true, paper };
}

export async function submitExam(id: string, answers: Record<string, string>): Promise<{ ok: true; report: DailyExamReport } | Fail> {
  const result = await request<DailyExamReport>(`/api/v2/exam/${encodeURIComponent(id)}/submit`, { method: "POST", body: JSON.stringify({ answers }) });
  if (!result.ok) return result;
  if (typeof result.data.score !== "number" || typeof result.data.total !== "number") return { ok: false, message: "成绩还没读到，请再试一次。" };
  return { ok: true, report: result.data };
}

/** 「学下一讲」学完后记进度，明天从再下一讲开始。 */
export async function advanceProgress(unitNo: number): Promise<{ ok: true; learnedUpTo: number } | Fail> {
  const result = await request<{ learned_up_to: number }>("/api/v2/progress", { method: "POST", body: JSON.stringify({ unit_no: unitNo }) });
  if (!result.ok) return result;
  return { ok: true, learnedUpTo: result.data.learned_up_to };
}

export type StageView = { no: number; title: string; unit_nos: number[] };
export type AssessmentDue = { due: boolean; stage: StageView | null; reason: "stage_done" | "seven_days" | null; open_id: string | null };
export type QuizQuestion = { id: string; stem: string; options: { id: string; text: string }[] };
export type Quiz = { id: string; stage: StageView; questions: QuizQuestion[]; label: string; mock: boolean };
export type AssessmentReport = {
  score: number;
  units: { no: number; title: string; correct: number; total: number }[];
  weak_unit_nos: number[];
  next_stage: StageView | null;
  summary: string;
};
export type CompletionCard = {
  days: number;
  attempts: number;
  first_score: number | null;
  last_score: number | null;
  hardest_unit: string | null;
  label: string;
};
export type CompletionStatus = { suggest: boolean; reason: "all_done" | null; card: CompletionCard | null; done: boolean };

async function request<T>(path: string, init?: RequestInit): Promise<{ ok: true; data: T } | Fail> {
  try {
    const response = await fetch(path, {
      ...init,
      credentials: "include",
      headers: {
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(init?.headers || {}),
      },
    });
    const body = await response.json().catch(() => null) as { ok?: boolean; data?: T; detail?: unknown } | null;
    if (!response.ok || !body || body.ok === false || body.data === undefined) {
      const detail = body?.detail;
      const message = typeof detail === "string" ? detail : detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string" ? detail.message : "这次没完成，请再试一次。";
      return { ok: false, message };
    }
    return { ok: true, data: body.data };
  } catch {
    return { ok: false, message: "没有连上，请检查后再试。" };
  }
}

export async function getAssessmentDue(): Promise<AssessmentDue | null> {
  const result = await request<AssessmentDue>("/api/v2/assessment/due");
  if (!result.ok || typeof result.data.due !== "boolean") return null;
  return result.data;
}

export async function startAssessment(): Promise<{ ok: true; quiz: Quiz } | Fail> {
  const result = await request<Quiz>("/api/v2/assessment/start", { method: "POST" });
  if (!result.ok) return result;
  const quiz = result.data;
  if (!quiz || typeof quiz.id !== "string" || !Array.isArray(quiz.questions) || quiz.questions.length === 0) {
    return { ok: false, message: "题目还没准备好，请再试一次。" };
  }
  return { ok: true, quiz };
}

export async function submitAssessment(id: string, answers: Record<string, string>): Promise<{ ok: true; report: AssessmentReport } | Fail> {
  const result = await request<AssessmentReport>(`/api/v2/assessment/${encodeURIComponent(id)}/submit`, {
    method: "POST",
    body: JSON.stringify({ answers }),
  });
  if (!result.ok) return result;
  if (typeof result.data.score !== "number" || !Array.isArray(result.data.units) || typeof result.data.summary !== "string") {
    return { ok: false, message: "成绩还没读到，请再试一次。" };
  }
  return { ok: true, report: result.data };
}

export async function getCompletion(): Promise<CompletionStatus | null> {
  const result = await request<CompletionStatus>("/api/v2/completion");
  if (!result.ok || typeof result.data.done !== "boolean" || typeof result.data.suggest !== "boolean") return null;
  return result.data;
}

export async function confirmCompletion(reason: "suggested" | "user_said"): Promise<{ ok: true; card: CompletionCard } | Fail> {
  const result = await request<CompletionCard>("/api/v2/completion/confirm", { method: "POST", body: JSON.stringify({ reason }) });
  if (!result.ok) return result;
  if (typeof result.data.days !== "number" || typeof result.data.attempts !== "number") {
    return { ok: false, message: "完成记录还没读到，请再试一次。" };
  }
  return { ok: true, card: result.data };
}

export async function undoCompletion(): Promise<{ ok: true } | Fail> {
  const result = await request<{ done?: boolean }>("/api/v2/completion/undo", { method: "POST" });
  if (!result.ok) return result;
  return { ok: true };
}
