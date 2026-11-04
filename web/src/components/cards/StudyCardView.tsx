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
      <div className="card collapsed">
        <p>{card.collapsedText}</p>
        <button type="button" className="btn" onClick={() => onReopen(card.id)}>
          展开
        </button>
      </div>
    );
  }
  return (
    <article className="card" aria-label={CARD_LABEL[card.type]}>
      <header>
        <h3>{card.title}</h3>
        <span className={card.badge === "模拟" ? "badge sim" : "badge"}>{card.badge}</span>
        <span className="aux">{CARD_LABEL[card.type]}</span>
      </header>
      <ul>
        {card.lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <div className="btns">
        {card.type === "summary" && (
          <button type="button" className="btn primary" onClick={() => onOpenWorkbench("note")}>
            打开全文
          </button>
        )}
        {card.type === "progress" && (
          <button type="button" className="btn" onClick={() => onOpenWorkbench("page")}>
            看原文
          </button>
        )}
        {card.type === "done" && (
          <button type="button" className="btn primary" onClick={() => onOpenWorkbench("board")}>
            看看板
          </button>
        )}
        <button type="button" className="btn primary" onClick={() => onDone(card.id)}>
          {card.type === "suggestion" ? "就这样" : card.type === "reschedule" ? "选这个" : "好"}
        </button>
        <button type="button" className="btn" onClick={() => onDone(card.id)}>
          先不用
        </button>
      </div>
    </article>
  );
}
