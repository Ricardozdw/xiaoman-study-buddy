import { Badge, Button, Card } from "../../components/ui";
import type { AssessmentReport } from "./api";
import { unitScoreLine, weakLine } from "./cards";

type Props = { report: AssessmentReport; label: string; onOk: () => void };

export function ReportCard({ report, label, onOk }: Props) {
  const weak = weakLine(report.weak_unit_nos);
  return (
    <Card aria-label="成绩报告" data-v2-card="report" className="card-read">
      <header>
        <h3>这一阶段的成绩</h3>
        {label && <Badge sim={label === "模拟"}>{label}</Badge>}
      </header>
      <p className="v2-score">{report.score} 分</p>
      <ul className="v2-lines">
        {report.units.map((unit) => (
          <li key={unit.no}><span>{unit.title}</span><span>{unitScoreLine(unit)}</span></li>
        ))}
      </ul>
      {weak && <p>{weak}</p>}
      <p>{report.summary}</p>
      <div className="btns">
        <Button variant="primary" onClick={onOk}>好的</Button>
      </div>
    </Card>
  );
}
