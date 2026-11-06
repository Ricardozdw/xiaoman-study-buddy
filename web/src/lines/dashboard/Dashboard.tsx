import { useEffect, useState } from "react";
import { boardSummary, fetchBoard, type Board } from "./client";

export function DashboardSummary({ board, onOpen }: { board: Board; onOpen: () => void }) {
  return <section className="card" aria-label="本周学习摘要">
    <header><h3>这周的学习</h3><span className={board.mock ? "badge sim" : "badge"}>{board.label}</span></header>
    <p>{boardSummary(board)}</p>
    <button type="button" className="btn" onClick={onOpen}>打开完整看板</button>
  </section>;
}

export function DashboardPanel({ onUpdate }: { onUpdate?: (board: Board) => void }) {
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void fetchBoard(controller.signal).then((data) => {
      if (!controller.signal.aborted) { setBoard(data); onUpdate?.(data); }
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "读取失败，请重试。");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [revision, onUpdate]);

  return <section aria-label="学习看板" aria-busy={loading}>
    <div className="btns"><button type="button" className="btn" disabled={loading} onClick={() => setRevision((v) => v + 1)}>{loading ? "正在读取…" : "刷新看板"}</button></div>
    {error && <p role="alert">{error}</p>}
    {board && <>
      {error && <p className="aux">以下保留上次读取的记录。</p>}
      <p className={board.mock ? "badge sim" : "badge"}>{board.label}</p>
      {board.period && <p className="aux">{board.period.start} 至 {board.period.end} · 北京时间</p>}
      <dl>
        <dt>这周学了</dt><dd>{board.studied_days} 天</dd>
        <dt>本周做题</dt><dd>{board.attempt_count} 道</dd>
        <dt>待重做错题</dt><dd>{board.mistakes_due} 道</dd>
      </dl>
      {!board.studied_days && <p>从今天的一件小事开始，做过的都会记在这里。</p>}
      <h3>每讲掌握度</h3>
      {!board.lectures.length && <p>交一讲资料、练几道题后，这里会有你的学习记录。</p>}
      <ul className="tasks">{board.lectures.map((lecture) => <li key={lecture.id}>
        <strong>{lecture.title}</strong>
        <p>{lecture.assessed === false ? "还未评估" : `掌握 ${lecture.mastery}%`}</p>
        {lecture.assessed !== false && <progress max={100} value={lecture.mastery} aria-label={`${lecture.title}掌握度`} />}
        {!!lecture.mistakes_due && <p className="aux">待重做 {lecture.mistakes_due} 道</p>}
      </li>)}</ul>
      <p className="aux">{board.mastery_note}</p>
      <h3>目标进度</h3>
      {board.goal?.title ? <>
        <p>{board.goal.title}</p>
        <p>已完成 {board.goal.completed_lectures} / {board.goal.total_lectures} 讲 · {Math.round(board.goal_progress * 100)}%</p>
        <progress max={1} value={board.goal_progress} aria-label="目标进度" />
      </> : <p>先和小满定一个学习目标。</p>}
      <p className="aux">{board.note}</p>
    </>}
  </section>;
}
