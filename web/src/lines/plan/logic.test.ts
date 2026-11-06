import { describe, expect, it } from "vitest";
import { answer, cardLabel, changesLeftColumn, isPrimary, nextQuestion } from "./logic";
import type { PlanCard } from "./types";

const card = (options: { id: string; label: string }[], type: PlanCard["type"] = "suggestion"): PlanCard => ({
  id: "c1",
  kind: "x",
  type,
  title: "t",
  lines: [],
  badge: "模拟",
  collapsed_text: "",
  options,
  status: "pending",
});

describe("计划线 · 目标问答", () => {
  it("一次一题，问完返回 null", () => {
    const qs = [{ key: "a", text: "", quick_replies: [], skip_label: "跳过", default_text: "" }];
    expect(nextQuestion(qs, 0)?.key).toBe("a");
    expect(nextQuestion(qs, 1)).toBeNull();
  });

  it("跳过的题不写进回答（默认值不算用户的选择）", () => {
    expect(answer({}, "exam_date", "  ")).toEqual({});
    expect(answer({ exam_date: "x" }, "exam_date", null)).toEqual({});
    expect(answer({}, "lecture_count", "12 讲")).toEqual({ lecture_count: "12 讲" });
  });
});

describe("计划线 · 卡片", () => {
  it("只有一个选项时它是主按钮，多个选项都不是", () => {
    const one = card([{ id: "ok", label: "好" }]);
    expect(isPrimary(one, one.options[0])).toBe(true);
    const many = card([{ id: "a", label: "A" }, { id: "b", label: "B" }], "reschedule");
    expect(many.options.some((o) => isPrimary(many, o))).toBe(false);
    expect(cardLabel(many)).toBe("重排");
  });

  it("生效和撤销会改左栏", () => {
    expect(changesLeftColumn("accept")).toBe(true);
    expect(changesLeftColumn("undo")).toBe(true);
    expect(changesLeftColumn("revise")).toBe(false);
  });
});
