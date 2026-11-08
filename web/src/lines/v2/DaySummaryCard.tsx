import { useEffect, useState } from "react";
import { Avatar } from "../../components/Avatar";
import { Button, Card } from "../../components/ui";
import { getTodaySummary, type TodaySummary } from "./api";

/** V2.2 今天三件做完：小满庆祝 + 当日总结（模板文案，不调模型），下面接「学下一讲」。 */
export function DaySummaryCard({ refreshKey, next, busy, onNext }: {
  refreshKey: string;
  next: { no: number; title: string } | null;
  busy: boolean;
  onNext: (no: number) => void;
}) {
  const [summary, setSummary] = useState<TodaySummary | null>(null);
  useEffect(() => {
    let cancelled = false;
    void getTodaySummary().then((data) => { if (!cancelled) setSummary(data); });
    return () => { cancelled = true; };
  }, [refreshKey]);

  return (
    <Card as="section" aria-label="今天完成" data-v2-card="day-summary">
      <div className="v2-celebrate">
        <span className="v2-celebrate-avatar"><Avatar mood="wave" size={56} /></span>
        <div>
          <h3>今天的三件都做完了</h3>
          <p className="aux">辛苦了，今天的记录小满都记下了。</p>
        </div>
      </div>
      {summary ? (
        <>
          <div className="day-stats" aria-label="今天的成绩">
            <div><strong>{summary.lectures?.length ?? 0}</strong><span>学了几讲</span></div>
            <div><strong>{summary.practice?.total ? `${summary.practice.correct}/${summary.practice.total}` : "—"}</strong><span>练习答对</span></div>
            <div><strong>{summary.exam ? `${summary.exam.score}` : "—"}</strong><span>考试分数</span></div>
            <div><strong>{summary.total_days}</strong><span>累计天数</span></div>
          </div>
          {/* 数字已经在上面四格里，下面只写今天学了哪几讲，不再把同样的数字念一遍。 */}
          {summary.lectures?.length
            ? <p className="aux">今天学了：{summary.lectures.map((item) => `第 ${item.no} 讲「${item.title}」`).join("、")}</p>
            : <ul className="v2-lines">{summary.lines.map((line) => <li key={line}>{line}</li>)}</ul>}
        </>
      ) : (
        <p role="status" className="aux">正在整理今天的记录…</p>
      )}
      {next && (
        <>
          <p>还想多学一点的话，可以接着学第 {next.no} 讲「{next.title}」，明天就从再下一讲开始。</p>
          <div className="btns">
            <Button variant="primary" disabled={busy} onClick={() => onNext(next.no)}>学第 {next.no} 讲</Button>
          </div>
        </>
      )}
    </Card>
  );
}
