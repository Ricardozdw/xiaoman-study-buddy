import { useState } from "react";
import { cardLabel, isPrimary } from "./logic";
import type { PlanCard, PlanOption } from "./types";

// 计划线的卡：目标拆解 / 建议 / 重排。点了才生效；一次只有一张。
// 只用地基给的样式类（card、btns、btn、badge、aux、composer）。

type Props = {
  card: PlanCard;
  busy: boolean;
  onPick: (option: PlanOption, examDate?: string) => void;
  onDecline: () => void;
  onRevise?: (text: string) => void;
};

export function PlanCardView({ card, busy, onPick, onDecline, onRevise }: Props) {
  const [asking, setAsking] = useState<"exam_date" | "revise" | null>(null);
  const [text, setText] = useState("");
  const dateOption = card.options.find((option) => option.needs === "exam_date");

  return (
    <article className="card" aria-label={cardLabel(card)}>
      <header>
        <h3>{card.title}</h3>
        <span className={card.badge === "模拟" ? "badge sim" : "badge"}>{card.badge}</span>
        <span className="aux">{cardLabel(card)}</span>
      </header>
      <ul>
        {card.lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {asking ? (
        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault();
            if (!text.trim()) return;
            if (asking === "exam_date" && dateOption) onPick(dateOption, text.trim());
            if (asking === "revise" && onRevise) onRevise(text.trim());
            setText("");
            setAsking(null);
          }}
        >
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            type={asking === "exam_date" ? "date" : "text"}
            placeholder={asking === "revise" ? "比如：考试改到 12 月 20 日" : ""}
            aria-label={asking === "revise" ? "说说怎么改" : "新的考试日期"}
          />
          <button type="submit" className="btn primary" disabled={busy}>
            确定
          </button>
          <button type="button" className="btn" onClick={() => setAsking(null)}>
            取消
          </button>
        </form>
      ) : (
        <div className="btns">
          {card.options.map((option) => (
            <button
              key={option.id}
              type="button"
              className={isPrimary(card, option) ? "btn primary" : "btn"}
              disabled={busy}
              onClick={() => (option.needs === "exam_date" ? setAsking("exam_date") : onPick(option))}
            >
              {option.label}
            </button>
          ))}
          {card.revise_label && onRevise && (
            <button type="button" className="btn" disabled={busy} onClick={() => setAsking("revise")}>
              {card.revise_label}
            </button>
          )}
          <button type="button" className="btn" disabled={busy} onClick={onDecline}>
            {card.decline_label || "先不用"}
          </button>
        </div>
      )}
    </article>
  );
}
