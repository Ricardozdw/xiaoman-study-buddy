import { useState } from "react";
import { Badge, Button, Card } from "../../components/ui";
import type { CompletionCard as CompletionStats } from "./api";
import { COMPLETION_SUGGEST, NEXT_GOAL_HINT, scoreSpan } from "./cards";

type SuggestProps = {
  mode: "suggest";
  userSaid: boolean;
  busy: boolean;
  error: string;
  onComplete: () => void;
  onLater: () => void;
};

type DoneProps = {
  mode: "done";
  card: CompletionStats;
  busy: boolean;
  error: string;
  onUndo: () => void;
  onRest: () => void;
};

export function CompletionCard(props: SuggestProps | DoneProps) {
  const [hint, setHint] = useState(false);
  if (props.mode === "suggest") {
    return (
      <Card aria-label="完成建议" data-v2-card="suggest">
        <header><h3>{COMPLETION_SUGGEST}</h3></header>
        <p>{props.userSaid ? "你说学完了。点了完成，这个目标才算收尾。" : "学过的单元都勾完了，最近一次阶段测验也到了线。点了完成，这个目标才算收尾。"}</p>
        <div className="btns">
          <Button disabled={props.busy} onClick={props.onLater}>再学一阵</Button>
          <Button variant="primary" disabled={props.busy} onClick={props.onComplete}>完成目标</Button>
        </div>
        {props.error && <p role="alert">{props.error}</p>}
      </Card>
    );
  }

  const { card } = props;
  return (
    <Card aria-label="目标完成" data-v2-card="done">
      <header>
        <h3>这个目标完成了</h3>
        {card.label && <Badge sim={card.label === "模拟"}>{card.label}</Badge>}
      </header>
      <ul>
        <li>学了 {card.days} 天</li>
        <li>做了 {card.attempts} 题</li>
        <li>{scoreSpan(card)}</li>
        {card.hardest_unit ? <li>最难的单元：{card.hardest_unit}</li> : null}
      </ul>
      <p className="aux">学习记录都留着。</p>
      <div className="btns">
        <Button disabled={props.busy} onClick={props.onUndo}>撤销</Button>
        <Button disabled={props.busy} onClick={props.onRest}>先休息一阵</Button>
        <Button variant="primary" disabled={props.busy} onClick={() => setHint(true)}>定下一个目标</Button>
      </div>
      {hint && <p role="status">{NEXT_GOAL_HINT}</p>}
      {props.error && <p role="alert">{props.error}</p>}
    </Card>
  );
}
