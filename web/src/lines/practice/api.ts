// 练习接口失败直接提示；反馈和作答均真实保存在后端数据库。
export type FeedbackRecord = { question_id: string; active: boolean; category: string; category_label: string;
  reason: string; message: string; created_at?: string; updated_at?: string; storage: "server"; attempt_id?: string };
export type LearningState = { learning_state: "wrong" | "consolidate" | "normal" | "reported" | "unanswered";
  learning_label: string; priority: boolean; excluded: boolean; review_recommended: boolean; review_rank: number | null;
  review_passed: boolean; report?: FeedbackRecord | null };
export type Summary = { effective_count: number; correct_count: number; accuracy: number | null;
  wrong_count: number; consolidate_count: number; reported_count: number; unmarked_count: number; legacy_unknown_count: number };
export type Question = { id: string; stem: string; options: { id: string; text: string }[];
  difficulty: "easy" | "medium" | "hard"; source: { page?: number }; mock: boolean };
export type Result = LearningState & {
  attempt_id: string; question_id: string; your_answer: string; answer: string; correct: boolean;
  analysis: string; source: { page?: number; quote?: string }; mastery?: number | null;
  next_review_on?: string; quiz_completed?: boolean; confidence: string; confidence_label: string;
  confidence_status: string; feedback: string; action_feedback: string;
};
export type Progress = { question_id: string; answer: string; paused: boolean; seconds: number };
export type Quiz = { quiz_id: string; lecture_id: string; questions: Question[]; results?: Record<string, Result>;
  completed?: boolean; label: string; mock: boolean; notice?: string; reused?: boolean; progress?: Progress;
  summary?: Summary; reports?: Record<string, FeedbackRecord> };
export type Mistake = { question_id: string; lecture_id: string; stem: string; analysis: string; next_review_on: string; mock: boolean };
export type ReviewItem = Question & LearningState & Partial<Result> & { question_id: string; lecture_id: string;
  has_attempt: boolean; next_review_on: string; root_id: string; history_count: number;
  history: (Result & { stem: string; created_at: string })[] };
export type Stats = Summary & { title: string; scope: string; mock: boolean; label: string };
export type Material = { lecture_id: string; filename: string; page_count: number; character_count: number; reused?: boolean };
export type ModelStatus = { configured: boolean; model_chain: string[]; note: string };

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function request<T>(path: string, body?: unknown, method?: string): Promise<T> {
  try {
    const multipart = body instanceof FormData;
    const response = await fetch(path, {
      method: method || (body === undefined ? "GET" : "POST"), credentials: "include",
      headers: body === undefined || multipart ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : multipart ? body : JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new ApiError(data.detail?.message || "暂时没接上，请重试。已保存的作答不会丢。", response.status);
    return data.data as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError("暂时没接上，请检查后端后重试。", 0);
  }
}
