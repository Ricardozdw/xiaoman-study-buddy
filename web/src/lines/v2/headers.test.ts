import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AssessmentCard } from "./AssessmentCard";
import type { Quiz } from "./api";

const quiz = { id: "x", label: "AI 整理，可以改", mock: false, stage: { no: 0, title: "考试 · 第 1 讲", unit_nos: [] },
  questions: [{ id: "q1", stem: "第一题题干", options: [{ id: "A", text: "甲" }] }, { id: "q2", stem: "第二题", options: [] }] } as unknown as Quiz;

describe("考试卡头部", () => {
  it("来源行 → 题干 → 进度条，都在同一个纵向头部里", () => {
    const html = renderToStaticMarkup(createElement(AssessmentCard, { mode: "quiz", quiz, index: 0, answers: {}, busy: false, error: "", warn: "", canForce: false,
      onPick: () => {}, onPrev: () => {}, onNext: () => {}, onSubmit: () => {}, onForce: () => {}, intro: "都是今天这一讲的题" }));
    const header = html.slice(html.indexOf('<header class="lecture-head">'), html.indexOf("</header>"));
    expect(header.indexOf("head-meta")).toBeLessThan(header.indexOf("第一题题干"));
    expect(header.indexOf("第一题题干")).toBeLessThan(header.indexOf("quiz-progress"));
    expect(header).toContain("第 1 / 2 题");
    expect(header).toContain("通用题，没有出处");
  });
});
