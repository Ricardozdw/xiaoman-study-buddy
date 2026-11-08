import { useEffect, useState } from "react";
import { Button, Card } from "../../components/ui";
import { answerRedo, getMistakes, redoMistake, type MistakeBook, type MistakeItem, type QuizQuestion } from "./api";

/** V2.2 错题本：随时翻看还没做对的题；再做一次会换个问法，做对了自动移出。 */
export function MistakeBookCard({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const [book, setBook] = useState<MistakeBook | null>(null);
  const [error, setError] = useState("");

  async function load() {
    const data = await getMistakes();
    if (!data) setError("错题本没读到，请稍后再试。");
    setBook(data);
  }
  useEffect(() => { void load(); }, []);

  return (
    <Card as="section" aria-label="错题本" data-v2-card="mistakes" className="card-read">
      <header>
        <h3>错题本</h3>
        {book && <span className="aux">还有 {book.count} 题没做对</span>}
      </header>
      {!book && !error && <p role="status" className="aux">正在翻错题本…</p>}
      {error && <p role="alert">{error}</p>}
      {book && book.count === 0 && <p>现在没有错题。做错的题会自动收进来，做对了就移出。</p>}
      {book?.groups.map((group) => (
        <section key={group.lecture_no} className="v2-mistake-group">
          <h4>第 {group.lecture_no} 讲{group.title ? ` · ${group.title}` : ""}</h4>
          {group.items.map((item) => (
            <MistakeRow key={item.question_id} item={item} onSolved={() => { void load(); onChanged(); }} />
          ))}
        </section>
      ))}
      <div className="btns"><Button onClick={onClose}>收起</Button></div>
    </Card>
  );
}

function MistakeRow({ item, onSolved }: { item: MistakeItem; onSolved: () => void }) {
  const [redo, setRedo] = useState<{ quizId: string; question: QuizQuestion } | null>(null);
  const [result, setResult] = useState<{ correct: boolean; analysis: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function start() {
    setBusy(true); setError("");
    const res = await redoMistake(item.question_id);
    setBusy(false);
    if (!res.ok) { setError(res.message); return; }
    setRedo({ quizId: res.quiz.quiz_id, question: res.quiz.questions[0] });
  }
  async function pick(optionId: string) {
    if (!redo) return;
    setBusy(true); setError("");
    const res = await answerRedo(redo.quizId, redo.question.id, optionId);
    setBusy(false);
    if (!res.ok) { setError(res.message); return; }
    setResult({ correct: res.result.correct, analysis: res.result.analysis });
  }

  return (
    <div className="v2-mistake">
      <p className="v2-mistake-stem">{item.stem}</p>
      <p className="aux">我的答案：{item.your_answer}{item.your_answer_text ? `. ${item.your_answer_text}` : ""} · 正确答案：{item.answer}{item.answer_text ? `. ${item.answer_text}` : ""}</p>
      {item.analysis && <p className="aux">解析：{item.analysis}</p>}
      {!redo && <div className="btns"><Button disabled={busy} onClick={() => void start()}>{busy ? "正在换个问法…" : "再做一次"}</Button></div>}
      {redo && !result && (
        <div className="v2-redo">
          <p>换个问法：{redo.question.stem}</p>
          <div className="v2-options">
            {redo.question.options.map((option) => (
              <Button key={option.id} className="option" disabled={busy} onClick={() => void pick(option.id)}>{option.id}. {option.text}</Button>
            ))}
          </div>
        </div>
      )}
      {result && (
        <div className="v2-redo">
          <p role="status">{result.correct ? "答对了，这题从错题本里移出。" : "还没对，没关系，它会留在错题本里，明天的考试也会再出现。"}</p>
          {result.analysis && <p className="aux">{result.analysis}</p>}
          <div className="btns"><Button variant="primary" onClick={onSolved}>好</Button></div>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
