// 定目标五问与大纲编辑的纯逻辑。跳过不算用户的选择（规则 6），默认值只在确认时写明。

export type GoalType = "exam" | "course" | "skill";
export type MaterialsChoice = "now" | "later" | "none";
export type GoalStep = "goal" | "goalName" | "deadline" | "minutes" | "materials" | "progress" | "confirm";

export const V2_OPENING = "我是小满。先说说你想学成什么样，我帮你拆成每天的小任务。";

export type GoalState = {
  step: GoalStep;
  goalChosen: boolean;
  goalType?: GoalType;
  title?: string;
  /** 点了快捷回复、还没填具体名称时，跳过就用这句当目标名。 */
  quickTitle?: string;
  deadlineChosen: boolean;
  /** 用户选了具体日期或快捷换算后的日期。不急、跳过都不放这里。 */
  deadline?: string;
  deadlineText?: string;
  minutesChosen: boolean;
  dailyMinutes?: number;
  materialsChosen: boolean;
  materials?: MaterialsChoice;
  progressChosen: boolean;
  progress?: string;
};

export type AnswerInput =
  | { type: "quick"; label: string }
  | { type: "text"; text: string }
  | { type: "date"; date: string }
  | { type: "skip" };

export type DraftBody = {
  goal_type: GoalType;
  title: string;
  daily_minutes: number;
  progress: string;
  materials: MaterialsChoice;
  deadline?: string;
};

export type UnitInput = { title: string; points: string[] };

export const MATERIALS_NOW_NOTICE = "V2 先支持没资料这条路，资料可以之后再交";
export const CONFIRM_SENTENCE = "这些是先按默认排的";
export const ACCEPT_STORAGE_KEY = "xiaoman.v2.acceptedOutline";
export const ACCEPTED_TEXT = "已按这份大纲排好今天的三件";

export const DEFAULT_TITLE = "把这门课学完";
export const DEFAULT_MINUTES = 30;

export const DEFAULT_NOTES = {
  goal: "想学成什么样先按“把这门课学完”排",
  deadline: "完成时间先按不设日期排",
  minutes: "每天时间先按 30 分钟排",
  materials: "资料先按还没有排",
  progress: "学到哪了先按刚开始排",
};

const GOAL_OPTIONS: { label: string; goalType: GoalType; title: string }[] = [
  { label: "考过一个证书", goalType: "exam", title: "考过一个证书" },
  { label: "学完一门课或一本书", goalType: "course", title: "学完一门课或一本书" },
  { label: "掌握一项技能", goalType: "skill", title: "掌握一项技能" },
];

export function goalNamePrompt(goalType: GoalType | undefined): string {
  if (goalType === "exam") return "是哪个证书？";
  if (goalType === "skill") return "是哪项技能？";
  return "是哪门课或哪本书？";
}

export const QUESTIONS: Record<Exclude<GoalStep, "confirm" | "goalName">, { text: string; quick: string[] }> = {
  goal: { text: "想学成什么样？", quick: GOAL_OPTIONS.map((item) => item.label) },
  deadline: { text: "什么时候想完成？", quick: ["一个月内", "三个月内", "不急"] },
  minutes: { text: "每天大概有多少时间？", quick: ["15 分钟", "30 分钟", "50 分钟"] },
  materials: { text: "手上有课件、教材或考纲吗？", quick: ["有，现在交", "有，晚点交", "没有"] },
  progress: { text: "学到哪了？", quick: ["刚开始", "学了一部分", "快学完了"] },
};

export function initialGoalState(): GoalState {
  return {
    step: "goal",
    goalChosen: false,
    deadlineChosen: false,
    minutesChosen: false,
    materialsChosen: false,
    progressChosen: false,
  };
}

export function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

/** 按日历加天数，不用本机时区，避免“今天 + 90 天”差一天。 */
export function addDays(iso: string, days: number): string {
  const [year, month, day] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() + days);
  const monthText = String(date.getUTCMonth() + 1).padStart(2, "0");
  const dayText = String(date.getUTCDate()).padStart(2, "0");
  return `${date.getUTCFullYear()}-${monthText}-${dayText}`;
}

export function asksProgress(state: GoalState): boolean {
  return (state.goalType ?? "course") !== "skill";
}

export function stepProgress(state: GoalState): { current: number; total: number } {
  const steps: GoalStep[] = ["goal", "deadline", "minutes", "materials"];
  if (asksProgress(state)) steps.push("progress");
  if (state.step === "confirm") return { current: steps.length, total: steps.length };
  // 追问具体名称仍算第 1 题，不另加一题。
  if (state.step === "goalName") return { current: 1, total: steps.length };
  return { current: steps.indexOf(state.step) + 1, total: steps.length };
}

function fail(state: GoalState, error: string) {
  return { state, error };
}

function goalFromText(text: string): { goalType: GoalType; title: string } | null {
  const exact = GOAL_OPTIONS.find((item) => item.label === text);
  if (exact) return { goalType: exact.goalType, title: exact.title };
  if (/证书|考证|考试|考过|考\s*[A-Za-z0-9]/.test(text)) return { goalType: "exam", title: text };
  if (/技能|学会|掌握/.test(text)) return { goalType: "skill", title: text };
  if (/课|书|学完/.test(text)) return { goalType: "course", title: text };
  return null;
}

function parseMinutes(text: string): { ok: true; value: number } | { ok: false; reason: "format" | "range" } {
  const matched = text.trim().match(/^(\d{1,3})(?:\s*分钟)?$/);
  if (!matched) return { ok: false, reason: "format" };
  const value = Number(matched[1]);
  if (value < 5 || value > 600) return { ok: false, reason: "range" };
  return { ok: true, value };
}

function parseMaterials(text: string): MaterialsChoice | null {
  if (text === "没有" || text === "无" || text === "没") return "none";
  if (text === "有，现在交" || text === "现在交" || text === "现在") return "now";
  if (text === "有，晚点交" || text === "晚点交" || text === "晚点" || text === "以后交") return "later";
  return null;
}

function go(state: GoalState, step: GoalStep): GoalState {
  return { ...state, step };
}

export function applyAnswer(state: GoalState, input: AnswerInput, today: string): { state: GoalState; error?: string; notice?: string } {
  if (state.step === "confirm") return fail(state, "已经到确认了。");
  if (state.step === "goal") return applyGoal(state, input);
  if (state.step === "goalName") return applyGoalName(state, input);
  if (state.step === "deadline") return applyDeadline(state, input, today);
  if (state.step === "minutes") return applyMinutes(state, input);
  if (state.step === "materials") return applyMaterials(state, input);
  return applyProgress(state, input);
}

function applyGoal(state: GoalState, input: AnswerInput): { state: GoalState; error?: string } {
  if (input.type === "skip") return { state: go({ ...state, goalChosen: false, goalType: undefined, title: undefined, quickTitle: undefined }, "deadline") };
  if (input.type === "quick") {
    const option = GOAL_OPTIONS.find((item) => item.label === input.label);
    if (!option) return fail(state, "可以点上面一个，或自己说一个目标。");
    return { state: go({ ...state, goalChosen: false, goalType: option.goalType, title: undefined, quickTitle: option.title }, "goalName") };
  }
  const text = input.type === "text" ? input.text.trim() : "";
  if (!text) return fail(state, "可以说一个目标，或先跳过。");
  if (text.length > 200) return fail(state, "目标名称太长了，请控制在 200 字以内。");
  const parsed = goalFromText(text);
  if (!parsed) return fail(state, "我还分不清是考证、课程还是技能。可以点上面一个，或先跳过。");
  return { state: go({ ...state, goalChosen: true, goalType: parsed.goalType, title: parsed.title, quickTitle: undefined }, "deadline") };
}

function applyGoalName(state: GoalState, input: AnswerInput): { state: GoalState; error?: string } {
  const fallback = state.quickTitle;
  if (!state.goalType || !fallback) return fail(state, "先选一个目标类型。");
  if (input.type === "skip") return { state: go({ ...state, goalChosen: true, title: fallback, quickTitle: undefined }, "deadline") };
  const text = input.type === "text" ? input.text.trim() : "";
  if (!text) return fail(state, "可以说具体名称，或先跳过。");
  if (text.length > 200) return fail(state, "目标名称太长了，请控制在 200 字以内。");
  return { state: go({ ...state, goalChosen: true, title: text, quickTitle: undefined }, "deadline") };
}

function applyDeadline(state: GoalState, input: AnswerInput, today: string): { state: GoalState; error?: string } {
  if (input.type === "skip") {
    return { state: go({ ...state, deadlineChosen: false, deadline: undefined, deadlineText: undefined }, "minutes") };
  }
  const label = input.type === "quick" ? input.label : input.type === "text" ? input.text.trim() : "";
  if (label === "不急") {
    return { state: go({ ...state, deadlineChosen: true, deadline: undefined, deadlineText: "不急" }, "minutes") };
  }
  if (label === "一个月内" || label === "三个月内") {
    if (!isIsoDate(today)) return fail(state, "还没读到今天的日期，请稍后再选。");
    const deadline = addDays(today, label === "一个月内" ? 30 : 90);
    return { state: go({ ...state, deadlineChosen: true, deadline, deadlineText: `${label}（${deadline}）` }, "minutes") };
  }
  const date = input.type === "date" ? input.date.trim() : label;
  if (!isIsoDate(date)) return fail(state, "可以选一个月内、三个月内、不急，或选一个具体日期。");
  return { state: go({ ...state, deadlineChosen: true, deadline: date, deadlineText: date }, "minutes") };
}

function applyMinutes(state: GoalState, input: AnswerInput): { state: GoalState; error?: string } {
  if (input.type === "skip") return { state: go({ ...state, minutesChosen: false, dailyMinutes: undefined }, "materials") };
  const text = input.type === "quick" ? input.label : input.type === "text" ? input.text.trim() : "";
  const parsed = parseMinutes(text);
  if (!parsed.ok) {
    return fail(state, parsed.reason === "range" ? "每天时间请填 5 到 600 分钟。" : "没看懂分钟数，可以选上面的，或填一个数字。");
  }
  return { state: go({ ...state, minutesChosen: true, dailyMinutes: parsed.value }, "materials") };
}

function applyMaterials(state: GoalState, input: AnswerInput): { state: GoalState; error?: string; notice?: string } {
  if (input.type === "skip") {
    const next = { ...state, materialsChosen: false, materials: undefined as MaterialsChoice | undefined };
    return { state: go(next, asksProgress(next) ? "progress" : "confirm") };
  }
  const text = input.type === "quick" ? input.label : input.type === "text" ? input.text.trim() : "";
  const materials = parseMaterials(text);
  if (!materials) return fail(state, "可以选上面的，或说说有没有资料。");
  const next = { ...state, materialsChosen: true, materials };
  return {
    state: go(next, asksProgress(next) ? "progress" : "confirm"),
    notice: materials === "now" ? MATERIALS_NOW_NOTICE : undefined,
  };
}

function applyProgress(state: GoalState, input: AnswerInput): { state: GoalState; error?: string } {
  if (input.type === "skip") return { state: go({ ...state, progressChosen: false, progress: undefined }, "confirm") };
  const text = input.type === "quick" ? input.label : input.type === "text" ? input.text.trim() : "";
  if (!text) return fail(state, "可以说说学到哪了，或先跳过。");
  if (text.length > 1000) return fail(state, "这句话太长了，请控制在 1000 字以内。");
  return { state: go({ ...state, progressChosen: true, progress: text }, "confirm") };
}

export function defaultNotes(state: GoalState): string[] {
  const notes: string[] = [];
  if (!state.goalChosen) notes.push(DEFAULT_NOTES.goal);
  if (!state.deadlineChosen) notes.push(DEFAULT_NOTES.deadline);
  if (!state.minutesChosen) notes.push(DEFAULT_NOTES.minutes);
  if (!state.materialsChosen) notes.push(DEFAULT_NOTES.materials);
  if (state.step === "confirm" && asksProgress(state) && !state.progressChosen) notes.push(DEFAULT_NOTES.progress);
  return notes;
}

export function summaryLines(state: GoalState): { label: string; value: string }[] {
  const goalType = state.goalType ?? "course";
  const title = state.title?.trim() || DEFAULT_TITLE;
  const minutes = state.dailyMinutes ?? DEFAULT_MINUTES;
  const materials = state.materials ?? "none";
  const materialText = materials === "now" ? "有，现在交" : materials === "later" ? "有，晚点交" : "没有";
  const lines = [
    { label: "想学成什么样", value: title },
    { label: "什么时候完成", value: state.deadlineChosen ? state.deadlineText || "不急" : "不设日期" },
    { label: "每天时间", value: `${minutes} 分钟` },
    { label: "资料", value: materialText },
  ];
  if (goalType !== "skill") lines.push({ label: "学到哪了", value: state.progressChosen ? state.progress || "刚开始" : "刚开始" });
  return lines;
}

export function buildDraft(state: GoalState): DraftBody | null {
  if (state.step !== "confirm") return null;
  const body: DraftBody = {
    goal_type: state.goalType ?? "course",
    title: state.title?.trim() || DEFAULT_TITLE,
    daily_minutes: state.dailyMinutes ?? DEFAULT_MINUTES,
    progress: asksProgress(state) ? state.progress?.trim() || "" : "",
    materials: state.materials ?? "none",
  };
  if (state.deadlineChosen && state.deadline) body.deadline = state.deadline;
  return body;
}

export function validateUnits(units: UnitInput[]): { ok: true; units: UnitInput[] } | { ok: false; message: string } {
  if (!Array.isArray(units) || units.length < 1 || units.length > 20) return { ok: false, message: "单元要有 1 到 20 个" };
  const cleaned: UnitInput[] = [];
  const seen = new Set<string>();
  for (const unit of units) {
    const title = unit.title.trim();
    if (!title) return { ok: false, message: "单元标题不能空" };
    if (title.length > 200) return { ok: false, message: "单元标题太长了" };
    if (seen.has(title)) return { ok: false, message: "单元标题不能重复" };
    seen.add(title);
    if (!Array.isArray(unit.points) || unit.points.length < 1 || unit.points.length > 20) {
      return { ok: false, message: "每个单元的要点要有 1 到 20 条" };
    }
    const points = unit.points.map((point) => point.trim());
    if (points.some((point) => !point)) return { ok: false, message: "要点不能空" };
    if (points.some((point) => point.length > 1000)) return { ok: false, message: "要点太长了" };
    cleaned.push({ title, points });
  }
  return { ok: true, units: cleaned };
}

export type AcceptedOutline = { id: string; day: string };

/** 撤销只在确认当天显示。今天以 /api/plan/today 的 date 为准。 */
export function acceptanceNotice(stored: AcceptedOutline | null, today: string): { id: string; text: string } | null {
  if (!stored?.id || stored.day !== today) return null;
  return { id: stored.id, text: ACCEPTED_TEXT };
}

type LearnTask = { id: string; kind?: string; status: string; ref?: { source?: string; lecture_no?: number } };
type UnitTitles = { units: { no?: number; title: string }[] };

/** 正在学的单元：今天第一件没完成的「学第 N 讲」；都学完了就是今天学的那一讲（练、考还在这一讲上）。 */
export function currentUnitNo(tasks: LearnTask[]): number | null {
  const learn = tasks.filter((item) => item.kind === "learn" && item.ref?.source === "lecture" && typeof item.ref.lecture_no === "number");
  const task = learn.find((item) => item.status !== "done") ?? learn[learn.length - 1];
  return task?.ref?.lecture_no ?? null;
}

/** 块4：确认大纲后、第 1 讲还没学完时，明确告诉用户下一步。 */
export function firstLectureStep(outline: UnitTitles | null, tasks: LearnTask[]): { unitNo: number; taskId: string; text: string } | null {
  if (!outline || !outline.units.length) return null;
  const task = tasks.find((item) => item.kind === "learn" && item.status !== "done" && item.ref?.source === "lecture" && item.ref.lecture_no === 1);
  if (!task) return null;
  const title = outline.units.find((unit, index) => (unit.no ?? index + 1) === 1)?.title ?? outline.units[0].title;
  return { unitNo: 1, taskId: task.id, text: `大纲好了，我们从第 1 讲「${title}」开始。` };
}

type PathOutline = {
  units: { no?: number; title: string; points: string[] }[];
  learned_up_to?: number;
  checkpoints?: { stage_no: number; after_unit: number; title: string; status: "upcoming" | "ready" | "done"; score: number | null }[];
};
export type PathNode = {
  no: number;
  title: string;
  points: string[];
  state: "done" | "today" | "upcoming";
  learned: boolean;
  checkpoint: NonNullable<PathOutline["checkpoints"]>[number] | null;
};

/** V2.2 路径图：每讲的状态 + 阶段关卡挂在该阶段最后一讲后面。 */
export function pathNodes(outline: PathOutline, currentNo: number | null): PathNode[] {
  const learned = outline.learned_up_to ?? 0;
  const gates = new Map((outline.checkpoints ?? []).map((gate) => [gate.after_unit, gate]));
  return outline.units.map((unit, index) => {
    const no = unit.no ?? index + 1;
    const state = no === currentNo ? "today" : no <= learned ? "done" : "upcoming";
    return { no, title: unit.title, points: unit.points, state, learned: no <= learned, checkpoint: gates.get(no) ?? null };
  });
}
