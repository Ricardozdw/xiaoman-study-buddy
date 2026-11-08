import { Fragment, useState } from "react";
import type { OutlineView } from "./api";
import { pathNodes } from "./logic";

/**
 * V2.2 学习路径图：学过的点亮、今天这一讲高亮、阶段测验是路上的关卡。
 * 学过的讲可以「再看一遍讲解」（读缓存，不再调模型）；没学的只看要点，不能跳讲。
 */
export function OutlineRail({ outline, currentNo, onReview }: { outline: OutlineView; currentNo: number | null; onReview?: (unitNo: number) => void }) {
  const nodes = pathNodes(outline, currentNo);
  const learned = outline.learned_up_to ?? 0;
  // 默认只露出“学过的最后一讲 + 今天 + 后面两讲”，路线太长时不把左栏撑满。
  const [all, setAll] = useState(false);
  const todayIndex = Math.max(0, nodes.findIndex((node) => node.state === "today"));
  const from = Math.max(0, todayIndex - 1);
  const to = Math.min(nodes.length, todayIndex + 3);
  const shown = all ? nodes : nodes.slice(from, to);
  return (
    <section className="rail-section" aria-label="学习路径">
      <h2>学习路径</h2>
      <p className="aux">{outline.title} · 学了 {Math.min(learned, outline.units.length)} / {outline.units.length} 讲</p>
      <ol className="v2-path">
        {shown.map((node) => (
          <Fragment key={node.no}>
            <li className={`v2-node ${node.state}`}>
              <span className="v2-dot" aria-hidden="true">{node.state === "done" ? "✓" : node.no}</span>
              <details open={node.state === "today"}>
                <summary>
                  <span className="v2-node-title">第 {node.no} 讲 · {node.title}</span>
                  <span className="v2-node-tag">{node.state === "today" ? "今天" : node.state === "done" ? "学过" : "未学"}</span>
                </summary>
                <ul className="v2-points">{node.points.map((point, index) => <li key={index}>{point}</li>)}</ul>
                {node.learned && onReview && (
                  <button type="button" className="v2-link" onClick={() => onReview(node.no)}>再看一遍讲解</button>
                )}
              </details>
            </li>
            {node.checkpoint && (
              <li className={`v2-gate ${node.checkpoint.status}`}>
                <span className="v2-dot" aria-hidden="true">★</span>
                <span>
                  阶段 {node.checkpoint.stage_no} 测验 ·{" "}
                  {node.checkpoint.status === "done" ? `${node.checkpoint.score ?? 0} 分` : node.checkpoint.status === "ready" ? "可以考了，在今天的考试里" : "学完这一段再考"}
                </span>
              </li>
            )}
          </Fragment>
        ))}
      </ol>
      {nodes.length > shown.length || all ? (
        <button type="button" className="v2-link" onClick={() => setAll((v) => !v)}>{all ? "收起" : `看全部 ${nodes.length} 讲`}</button>
      ) : null}
    </section>
  );
}
