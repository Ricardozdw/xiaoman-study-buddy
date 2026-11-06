import { useState } from "react";
import { answer, nextQuestion, type Answers } from "./logic";
import type { GoalQuestion } from "./types";

// 第一次见面：一次问一题，每题有快捷回复，也能自己输入或跳过。问完交给后端出目标拆解卡。

type Props = { questions: GoalQuestion[]; busy: boolean; onDone: (answers: Answers) => void };

export function GoalSetup({ questions, busy, onDone }: Props) {
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Answers>({});
  const [text, setText] = useState("");
  const question = nextQuestion(questions, index);

  function reply(value: string | null) {
    if (!question) return;
    const next = answer(answers, question.key, value);
    setAnswers(next);
    setText("");
    if (index + 1 >= questions.length) onDone(next);
    else setIndex(index + 1);
  }

  if (!question) return null;
  return (
    <article className="card" aria-label="定目标">
      <header>
        <h3>{question.text}</h3>
        <span className="aux">
          {index + 1} / {questions.length}
        </span>
      </header>
      <div className="btns">
        {question.quick_replies.map((item) => (
          <button key={item} type="button" className="btn" disabled={busy} onClick={() => reply(item)}>
            {item}
          </button>
        ))}
        <button type="button" className="btn" disabled={busy} onClick={() => reply(null)}>
          {question.skip_label}
        </button>
      </div>
      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          if (text.trim()) reply(text);
        }}
      >
        <input value={text} onChange={(event) => setText(event.target.value)} placeholder="也可以自己说" aria-label={question.text} />
        <button type="submit" className="btn primary" disabled={busy || !text.trim()}>
          好
        </button>
      </form>
      <p className="aux">跳过的话：{question.default_text}</p>
    </article>
  );
}
