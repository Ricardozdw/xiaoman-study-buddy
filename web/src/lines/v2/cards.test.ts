import { describe, expect, it } from "vitest";
import { V2_OPENING } from "./logic";
import {
  ASSESSMENT_INVITE,
  COMPLETION_SUGGEST,
  FORBIDDEN_WORDS,
  GENERIC_QUESTION_BADGE,
  GOAL_DONE_RAIL,
  NEXT_GOAL_HINT,
  completionLines,
  forbiddenHit,
  pickInitialView,
  reportLines,
  stepIndex,
  submitGuard,
  viewAfterReport,
  weakLine,
  type Report,
} from "./cards";

const report: Report = {
  score: 70,
  units: [
    { no: 1, title: "考试概览与准备", correct: 3, total: 4 },
    { no: 3, title: "核心概念 2", correct: 1, total: 3 },
  ],
  weak_unit_nos: [3],
  summary: "这一阶段做了 10 题，对了 7 题。第 3 单元再看一眼会更稳。",
};

describe("题目切换与交卷前提示", () => {
  const ids = ["q1", "q2", "q3"];

  it("上一题下一题停在第一题和最后一题", () => {
    expect(stepIndex(0, 10, -1)).toBe(0);
    expect(stepIndex(0, 10, 1)).toBe(1);
    expect(stepIndex(8, 10, 1)).toBe(9);
    expect(stepIndex(9, 10, 1)).toBe(9);
    expect(stepIndex(3, 0, 1)).toBe(0);
  });

  it("还有题没选时提示可以回去补，也可以交卷；一道都没答不能交", () => {
    expect(submitGuard(ids, {})).toEqual({ ok: false, canForce: false, message: "先回答至少一道题，就可以交卷。" });
    const partial = submitGuard(ids, { q1: "B" });
    expect(partial.ok).toBe(false);
    if (!partial.ok) {
      expect(partial.canForce).toBe(true);
      expect(partial.message).toContain("还有 2 题没选");
      expect(partial.message).toContain("也可以现在交卷");
    }
    expect(submitGuard(ids, { q1: "A", q2: "B", q3: "C" })).toEqual({ ok: true });
    expect(stepIndex(1, ids.length, -1)).toBe(0);
  });
});

describe("报告和完成文案", () => {
  it("禁用词列表能认出不及格，产品文案里没有这些词", () => {
    expect(FORBIDDEN_WORDS).toContain("不及格");
    expect(forbiddenHit("这次不及格")).toBe("不及格");
    expect(forbiddenHit("很差")).toBe("很差");
    const copy = [
      V2_OPENING,
      ASSESSMENT_INVITE,
      COMPLETION_SUGGEST,
      NEXT_GOAL_HINT,
      GOAL_DONE_RAIL,
      GENERIC_QUESTION_BADGE,
      ...reportLines(report),
      weakLine([3]) || "",
      ...completionLines({ days: 4, attempts: 10, first_score: 70, last_score: 100, hardest_unit: null }),
      "还有 2 题没选。没答的不算错，可以回去补，也可以现在交卷。",
      "先回答至少一道题，就可以交卷。",
    ];
    for (const line of copy) expect(forbiddenHit(line), line).toBeNull();
  });

  it("报告写出总分、对几题和薄弱单元；全对的完成卡不写最难单元", () => {
    const lines = reportLines(report);
    expect(lines[0]).toBe("70 分");
    expect(lines).toContain("考试概览与准备：对 3 / 4");
    expect(lines).toContain("第 3 单元再看一眼会更稳");
    expect(lines.at(-1)).toBe(report.summary);
    const perfect = completionLines({ days: 6, attempts: 10, first_score: 100, last_score: 100, hardest_unit: null });
    expect(perfect).toEqual(["学了 6 天", "做了 10 题", "阶段测验从 100 分到 100 分"]);
    expect(perfect.join("")).not.toContain("最难");
    const hard = completionLines({ days: 6, attempts: 10, first_score: 60, last_score: 80, hardest_unit: "核心概念 2" });
    expect(hard).toContain("最难的单元：核心概念 2");
    expect(hard).toContain("阶段测验从 60 分到 80 分");
  });
});

describe("一次只出一张", () => {
  it("完成建议压过测验；晚点再考的当天不再出邀请", () => {
    expect(pickInitialView({ done: false, suggest: true, due: true, laterDay: null, today: "2026-11-07" })).toBe("suggest");
    expect(pickInitialView({ done: true, suggest: true, due: true, laterDay: null, today: "2026-11-07" })).toBe("done");
    expect(pickInitialView({ done: false, suggest: false, due: true, laterDay: "2026-11-07", today: "2026-11-07" })).toBe("idle");
    expect(pickInitialView({ done: false, suggest: false, due: true, laterDay: "2026-11-07", today: "2026-11-14" })).toBe("invite");
    expect(pickInitialView({ done: false, suggest: false, due: false, laterDay: null, today: "2026-11-07" })).toBe("idle");
    expect(viewAfterReport({ done: false, suggest: true })).toBe("suggest");
    expect(viewAfterReport({ done: false, suggest: false })).toBe("idle");
  });
});
