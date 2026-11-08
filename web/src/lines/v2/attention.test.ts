import { describe, expect, it } from "vitest";
import { attentionItems, headline, type AttnTask } from "./attention";

const t = (id: string, kind: AttnTask["kind"], status: "todo" | "done" = "todo", extra: Partial<AttnTask> = {}): AttnTask =>
  ({ id, kind, status, kind_label: { learn: "学新的", practice: "练一练", repair: "补一补", exam: "考试" }[kind], title: `${kind}-${id}`, minutes: 10, ...extra });

describe("首屏状态与需要关注的事", () => {
  it("一句话状态：还剩几件、按顺序、合计分钟", () => {
    const h = headline({ needsGoal: false, goalDone: false, tasks: [t("1", "learn", "done"), t("2", "practice"), t("3", "exam", "todo", { minutes: 17 })] });
    expect(h.title).toBe("今天还有 2 件事");
    expect(h.sub).toBe("练一练 → 考试 · 大约 27 分钟");
  });

  it("没定目标 / 全做完 的说法", () => {
    expect(headline({ needsGoal: true, goalDone: false, tasks: [] }).title).toBe("先定个学习目标");
    expect(headline({ needsGoal: false, goalDone: false, tasks: [t("1", "learn", "done")], totalDays: 3 })).toEqual({ title: "今天的都做完了", sub: "累计学了 3 天，明天见" });
  });

  it("默认关注下一件；没做完的练习排最前", () => {
    const tasks = [t("1", "learn", "done"), t("2", "practice"), t("3", "exam")];
    expect(attentionItems({ needsGoal: false, goalDone: false, tasks }).map((i) => i.taskId)).toEqual(["2"]);
    const resumed = attentionItems({ needsGoal: false, goalDone: false, tasks, resumeLectureNo: 1 });
    expect(resumed[0]).toMatchObject({ key: "resume", action: "resume", taskId: "2" });
    expect(resumed).toHaveLength(2);
    expect(resumed[1].taskId).toBe("3"); // 同一件不重复出现
  });

  it("考试有错题 / 阶段测验到点时主动提醒，最多两张", () => {
    const tasks = [t("1", "learn"), t("2", "practice"), t("3", "exam", "todo", { ref: { mistake_ids: ["a", "b"] } })];
    const items = attentionItems({ needsGoal: false, goalDone: false, tasks });
    expect(items[0].title).toBe("之前错了 2 题，今天考试先考它们");
    expect(items[1].taskId).toBe("1");
    expect(attentionItems({ needsGoal: false, goalDone: false, tasks, stageReady: 1 })[0].title).toBe("阶段 1 测验可以考了");
  });

  it("全做完、没定目标时都不出卡（不把“做完了”说三遍）", () => {
    expect(attentionItems({ needsGoal: false, goalDone: false, tasks: [t("1", "learn", "done")] })).toEqual([]);
    expect(attentionItems({ needsGoal: true, goalDone: false, tasks: [] })).toEqual([]);
  });
});
