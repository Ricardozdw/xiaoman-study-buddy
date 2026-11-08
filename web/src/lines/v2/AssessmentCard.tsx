import { Badge, Button, Card } from "../../components/ui";
import type { Quiz, StageView } from "./api";
import { ASSESSMENT_INVITE, GENERIC_QUESTION_BADGE } from "./cards";

type InviteProps = {
  mode: "invite";
  stage: StageView | null;
  busy: boolean;
  error: string;
  onStart: () => void;
  onLater: () => void;
};

type QuizProps = {
  mode: "quiz";
  quiz: Quiz;
  index: number;
  answers: Record<string, string>;
  busy: boolean;
  error: string;
  warn: string;
  canForce: boolean;
  onPick: (questionId: string, optionId: string) => void;
  onPrev: () => void;
  onNext: () => void;
  onSubmit: () => void;
  onForce: () => void;
  intro?: string;
};

export function AssessmentCard(props: InviteProps | QuizProps) {
  if (props.mode === "invite") {
    return (
      <Card aria-label="阶段测验" data-v2-card="assessment">
        <header>
          <h3>{ASSESSMENT_INVITE}</h3>
          {props.stage?.title && <span className="aux">{props.stage.title}</span>}
        </header>
        <p>做完大概 15 分钟。它占今天三件里的一件，不加件数。</p>
        <div className="btns">
          <Button disabled={props.busy} onClick={props.onLater}>晚点再考</Button>
          <Button variant="primary" disabled={props.busy} onClick={props.onStart}>开始</Button>
        </div>
        {props.error && <p role="alert">{props.error}</p>}
      </Card>
    );
  }

  const question = props.quiz.questions[props.index];
  const last = props.index >= props.quiz.questions.length - 1;
  if (!question) return null;
  return (
    <Card aria-label="阶段测验" data-v2-card="assessment" className="exam-card card-read">
      <header className="lecture-head">
        <div className="head-meta">
          <span>
            {props.quiz.stage?.title || "阶段测验"} · {GENERIC_QUESTION_BADGE}
            {props.quiz.label === "模拟" && <> <Badge sim>模拟</Badge></>}
          </span>
          <span className="head-count">第 {props.index + 1} / {props.quiz.questions.length} 题</span>
        </div>
        <h3>{question.stem}</h3>
        <div className="quiz-progress" aria-hidden="true"><span style={{ width: `${(Object.keys(props.answers).filter((id) => props.answers[id]).length / props.quiz.questions.length) * 100}%` }} /></div>
        {props.index === 0 && props.intro && <p className="aux head-note">{props.intro}。</p>}
      </header>
      <div className="options">
        {question.options.map((option) => (
          <Button
            key={option.id}
            className={`option ${props.answers[question.id] === option.id ? "picked" : ""}`}
            aria-pressed={props.answers[question.id] === option.id}
            disabled={props.busy}
            onClick={() => props.onPick(question.id, option.id)}
          >
            <span className="option-key">{option.id}</span>{option.text}
          </Button>
        ))}
      </div>
      <p className="aux">考试不当场对答案，交卷后一起看。</p>
      <div className="btns">
        <Button disabled={props.busy || props.index === 0} onClick={props.onPrev}>上一题</Button>
        {last ? <Button variant="primary" disabled={props.busy} onClick={props.onSubmit}>交卷</Button> : <Button variant={props.answers[question.id] ? "primary" : "secondary"} disabled={props.busy} onClick={props.onNext}>下一题</Button>}
        {last && props.canForce && <Button disabled={props.busy} onClick={props.onForce}>仍然交卷</Button>}
      </div>
      {props.warn && <p role="status">{props.warn}</p>}
      {props.error && <p role="alert">{props.error}</p>}
    </Card>
  );
}
