import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AnswerDetails, LearningSummary, matchesFilter, StateTag } from "./LearningSummary";
import { QuizCard } from "./QuizCard";
import { QuestionReviewList } from "./QuestionReviewList";
import { FeedbackPanel } from "./FeedbackPanel";
import type { LearningState, Quiz, Result, ReviewItem, Summary } from "./api";

const empty: Summary = { accuracy: null, effective_count: 0, correct_count: 0, wrong_count: 0,
  consolidate_count: 0, reported_count: 2, unmarked_count: 0, legacy_unknown_count: 0 };
const quiz: Quiz = { quiz_id: "test", lecture_id: "pdf", questions: [{ id: "q", stem: "示例题干", options: [{ id: "A", text: "示例选项" }], difficulty: "easy", source: { page: 1 }, mock: true }], label: "模拟", mock: true };
const result: Result = { attempt_id: "a", question_id: "q", your_answer: "A", answer: "A", correct: true,
  analysis: "解析只展示一次", source: { page: 1, quote: "逐字原文" }, confidence: "low", confidence_label: "没有把握",
  confidence_status: "low", feedback: "重复鼓励语", action_feedback: "冗长分类规则", learning_state: "consolidate", learning_label: "答对待巩固", priority: false, excluded: false, review_recommended: true, review_rank: 2, review_passed: false };
const item: ReviewItem = { ...quiz.questions[0], ...result, lecture_id: "pdf", root_id: "q", has_attempt: true,
  next_review_on: "", history_count: 1, history: [{ ...result, stem: "示例题干", created_at: "2026-11-05T00:00:00Z" }] };
const renderQuiz = (value: Quiz) => renderToStaticMarkup(createElement(QuizCard, { quiz: value, onChange: () => {}, onComplete: () => {}, onRecordsChange: async () => {} }));
const renderList = (items: ReviewItem[], onStart?: () => void) => renderToStaticMarkup(createElement(QuestionReviewList, { items, onStart, onFeedback: async () => {} }));

describe("精简页面保留学习状态规则", () => {
  it("没有有效作答时不显示0%或NaN，不再提供统计说明", () => {
    const html = renderToStaticMarkup(createElement(LearningSummary, { summary: empty, title: "学习概览" }));
    expect(html).toContain("暂无可统计的作答"); expect(html).not.toContain("0%"); expect(html).not.toContain("NaN");
    expect(html).toContain("已反馈（暂不计入）2"); expect(html).not.toContain("统计说明");
  });
  it("不显示旧把握度、相关计数或说明", () => {
    const html = renderToStaticMarkup(createElement(LearningSummary, { summary: { ...empty, accuracy: 50, effective_count: 2, correct_count: 1, unmarked_count: 1, legacy_unknown_count: 1 }, title: "学习概览" }));
    expect(html).toContain("50%"); expect(html).not.toContain("未标注把握度的有效作答"); expect(html).not.toContain("有效作答 "); expect(html).not.toContain("把握度"); expect(html).not.toContain("统计说明");
  });
  it("作答前不采集把握度，仍可直接提交答案和反馈问题", () => {
    const html = renderQuiz(quiz);
    expect(html).not.toContain("把握度"); expect(html).not.toContain("没有把握");
    expect(html).toContain("提交答案"); expect(html).toContain("反馈题目问题");
  });
  it("提交后只有一个对错结果，最后一题为完成练习，原文默认折叠", () => {
    const html = renderQuiz({ ...quiz, results: { q: result } });
    expect(html).not.toContain("把握度"); expect(html).not.toContain("没有把握"); expect(html).not.toContain('aria-pressed=');
    expect(html.match(/答对了/g)).toHaveLength(1); expect(html).not.toContain("重复鼓励语"); expect(html).not.toContain("冗长分类规则");
    expect(html).toContain("完成练习"); expect(html).toContain("正确答案"); expect(html).toContain("你的选择");
    expect(html).toContain("查看 PDF 原文"); expect(html).not.toMatch(/<details[^>]*open/);
  });
  it("完成页不铺开题目和解析，仅提供回顾和首页入口", () => {
    const html = renderQuiz({ ...quiz, completed: true, summary: { ...empty, accuracy: 100, effective_count: 1, correct_count: 1 }, results: { q: result } });
    expect(html).toContain("回顾本套题"); expect(html).toContain("返回首页"); expect(html).not.toContain("示例题干"); expect(html).not.toContain("解析只展示一次");
  });
  it("默认复习错题，全部保留已反馈，未作答不混入列表", () => {
    const html = renderList([item, { ...item, question_id: "new", stem: "未答题干", has_attempt: false }]);
    expect(html).not.toContain("示例题干"); expect(html).not.toContain("未答题干"); expect(html).toContain("这里暂时没有题目");
    expect(matchesFilter({ learning_state: "reported" } as LearningState, "wrong")).toBe(false);
    expect(matchesFilter({ learning_state: "reported" } as LearningState, "all")).toBe(true);
  });
  it("复习行默认显示复选框，当前解析不在历史中重复", () => {
    const wrong = { ...item, correct: false, learning_state: "wrong", priority: true, history: [item.history[0], { ...item.history[0], attempt_id: "old", analysis: "历史解析" }] } as ReviewItem;
    const html = renderList([wrong], () => {});
    expect(html).not.toContain("批量选择"); expect(html).toContain('type="checkbox"'); expect(html).toContain("全选本页"); expect(html).not.toMatch(/<details[^>]*open/);
    expect(html.match(/解析只展示一次/g)).toHaveLength(1); expect(html).toContain("历史解析"); expect(html).toContain("待巩固"); expect(html).not.toContain("优先复习");
  });
  it("普通答对没有正常记录标签，已反馈覆盖复习标签", () => {
    expect(renderToStaticMarkup(createElement(StateTag, { item: { ...item, learning_state: "normal" } }))).toBe("");
    expect(renderToStaticMarkup(createElement(StateTag, { item: { ...item, excluded: true, priority: true } }))).toContain("已反馈");
    const html = renderToStaticMarkup(createElement(AnswerDetails, { result: { ...result, excluded: true, priority: true } }));
    expect(html).not.toContain("优先复习"); expect(html).not.toContain("冗长分类规则");
  });
  it("反馈使用默认关闭的原生弹窗，未选择类型不能提交", () => {
    const html = renderToStaticMarkup(createElement(FeedbackPanel, { questionId: "q", onSaved: async () => {} }));
    expect(html).toContain("<dialog"); expect(html).not.toMatch(/<dialog[^>]*open/);
    expect(html).toContain("取消"); expect(html).toMatch(/disabled="">提交反馈/);
  });
  it("没有候选时全选和开始复习都禁用", () => {
    const html = renderList([{ ...item, learning_state: "reported", excluded: true, review_recommended: false }], () => {});
    expect(html).toMatch(/disabled="">开始复习/); expect(html).toContain('aria-label="全选本页"'); expect(html).not.toContain("批量选择");
  });
});


describe("第二轮统计标签", () => {
  it("有效作答6、答对5，显示答对5、答错1及独立反馈数", () => {
    const html = renderToStaticMarkup(createElement(LearningSummary, { summary: { ...empty, effective_count: 6, correct_count: 5, wrong_count: 1, reported_count: 2, accuracy: 83.33 }, title: "学习概览" }));
    expect(html).toContain('class="practice-count-correct">答对 5');
    expect(html).toContain('class="practice-count-wrong">答错 1');
    expect(html).toContain('class="practice-count-reported">已反馈（暂不计入）2');
    expect(html).not.toContain("有效作答 "); expect(html).not.toContain("未标注把握度的有效作答");
  });
  it("全部中的普通已答题也可手动选，已反馈题目禁选", () => {
    const html = renderToStaticMarkup(createElement(QuestionReviewList, { items: [{ ...item, learning_state: "normal", review_recommended: false }, { ...item, question_id: "reported", stem: "已反馈题干", excluded: true, learning_state: "reported" }], initialFilter: "all", onStart: () => {}, onFeedback: async () => {} }));
    expect(html.match(/type="checkbox"/g)).toHaveLength(3);
    expect(html).toMatch(/aria-label="选择复习题：示例题干"(?![^>]*disabled)/);
    expect(html).toMatch(/aria-label="选择复习题：已反馈题干"[^>]*disabled/);
    expect(html).toMatch(/disabled="">开始复习/);
    expect(html).toContain("换个问法，练同一个知识点。");
  });
});


describe("第三轮只按对错分类", () => {
  it("历史低把握答对列入答对的题，不混入待巩固", () => {
    expect(matchesFilter(item, "correct")).toBe(true);
    expect(matchesFilter(item, "wrong")).toBe(false);
    const html = renderToStaticMarkup(createElement(QuestionReviewList, { items: [item], initialFilter: "correct", onStart: () => {}, onFeedback: async () => {} }));
    expect(html).toContain("示例题干"); expect(html).not.toContain("把握度"); expect(html).not.toContain("没有把握");
    expect(html.indexOf('>待巩固</button>')).toBeLessThan(html.indexOf('>答对的题</button>'));
    expect(html.indexOf('>答对的题</button>')).toBeLessThan(html.indexOf('>全部</button>'));
  });
  it("历史高把握答错仅显示待巩固，逐次历史也不显示旧把握度", () => {
    const old = { ...item, correct: false, learning_state: "wrong", priority: true, confidence: "high", confidence_label: "很有把握", history: [item.history[0], { ...item.history[0], attempt_id: "previous", confidence_label: "历史把握度：八成吧" }] } as ReviewItem;
    const html = renderList([old], () => {});
    expect(html).toContain("待巩固"); expect(html).not.toContain("优先复习");
    expect(html).not.toContain("把握度"); expect(html).not.toContain("很有把握");
    expect(html).toContain("作答历史"); expect(html).toContain("查看 PDF 原文");
  });
  it("反馈仍独立排除，不混入待巩固或答对的题", () => {
    const reported = { ...item, correct: true, excluded: true, learning_state: "reported" } as ReviewItem;
    expect(matchesFilter(reported, "correct")).toBe(false);
    expect(matchesFilter(reported, "wrong")).toBe(false);
    expect(matchesFilter(reported, "reported")).toBe(true);
    expect(matchesFilter(reported, "all")).toBe(true);
  });
});
