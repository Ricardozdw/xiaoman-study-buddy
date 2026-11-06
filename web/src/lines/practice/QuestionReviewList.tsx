import { useEffect, useRef, useState } from "react";
import { Button } from "../../components/ui";
import type { FeedbackRecord, Result, ReviewItem } from "./api";
import { FeedbackPanel } from "./FeedbackPanel";
import { AnswerDetails, filters, matchesFilter, OptionReview, StateTag } from "./LearningSummary";

type Props = { items: ReviewItem[]; busy?: boolean; initialFilter?: string; quizId?: string;
  onStart?: (items: ReviewItem[]) => void; onFeedback: (record: FeedbackRecord) => Promise<void> };
export function QuestionReviewList({ items, busy = false, initialFilter = "wrong", quizId, onStart, onFeedback }: Props) {
  const [filter, setFilter] = useState(initialFilter);
  const [selected, setSelected] = useState<string[]>([]);
  const answered = items.filter((item) => item.has_attempt);
  const visible = answered.filter((item) => matchesFilter(item, filter));
  const eligible = visible.filter((item) => item.has_attempt && !item.excluded);
  const chosen = eligible.filter((item) => selected.includes(item.question_id));
  const allChecked = eligible.length > 0 && chosen.length === eligible.length;
  const partlyChecked = chosen.length > 0 && !allChecked;
  const selectAll = useRef<HTMLInputElement>(null);
  useEffect(() => { if (selectAll.current) selectAll.current.indeterminate = partlyChecked; }, [partlyChecked]);
  const overLimit = chosen.length > 15;
  function changeFilter(value: string) { setFilter(value); setSelected([]); }
  return <section className="practice-review-list" aria-label="题目列表">
    <div className="practice-review-tools">
      <div className="btns" aria-label="题目筛选">{filters.map(([value, label]) => <Button key={value} disabled={busy}
        aria-pressed={filter === value} onClick={() => changeFilter(value)}>{label}</Button>)}</div>
      <details className="practice-extra-filter"><summary>更多筛选{filter === "reported" ? " · 已反馈" : ""}</summary>
        <Button aria-pressed={filter === "reported"} disabled={busy} onClick={() => changeFilter("reported")}>已反馈</Button>
      </details>
    </div>
    {onStart && <>
      <p className="aux practice-review-intro">换个问法，练同一个知识点。</p>
      <label className="practice-select-all"><span className="practice-review-checkbox"><input ref={selectAll} type="checkbox" aria-label="全选本页"
        aria-checked={partlyChecked ? "mixed" : allChecked} checked={allChecked} disabled={busy || !eligible.length}
        onChange={() => setSelected(allChecked ? [] : eligible.map((item) => item.question_id))} /></span><span>全选本页</span></label>
    </>}
    {!visible.length && <p className="practice-empty">{answered.length ? "这里暂时没有题目。" : "还没有已答题，先去练一练吧。"}</p>}
    {visible.map((item) => <div className="practice-review-row" key={item.question_id}>
      {onStart && <label className="practice-review-checkbox"><input type="checkbox" aria-label={`选择复习题：${item.stem}`}
        checked={!item.excluded && selected.includes(item.question_id)} disabled={busy || item.excluded}
        title={item.excluded ? "已反馈，暂不参与复习" : "选择这道题"}
        onChange={() => setSelected((ids) => ids.includes(item.question_id) ? ids.filter((id) => id !== item.question_id) : [...ids, item.question_id])} /></label>}
      <details className="practice-question-detail"><summary><span className="practice-question-excerpt">{item.stem}</span><StateTag item={item} /></summary>
        <div className="practice-expanded"><h3>{item.stem}</h3>
          {item.mock && <span className="badge sim">模拟</span>}
          <OptionReview question={item} result={item as Result} />
          <AnswerDetails result={item as Result} />
          {item.history.length > 1 && <details className="practice-history"><summary>作答历史（{item.history.length} 次）</summary>
            {item.history.map((old) => <details key={old.attempt_id}><summary>{new Date(old.created_at).toLocaleString()} · {old.attempt_id === item.attempt_id ? "最近一次" : "此前作答"} · {old.correct ? "答对" : "答错"}</summary>
              {old.attempt_id === item.attempt_id ? <p className="aux">本次解析见上方。</p> : <><p>{old.stem}</p><AnswerDetails result={old} showChoices /></>}
            </details>)}
          </details>}
          <div className="practice-row-footer">
            {onStart && !item.excluded && <Button disabled={busy} onClick={() => onStart([item])}>换个问法再练</Button>}
            <FeedbackPanel inlineNotice={false} disabled={busy} questionId={item.question_id} quizId={quizId} attemptId={item.attempt_id} report={item.report} onSaved={onFeedback} />
          </div>
        </div>
      </details>
    </div>)}
    {onStart && <div className="practice-batch-bar">
      <div><span>已选 {chosen.length} 题</span>{overLimit && <p role="alert" className="aux">一次最多复习15题，请取消部分选择。</p>}</div>
      <Button variant="primary" disabled={busy || !chosen.length || overLimit} onClick={() => {
        if (!busy && chosen.length > 0 && chosen.length <= 15) onStart(chosen);
      }}>{busy ? "生成中…" : "开始复习"}</Button>
    </div>}
  </section>;
}
