// 测验、报告、完成卡的纯逻辑。一次只决定出哪一张；文案不评判人。
import { isIsoDate } from "./logic";

export const GENERIC_QUESTION_BADGE = "通用题，没有出处";
export const ASSESSMENT_INVITE = "考考这一阶段？大约 15 分钟";
export const COMPLETION_SUGGEST = "看起来可以收尾了";
export const NEXT_GOAL_HINT = "V2.0 先支持一个目标，下一个目标在 V2.3 做";
export const GOAL_DONE_RAIL = "这个目标已完成 🎉";
export const ASSESSMENT_LATER_KEY = "xiaoman.v2.assessmentLater";

export const FORBIDDEN_WORDS = ["不及格", "不合格", "没及格", "很差", "太差", "差劲", "糟糕", "失败", "差评", "你断了"];

export type ReportUnit = { no: number; title: string; correct: number; total: number };
export type Report = {
  score: number;
  units: ReportUnit[];
  weak_unit_nos: number[];
  summary: string;
};

export type CompletionStats = {
  days: number;
  attempts: number;
  first_score: number | null;
  last_score: number | null;
  hardest_unit: string | null;
};

export type InitialView = "done" | "suggest" | "invite" | "idle";

export function forbiddenHit(text: string): string | null {
  return FORBIDDEN_WORDS.find((word) => text.includes(word)) ?? null;
}

export function stepIndex(index: number, total: number, direction: -1 | 1): number {
  if (total <= 0) return 0;
  return Math.min(total - 1, Math.max(0, index + direction));
}

export function unansweredCount(ids: string[], answers: Record<string, string>): number {
  return ids.filter((id) => !answers[id]).length;
}

export function submitGuard(ids: string[], answers: Record<string, string>): { ok: true } | { ok: false; canForce: boolean; message: string } {
  const missing = unansweredCount(ids, answers);
  if (ids.length > 0 && missing === ids.length) return { ok: false, canForce: false, message: "先回答至少一道题，就可以交卷。" };
  if (missing > 0) return { ok: false, canForce: true, message: `还有 ${missing} 题没选。没答的不算错，可以回去补，也可以现在交卷。` };
  return { ok: true };
}

export function unitScoreLine(unit: { correct: number; total: number }): string {
  return `对 ${unit.correct} / ${unit.total}`;
}

export function weakLine(nos: number[]): string | null {
  if (!nos.length) return null;
  return `第 ${nos.join("、")} 单元再看一眼会更稳`;
}

export function reportLines(report: Report): string[] {
  const weak = weakLine(report.weak_unit_nos);
  return [
    `${report.score} 分`,
    ...report.units.map((unit) => `${unit.title}：${unitScoreLine(unit)}`),
    ...(weak ? [weak] : []),
    report.summary,
  ];
}

export function scoreSpan(card: CompletionStats): string {
  const { first_score: first, last_score: last } = card;
  if (first != null && last != null) return `阶段测验从 ${first} 分到 ${last} 分`;
  if (last != null) return `阶段测验 ${last} 分`;
  if (first != null) return `阶段测验 ${first} 分`;
  return "还没有阶段测验分数";
}

export function completionLines(card: CompletionStats): string[] {
  const lines = [`学了 ${card.days} 天`, `做了 ${card.attempts} 题`, scoreSpan(card)];
  if (card.hardest_unit) lines.push(`最难的单元：${card.hardest_unit}`);
  return lines;
}

export function isSnoozed(laterDay: string | null, today: string): boolean {
  return Boolean(laterDay && today && laterDay === today);
}

export function readLaterDay(): string | null {
  try {
    const value = localStorage.getItem(ASSESSMENT_LATER_KEY);
    return value && isIsoDate(value) ? value : null;
  } catch {
    return null;
  }
}

export function rememberLater(day: string) {
  try {
    localStorage.setItem(ASSESSMENT_LATER_KEY, day);
  } catch {
    // 记不住时这次先收起；刷新后当天可能再出现。
  }
}

/** 打开页面时只出一张：完成建议优先于测验邀请。报告是刚交卷的结果，不在这里抢。 */
export function pickInitialView(input: { done: boolean; suggest: boolean; due: boolean; laterDay: string | null; today: string }): InitialView {
  if (input.done) return "done";
  if (input.suggest) return "suggest";
  if (input.due && !isSnoozed(input.laterDay, input.today)) return "invite";
  return "idle";
}

export function viewAfterReport(input: { done: boolean; suggest: boolean }): "done" | "suggest" | "idle" {
  if (input.done) return "done";
  if (input.suggest) return "suggest";
  return "idle";
}
