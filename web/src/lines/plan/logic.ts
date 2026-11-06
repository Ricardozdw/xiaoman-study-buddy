import type { GoalQuestion, PlanCard, PlanOption } from "./types";

// 目标问答：一次一题。answers 里没有的 key = 用户跳过。
export type Answers = Record<string, string>;

export function nextQuestion(questions: GoalQuestion[], index: number): GoalQuestion | null {
  return index >= 0 && index < questions.length ? questions[index] : null;
}

export function answer(answers: Answers, key: string, value: string | null): Answers {
  const next = { ...answers };
  const text = (value ?? "").trim();
  if (text) next[key] = text;
  else delete next[key]; // 跳过：不填，后端按“先按……安排”处理
  return next;
}

// 卡片上的主按钮：只有一个选项时它就是主按钮；多个选项时都是普通按钮，让用户自己挑。
export function isPrimary(card: PlanCard, option: PlanOption): boolean {
  return card.options.length === 1 && card.options[0].id === option.id;
}

export function cardLabel(card: PlanCard): string {
  if (card.type === "goal") return "目标拆解";
  if (card.type === "reschedule") return "重排";
  if (card.type === "done") return "收工";
  return "建议";
}

// 这些操作会改到左栏（Shell 管），做完要刷新页面才能看到新的三件。
export function changesLeftColumn(action: "accept" | "undo" | "dismiss" | "draft" | "revise" | "adjust"): boolean {
  return action === "accept" || action === "undo";
}
