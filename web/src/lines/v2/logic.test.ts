import { describe, expect, it } from "vitest";
import {
  CONFIRM_SENTENCE,
  DEFAULT_NOTES,
  MATERIALS_NOW_NOTICE,
  V2_OPENING,
  acceptanceNotice,
  addDays,
  applyAnswer,
  buildDraft,
  defaultNotes,
  goalNamePrompt,
  initialGoalState,
  stepProgress,
  validateUnits,
  type AnswerInput,
} from "./logic";
import { OUTLINE_BADGE, answerUsesOutlineSource, isOutlineFilename } from "./source";

const TODAY = "2026-11-07";

function walk(inputs: AnswerInput[], today = TODAY) {
  const seen = ["goal"];
  let state = initialGoalState();
  const notices: string[] = [];
  for (const input of inputs) {
    const result = applyAnswer(state, input, today);
    expect(result.error, JSON.stringify(input)).toBeUndefined();
    state = result.state;
    if (result.notice) notices.push(result.notice);
    seen.push(state.step);
  }
  return { state, seen, notices };
}

describe("定目标五问", () => {
  it("考证一路答完是五题，然后才到确认", () => {
    const { state, seen } = walk([
      { type: "quick", label: "考过一个证书" },
      { type: "skip" },
      { type: "quick", label: "一个月内" },
      { type: "quick", label: "30 分钟" },
      { type: "quick", label: "没有" },
      { type: "quick", label: "刚开始" },
    ]);
    expect(seen).toEqual(["goal", "goalName", "deadline", "minutes", "materials", "progress", "confirm"]);
    expect(stepProgress(initialGoalState())).toEqual({ current: 1, total: 5 });
    expect(state.step).toBe("confirm");
    const body = buildDraft(state);
    expect(body).toEqual({
      goal_type: "exam",
      title: "考过一个证书",
      deadline: "2026-12-07",
      daily_minutes: 30,
      progress: "刚开始",
      materials: "none",
    });
    expect(defaultNotes(state)).toEqual([]);
  });

  it("技能不问学到哪了", () => {
    const { state, seen } = walk([
      { type: "quick", label: "掌握一项技能" },
      { type: "skip" },
      { type: "quick", label: "不急" },
      { type: "text", text: "50分钟" },
      { type: "quick", label: "有，晚点交" },
    ]);
    expect(seen).toEqual(["goal", "goalName", "deadline", "minutes", "materials", "confirm"]);
    expect(stepProgress(state)).toEqual({ current: 4, total: 4 });
    const body = buildDraft(state);
    expect(body).toEqual({
      goal_type: "skill",
      title: "掌握一项技能",
      daily_minutes: 50,
      progress: "",
      materials: "later",
    });
    expect(body).not.toHaveProperty("deadline");
    expect(defaultNotes(state)).toEqual([]);
  });

  it("跳过的题用默认值，确认里写明这些是先按默认排的", () => {
    const { state } = walk([
      { type: "skip" },
      { type: "skip" },
      { type: "skip" },
      { type: "skip" },
      { type: "skip" },
    ]);
    expect(state.step).toBe("confirm");
    expect(defaultNotes(state)).toEqual([
      DEFAULT_NOTES.goal,
      DEFAULT_NOTES.deadline,
      DEFAULT_NOTES.minutes,
      DEFAULT_NOTES.materials,
      DEFAULT_NOTES.progress,
    ]);
    expect(CONFIRM_SENTENCE).toBe("这些是先按默认排的");
    const body = buildDraft(state);
    expect(body).toEqual({
      goal_type: "course",
      title: "把这门课学完",
      daily_minutes: 30,
      progress: "",
      materials: "none",
    });
    expect(body).not.toHaveProperty("deadline");
    expect(buildDraft(initialGoalState())).toBeNull();
  });

  it("三个月内换成今天加 90 天，不急不传 deadline", () => {
    expect(addDays(TODAY, 30)).toBe("2026-12-07");
    expect(addDays(TODAY, 90)).toBe("2027-02-05");
    const named = applyAnswer(initialGoalState(), { type: "quick", label: "考过一个证书" }, TODAY);
    expect(named.state.step).toBe("goalName");
    const asked = applyAnswer(named.state, { type: "skip" }, TODAY).state;
    const later = applyAnswer(asked, { type: "quick", label: "三个月内" }, TODAY);
    expect(later.state.deadline).toBe("2027-02-05");
    expect(later.state.deadlineText).toBe("三个月内（2027-02-05）");
    const relaxed = applyAnswer(asked, { type: "quick", label: "不急" }, TODAY);
    expect(relaxed.error).toBeUndefined();
    expect(relaxed.state.deadlineChosen).toBe(true);
    expect(relaxed.state.deadline).toBeUndefined();
    expect(defaultNotes({ ...relaxed.state, step: "confirm" })).not.toContain(DEFAULT_NOTES.deadline);
    const skipped = applyAnswer(asked, { type: "skip" }, TODAY);
    expect(skipped.state.deadline).toBeUndefined();
    expect(skipped.state.deadlineChosen).toBe(false);
    const body = buildDraft({ ...relaxed.state, step: "confirm", minutesChosen: true, dailyMinutes: 30, materialsChosen: true, materials: "none" });
    expect(body).not.toHaveProperty("deadline");
  });

  it("具体日期原样传入，非法日期停在这一题", () => {
    let state = applyAnswer(initialGoalState(), { type: "quick", label: "学完一门课或一本书" }, TODAY).state;
    expect(state.step).toBe("goalName");
    state = applyAnswer(state, { type: "skip" }, TODAY).state;
    const picked = applyAnswer(state, { type: "date", date: "2026-12-20" }, TODAY);
    expect(picked.state.deadline).toBe("2026-12-20");
    state = applyAnswer(initialGoalState(), { type: "text", text: "考 PMP" }, TODAY).state;
    expect(state.goalType).toBe("exam");
    expect(state.title).toBe("考 PMP");
    const invalid = applyAnswer(state, { type: "date", date: "2026-02-31" }, TODAY);
    expect(invalid.error).toBeTruthy();
    expect(invalid.state.step).toBe("deadline");
    const unknown = applyAnswer(initialGoalState(), { type: "text", text: "PMP" }, TODAY);
    expect(unknown.error).toBeTruthy();
    expect(unknown.state.step).toBe("goal");
  });

  it("资料三种选择都继续走没资料的大纲，不进入交资料", () => {
    for (const label of ["没有", "有，晚点交", "有，现在交"] as const) {
      const { state, seen, notices } = walk([
        { type: "quick", label: "考过一个证书" },
        { type: "skip" },
        { type: "quick", label: "不急" },
        { type: "quick", label: "15 分钟" },
        { type: "quick", label },
      ]);
      expect(seen.at(-1)).toBe("progress");
      expect(seen).not.toContain("upload");
      expect(state.materials).toBe(label === "没有" ? "none" : label === "有，晚点交" ? "later" : "now");
      expect(notices).toEqual(label === "有，现在交" ? [MATERIALS_NOW_NOTICE] : []);
    }
  });
});

describe("追问具体名称", () => {
  it("快捷回复才追问，填了用原话，跳过才用快捷回复，直接输入不追问", () => {
    expect(V2_OPENING).toBe("我是小满。先说说你想学成什么样，我帮你拆成每天的小任务。");
    const exam = applyAnswer(initialGoalState(), { type: "quick", label: "考过一个证书" }, TODAY);
    expect(exam.error).toBeUndefined();
    expect(exam.state.step).toBe("goalName");
    expect(goalNamePrompt(exam.state.goalType)).toBe("是哪个证书？");
    expect(stepProgress(exam.state)).toEqual({ current: 1, total: 5 });

    const named = applyAnswer(exam.state, { type: "text", text: "PMP 认证" }, TODAY);
    expect(named.error).toBeUndefined();
    expect(named.state.step).toBe("deadline");
    expect(named.state.goalType).toBe("exam");
    expect(named.state.goalChosen).toBe(true);
    expect(named.state.title).toBe("PMP 认证");
    const draft = buildDraft({
      ...named.state,
      step: "confirm",
      deadlineChosen: true,
      deadline: "2026-12-01",
      minutesChosen: true,
      dailyMinutes: 30,
      materialsChosen: true,
      materials: "none",
      progressChosen: true,
      progress: "刚开始",
    });
    expect(draft?.title).toBe("PMP 认证");

    const skipped = applyAnswer(exam.state, { type: "skip" }, TODAY);
    expect(skipped.state.step).toBe("deadline");
    expect(skipped.state.title).toBe("考过一个证书");
    expect(skipped.state.goalChosen).toBe(true);

    const typed = applyAnswer(initialGoalState(), { type: "text", text: "考过 PMP" }, TODAY);
    expect(typed.state.step).toBe("deadline");
    expect(typed.state.title).toBe("考过 PMP");
    const exact = applyAnswer(initialGoalState(), { type: "text", text: "考过一个证书" }, TODAY);
    expect(exact.state.step).toBe("deadline");
    expect(exact.state.title).toBe("考过一个证书");

    const course = applyAnswer(initialGoalState(), { type: "quick", label: "学完一门课或一本书" }, TODAY);
    expect(goalNamePrompt(course.state.goalType)).toBe("是哪门课或哪本书？");
    const skill = applyAnswer(initialGoalState(), { type: "quick", label: "掌握一项技能" }, TODAY);
    expect(goalNamePrompt(skill.state.goalType)).toBe("是哪项技能？");
    expect(stepProgress(skill.state)).toEqual({ current: 1, total: 4 });
    const blank = applyAnswer(exam.state, { type: "text", text: "   " }, TODAY);
    expect(blank.error).toBeTruthy();
    expect(blank.state.step).toBe("goalName");
  });
});

describe("大纲编辑", () => {
  const point = ["一个要点"];

  it("标题不能空，单元要在 1 到 20 个", () => {
    expect(validateUnits([])).toEqual({ ok: false, message: "单元要有 1 到 20 个" });
    expect(validateUnits([{ title: "  ", points: point }])).toEqual({ ok: false, message: "单元标题不能空" });
    expect(validateUnits([{ title: "重复", points: point }, { title: "重复", points: point }]).ok).toBe(false);
    expect(validateUnits([{ title: "只有一个", points: point }]).ok).toBe(true);
    const twenty = Array.from({ length: 20 }, (_, index) => ({ title: `单元${index + 1}`, points: point }));
    const saved = validateUnits(twenty);
    expect(saved.ok).toBe(true);
    if (saved.ok) expect(saved.units).toHaveLength(20);
    expect(validateUnits([...twenty, { title: "多一个", points: point }])).toEqual({ ok: false, message: "单元要有 1 到 20 个" });
    expect(validateUnits([{ title: "有标题", points: ["  "] }])).toEqual({ ok: false, message: "要点不能空" });
  });
});

describe("来源标记与当天撤销", () => {
  const lectures = [
    { id: "lec-1", title: "AI 学习大纲（通用知识，非资料原文）" },
    { id: "lec-6", title: "样例-第6讲.pdf" },
  ];

  it("文件名以 AI 学习大纲开头才算没有出处", () => {
    expect(isOutlineFilename(lectures[0].title)).toBe(true);
    expect(isOutlineFilename("样例-第6讲.pdf")).toBe(false);
    expect(isOutlineFilename("")).toBe(false);
    expect(answerUsesOutlineSource({ references: [{ lecture_id: "lec-1" }] }, lectures)).toBe(true);
    expect(answerUsesOutlineSource({ references: [{ lecture_id: "lec-6" }] }, lectures)).toBe(false);
    expect(answerUsesOutlineSource({ references: [{ lecture_id: "lec-9" }] }, lectures)).toBe(false);
    expect(answerUsesOutlineSource({ handoffIntent: "quiz", lectureId: "lec-1" }, lectures)).toBe(true);
    expect(answerUsesOutlineSource({ handoffIntent: "quiz", lectureId: "lec-6" }, lectures)).toBe(false);
    expect(answerUsesOutlineSource({ handoffIntent: "plan", lectureId: "lec-1" }, lectures)).toBe(false);
    expect(OUTLINE_BADGE).toBe("通用知识，没有出处");
  });

  it("撤销提示只在确认当天出现", () => {
    expect(acceptanceNotice({ id: "abc", day: TODAY }, TODAY)?.text).toBe("已按这份大纲排好，今天的三件在左边");
    expect(acceptanceNotice({ id: "abc", day: TODAY }, "2026-11-08")).toBeNull();
    expect(acceptanceNotice(null, TODAY)).toBeNull();
  });
});
