import type { Board } from "./client";

export type DashboardTurn = { id: string; after: number; question: string; board?: Board; error?: string };

// QA 的消息只追加、不删除；用当时的位置把本地看板插回同一条对话，后续回答不会排到看板前面。
export function mergeDashboardTurns<T>(answers: T[], dashboard: DashboardTurn[]) {
  const groups = new Map<number, DashboardTurn[]>();
  for (const turn of dashboard) {
    const position = Math.min(turn.after, answers.length);
    groups.set(position, [...(groups.get(position) || []), turn]);
  }
  const result: ({ kind: "qa"; answer: T } | { kind: "dashboard"; turn: DashboardTurn })[] = [];
  for (let position = 0; position <= answers.length; position++) {
    for (const turn of groups.get(position) || []) result.push({ kind: "dashboard", turn });
    if (position < answers.length) result.push({ kind: "qa", answer: answers[position] });
  }
  return result;
}
