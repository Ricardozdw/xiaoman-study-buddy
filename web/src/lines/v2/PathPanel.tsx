import { Fragment, useState } from "react";
import { Button, Icon } from "../../components/ui";
import type { OutlineView } from "./api";
import { pathNodes } from "./logic";

/** 左栏只放一行入口：进度条 + 下一站，点开看完整路径。 */
export function PathEntry({ outline, onOpen }: { outline: OutlineView; onOpen: () => void }) {
  const total = outline.units.length;
  const learned = Math.min(outline.learned_up_to ?? 0, total);
  const next = outline.units[learned];
  return (
    <section className="rail-section" aria-label="学习路径">
      <button type="button" className="path-entry" onClick={onOpen}>
        <span className="path-entry-top">学习路径<Icon name="chevron" /></span>
        <span className="aux">{outline.title} · 学了 {learned} / {total} 讲</span>
        <span className="path-meter" aria-hidden="true"><span style={{ width: `${total ? (learned / total) * 100 : 0}%` }} /></span>
        <span className="aux">{next ? `下一站：第 ${next.no ?? learned + 1} 讲` : "全部学完了"}</span>
      </button>
    </section>
  );
}

/**
 * 完整学习路径（右侧面板；手机上全屏）：学过的打勾可重看，今天这一讲高亮并展开要点，
 * 没学的只显示标题、点开看要点（不能跳讲），阶段测验是路上的星标关卡。
 */
export function PathPanel({ outline, currentNo, onReview, onContinue }: {
  outline: OutlineView;
  currentNo: number | null;
  onReview: (unitNo: number) => void;
  onContinue: () => void;
}) {
  const nodes = pathNodes(outline, currentNo);
  const [open, setOpen] = useState<number | null>(null);
  const learned = Math.min(outline.learned_up_to ?? 0, outline.units.length);
  return (
    <section aria-label="完整学习路径">
      <p className="aux">{outline.title} · 学了 {learned} / {outline.units.length} 讲</p>
      <ol className="path-map">
        {nodes.map((node) => {
          // 今天这一讲已经学完：按“学过”展示（重看），不再显示“继续学”。
          const todayOpen = node.state === "today" && !node.learned;
          const expanded = todayOpen || open === node.no;
          return (
            <Fragment key={node.no}>
              <li className={node.state === "today" && node.learned ? "done" : node.state}>
                <span className="path-dot" aria-hidden="true">{node.learned ? "✓" : node.no}</span>
                <div className="path-body">
                  <button type="button" className="path-title" aria-expanded={expanded} onClick={() => setOpen(open === node.no ? null : node.no)}>
                    <strong>第 {node.no} 讲 · {node.title}</strong>
                    <span className="path-tag">{node.state === "today" ? (node.learned ? "今天学过" : "今天") : node.state === "done" ? "学过" : "未学"}</span>
                  </button>
                  {expanded && <ul className="path-points">{node.points.map((point, index) => <li key={index}>{point}</li>)}</ul>}
                  {todayOpen && <div className="btns"><Button variant="primary" onClick={onContinue}>继续学</Button></div>}
                  {node.learned && <div className="btns"><Button onClick={() => onReview(node.no)}>重看</Button></div>}
                </div>
              </li>
              {node.checkpoint && (
                <li className={`gate ${node.checkpoint.status === "done" ? "done" : ""}`}>
                  <span className="path-dot" aria-hidden="true">★</span>
                  <div className="path-gate-text">
                    阶段 {node.checkpoint.stage_no} 测验 ·{" "}
                    {node.checkpoint.status === "done" ? `${node.checkpoint.score ?? 0} 分` : node.checkpoint.status === "ready" ? "可以考了，在今天的考试里" : "学完这一段再考"}
                  </div>
                </li>
              )}
            </Fragment>
          );
        })}
      </ol>
    </section>
  );
}
