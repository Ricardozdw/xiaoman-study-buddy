import type { OutlineView } from "./api";

/** 块4：确认后的大纲留在左栏，随时可看；正在学的单元默认展开。 */
export function OutlineRail({ outline, currentNo }: { outline: OutlineView; currentNo: number | null }) {
  return (
    <section className="rail-section" aria-label="学习大纲">
      <h2>学习大纲</h2>
      <p className="aux">{outline.title} · 共 {outline.units.length} 讲 · 通用知识，没有出处</p>
      <ul className="v2-units">
        {outline.units.map((unit, index) => {
          const no = unit.no ?? index + 1;
          const current = no === currentNo;
          return (
            <li key={no}>
              <details className="v2-unit" open={current}>
                <summary>第 {no} 讲 · {unit.title}{current ? "（正在学）" : ""}</summary>
                <ul className="v2-points">{unit.points.map((point, pointIndex) => <li key={pointIndex}>{point}</li>)}</ul>
              </details>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
