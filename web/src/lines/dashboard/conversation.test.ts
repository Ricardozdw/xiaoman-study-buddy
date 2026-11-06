import { describe, expect, it } from "vitest";
import { mergeDashboardTurns, type DashboardTurn } from "./conversation";

const board = (id: string, after: number): DashboardTurn => ({ id, after, question: "这周学得怎么样" });
const ids = (answers: string[], dashboard: DashboardTurn[]) => mergeDashboardTurns(answers, dashboard)
  .map(entry => entry.kind === "qa" ? entry.answer : entry.turn.id);

describe("问答和看板的合并对话", () => {
  it("看板之后继续提问，顺序仍然是问答→看板→问答", () => {
    const dashboard = [board("board", 2)];
    expect(ids(["question", "answer"], dashboard)).toEqual(["question", "answer", "board"]);
    expect(ids(["question", "answer", "next-question", "next-answer"], dashboard))
      .toEqual(["question", "answer", "board", "next-question", "next-answer"]);
  });

  it("连续查询看板与上传提示保持发出顺序", () => {
    expect(ids(["upload-notice"], [board("first", 0), board("second", 0), board("third", 1)]))
      .toEqual(["first", "second", "upload-notice", "third"]);
  });

  it("最新看板之后，之前的计划回答不再是最后一条", () => {
    const conversation = mergeDashboardTurns(["plan-answer"], [board("board", 1)]);
    expect(conversation.at(-1)?.kind).toBe("dashboard");
  });
});
