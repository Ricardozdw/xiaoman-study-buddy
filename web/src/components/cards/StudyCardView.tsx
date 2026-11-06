import { Badge, Button, Card, Icon } from "../ui";
import type { StudyCard } from "./logic";
import { CARD_LABEL } from "./logic";

type Props = {
  card: StudyCard;
  onDone: (id: string) => void;
  onReopen: (id: string) => void;
  onOpenWorkbench: (tab: "note" | "page" | "board") => void;
};

export function StudyCardView({ card, onDone, onReopen, onOpenWorkbench }: Props) {
  if (card.status === "done") {
    return (
      <Card as="div" collapsed>
        <p>{card.collapsedText}</p>
        <Button onClick={() => onReopen(card.id)}>展开</Button>
      </Card>
    );
  }
  return (
    <Card aria-label={CARD_LABEL[card.type]}>
      <div className="card-meta">
        <span className="card-icon">
          <Icon name="book" />
        </span>
        <span>{CARD_LABEL[card.type]}</span>
        <span className="dot" aria-hidden="true" />
        <Badge sim={card.badge === "模拟"}>{card.badge}</Badge>
      </div>
      <h3>{card.title}</h3>
      <ul>
        {card.lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {/* 次要操作在左，唯一的主操作在最右。 */}
      <div className="btns">
        <Button onClick={() => onDone(card.id)}>先不用</Button>
        {card.type === "summary" && <Button onClick={() => onOpenWorkbench("note")}>打开全文</Button>}
        {card.type === "progress" && <Button onClick={() => onOpenWorkbench("page")}>看原文</Button>}
        {card.type === "done" && <Button onClick={() => onOpenWorkbench("board")}>看看板</Button>}
        <Button variant="primary" onClick={() => onDone(card.id)}>
          {card.type === "suggestion" ? "就这样" : card.type === "reschedule" ? "选这个" : "好"}
        </Button>
      </div>
    </Card>
  );
}
