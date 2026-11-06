import type { ReactNode } from "react";
import type { LearningState, Question, Result, Summary } from "./api";

export const filters = [["wrong", "待巩固"], ["correct", "答对的题"], ["all", "全部"]] as const;
export function matchesFilter(item: (LearningState & { correct?: boolean }) | undefined, filter: string) {
  if (filter === "all") return true;
  if (filter === "reported") return Boolean(item?.excluded);
  if (!item || item.excluded || typeof item.correct !== "boolean") return false;
  return filter === "correct" ? item.correct : filter === "wrong" ? !item.correct : false;
}
export function StateTag({ item }: { item: LearningState }) {
  const label = item.excluded ? "已反馈" : item.learning_state === "wrong" ? "待巩固" : "";
  return label ? <span className="badge">{label}</span> : null;
}
export function LearningSummary({ summary, title, action }: { summary: Summary; title: string; action?: ReactNode }) {
  return <section className="practice-overview" aria-label={title}><header className="practice-overview-heading"><h2>{title}</h2>{action}</header>
    <div className="practice-metrics">
      <p><strong>{summary.accuracy === null ? "—" : `${summary.accuracy}%`}</strong><span>正确率</span></p>
      <p><strong>{summary.wrong_count}</strong><span>错题</span></p>
      <p><strong>{summary.consolidate_count}</strong><span>待巩固</span></p>
    </div>
    {summary.accuracy === null && <p className="aux">暂无可统计的作答</p>}
    <div className="practice-count-tags" aria-label="作答计数">
      <span className="practice-count-correct">答对 {summary.correct_count}</span>
      <span className="practice-count-wrong">答错 {summary.wrong_count}</span>
      <span className="practice-count-reported">已反馈（暂不计入）{summary.reported_count}</span>
    </div>

  </section>;
}
export function OptionReview({ question, result }: { question: Question; result: Result }) {
  return <ul className="practice-options practice-options-review">{question.options.map((o) => <li key={o.id}>
    <span>{o.id} {o.text}</span><span className="practice-option-note">{o.id === result.answer && "✓ 正确答案"}{o.id === result.your_answer && (o.id === result.answer ? " · 你的选择" : "你的选择")}</span>
  </li>)}</ul>;
}
export function AnswerDetails({ result, showChoices = false }: { result: Result; showChoices?: boolean }) {
  return <section className="practice-answer">
    <div className="practice-result-line"><strong>{result.correct ? "✓ 答对了" : "这题答错了"}</strong><StateTag item={result} /></div>
    {showChoices && <p className="aux">你选 {result.your_answer} · 正确答案 {result.answer}</p>}
    <p className="practice-analysis">{result.analysis}</p>
    {result.source.page && <details className="practice-source"><summary>查看 PDF 原文 · 第 {result.source.page} 页</summary>
      <blockquote>【第 {result.source.page} 页】{result.source.quote}</blockquote>
    </details>}
  </section>;
}
