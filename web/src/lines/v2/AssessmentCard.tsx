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
    <Card aria-label="阶段测验" data-v2-card="assessment">
      <header>
        <h3>{props.quiz.stage?.title || "阶段测验"}</h3>
        {props.quiz.label && <Badge sim={props.quiz.label === "模拟"}>{props.quiz.label}</Badge>}
        <Badge>{GENERIC_QUESTION_BADGE}</Badge>
        <span className="aux">第 {props.index + 1} / {props.quiz.questions.length} 题</span>
      </header>
      <p>{question.stem}</p>
      <div className="v2-options">
        {question.options.map((option) => (
          <Button
            key={option.id}
            className="option"
            aria-pressed={props.answers[question.id] === option.id}
            disabled={props.busy}
            onClick={() => props.onPick(question.id, option.id)}
          >
            {option.id}. {option.text}
          </Button>
        ))}
      </div>
      <div className="btns">
        <Button disabled={props.busy || props.index === 0} onClick={props.onPrev}>上一题</Button>
        {last ? <Button variant="primary" disabled={props.busy} onClick={props.onSubmit}>交卷</Button> : <Button disabled={props.busy} onClick={props.onNext}>下一题</Button>}
        {last && props.canForce && <Button disabled={props.busy} onClick={props.onForce}>仍然交卷</Button>}
      </div>
      {props.warn && <p role="status">{props.warn}</p>}
      {props.error && <p role="alert">{props.error}</p>}
    </Card>
  );
}
