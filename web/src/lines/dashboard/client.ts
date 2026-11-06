import type { Dashboard, Envelope } from "../../api/types";

export type Board = Omit<Dashboard, "lectures"> & {
  mock?: boolean;
  period?: { start: string; end: string; timezone: string };
  mastery_note?: string;
  goal?: { title: string; completed_lectures: number; total_lectures: number };
  lectures: (Dashboard["lectures"][number] & { assessed?: boolean; mistakes_due?: number })[];
};

// Error states stay visible: no local fake statistics on network or auth failures.
export async function fetchBoard(signal?: AbortSignal): Promise<Board> {
  const response = await fetch("/api/dashboard?range=week", { credentials: "include", signal });
  if (!response.ok) throw new Error(response.status === 401 ? "会话已失效，请刷新页面后重试。" : "看板暂时没接上，请重试。");
  const result = await response.json() as Envelope<Board>;
  if (!result.ok || !Array.isArray(result.data?.lectures)) throw new Error("看板数据暂时不可用。");
  return { ...result.data, mock: result.mock };
}

export function isDashboardRequest(text: string): boolean {
  return /^(?:请|帮我)?(?:看(?:看|一下)?(?:我的)?(?:学习)?(?:看板|进度)|(?:我)?(?:这|本)周(?:的)?(?:学(?:习|得)?(?:怎么样|如何|情况|进度|了什么)|学习总结))[？?！!。\s]*$/.test(text.trim());
}

export function boardSummary(board: Board): string {
  return `这周学了 ${board.studied_days} 天，做了 ${board.attempt_count} 道题，待重做 ${board.mistakes_due} 道。`;
}
