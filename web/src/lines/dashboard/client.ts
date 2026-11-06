import type { Dashboard } from "../../api/types";

export type Board = Omit<Dashboard, "lectures"> & {
  mock?: boolean;
  generated_at?: string;
  period?: { start: string; end: string; timezone: string };
  mastery_note?: string;
  goal?: { title: string; completed_lectures: number; total_lectures: number; status?: string };
  lectures: (Dashboard["lectures"][number] & { assessed?: boolean; mistakes_due?: number })[];
};

const record = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const count = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0;
const numberIn = (value: unknown, max: number): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= max;

function validBoard(value: unknown): value is Board {
  if (!record(value) || value.range !== "week" || !count(value.studied_days) || value.studied_days > 7
    || !count(value.attempt_count) || !count(value.mistakes_due) || !numberIn(value.goal_progress, 1)
    || !count(value.llm_calls) || typeof value.label !== "string" || typeof value.note !== "string"
    || !Array.isArray(value.files) || !Array.isArray(value.lectures)) return false;
  const ids = new Set<string>();
  for (const lecture of value.lectures) {
    if (!record(lecture) || typeof lecture.id !== "string" || !lecture.id || ids.has(lecture.id)
      || typeof lecture.title !== "string" || !numberIn(lecture.mastery, 100)
      || (lecture.assessed !== undefined && typeof lecture.assessed !== "boolean")
      || (lecture.mistakes_due !== undefined && !count(lecture.mistakes_due))) return false;
    ids.add(lecture.id);
  }
  if (value.goal !== undefined && (!record(value.goal) || typeof value.goal.title !== "string"
    || !count(value.goal.completed_lectures) || !count(value.goal.total_lectures)
    || value.goal.completed_lectures > value.goal.total_lectures)) return false;
  if (!value.files.every((file) => record(file) && typeof file.id === "string" && typeof file.filename === "string" && typeof file.parse_status === "string")) return false;
  if (value.period !== undefined && (!record(value.period) || value.period.timezone !== "Asia/Shanghai"
    || typeof value.period.start !== "string" || typeof value.period.end !== "string"
    || !/^\d{4}-\d{2}-\d{2}$/.test(value.period.start) || !/^\d{4}-\d{2}-\d{2}$/.test(value.period.end)
    || !Number.isFinite(Date.parse(value.period.start)) || !Number.isFinite(Date.parse(value.period.end))
    || value.period.start > value.period.end)) return false;
  if (value.generated_at !== undefined && (typeof value.generated_at !== "string" || !Number.isFinite(Date.parse(value.generated_at)))) return false;
  return true;
}

// Failures remain visible; a hung connection also has a bounded retry path.
export async function fetchBoard(signal?: AbortSignal): Promise<Board> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  let timedOut = false;
  if (signal?.aborted) cancel();
  else signal?.addEventListener("abort", cancel, { once: true });
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, 10_000);
  try {
    const response = await fetch("/api/dashboard?range=week", { credentials: "include", signal: controller.signal });
    if (!response.ok) throw new Error(response.status === 401 ? "会话已失效，请刷新页面后重试。" : "看板暂时没接上，请重试。");
    const result: unknown = await response.json();
    if (!record(result) || result.ok !== true || typeof result.mock !== "boolean" || !validBoard(result.data)) throw new Error("看板数据暂时不可用，请重试。");
    return { ...result.data, mock: result.mock };
  } catch (error) {
    if (signal?.aborted) throw new DOMException("读取已取消", "AbortError");
    if (timedOut) throw new Error("读取看板超时，请重试。");
    if (error instanceof TypeError || error instanceof SyntaxError) throw new Error("看板暂时无法读取，请检查网络后重试。");
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}

export function masteryChanges(previous: Board | null, current: Board): Record<string, string> {
  const before = new Map(previous?.lectures.map((lecture) => [lecture.id, lecture]));
  return Object.fromEntries(current.lectures.flatMap((lecture) => {
    const old = before.get(lecture.id);
    return old && old.assessed !== false && lecture.assessed !== false && old.mastery !== lecture.mastery
      ? [[lecture.id, `上次查看 ${old.mastery}% → 当前 ${lecture.mastery}%`]] : [];
  }));
}

export function isDashboardRequest(text: string): boolean {
  return /^(?:请|帮我)?(?:看(?:看|一下)?(?:我的)?(?:学习)?(?:看板|进度)|(?:我)?(?:这|本)周(?:的)?(?:学(?:习|得)?(?:怎么样|如何|情况|进度|了什么)|学习总结))[？?！!。\s]*$/.test(text.trim());
}

export function boardSummary(board: Board): string {
  return `这周学了 ${board.studied_days} 天，做了 ${board.attempt_count} 道题，待重做 ${board.mistakes_due} 道。`;
}
