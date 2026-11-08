import { useEffect, useRef, useState } from "react";
import { Bubble, Button, Card } from "../../components/ui";
import { acceptOutline, draftOutline, getPlanDate, patchOutline, undoOutline, type OutlineView, type UnitInput } from "./api";
import {
  ACCEPT_STORAGE_KEY,
  CONFIRM_SENTENCE,
  QUESTIONS,
  V2_OPENING,
  acceptanceNotice,
  applyAnswer,
  buildDraft,
  defaultNotes,
  goalNamePrompt,
  initialGoalState,
  isIsoDate,
  stepProgress,
  summaryLines,
  type AcceptedOutline,
  type AnswerInput,
  type GoalState,
} from "./logic";
import { OutlineCard } from "./OutlineCard";

type Line = { id: string; role: "user" | "xiaoman"; text: string };

function readStored(): AcceptedOutline | null {
  try {
    const raw = sessionStorage.getItem(ACCEPT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<AcceptedOutline>;
    if (typeof parsed.id === "string" && typeof parsed.day === "string") return { id: parsed.id, day: parsed.day };
  } catch {
    // 读不到就不当成已确认。
  }
  return null;
}

export function rememberAcceptance(id: string, day: string) {
  try {
    sessionStorage.setItem(ACCEPT_STORAGE_KEY, JSON.stringify({ id, day }));
  } catch {
    // 浏览器不让写时，刷新后撤销按钮会消失；当天仍可重新确认。
  }
}

function forgetAcceptance() {
  try {
    sessionStorage.removeItem(ACCEPT_STORAGE_KEY);
  } catch {
    // 清不掉时，刷新后若日期仍是当天，撤销按钮还在，点了会再试。
  }
}

export function AcceptedOutlineBar({ today }: { today: string }) {
  const [item, setItem] = useState(() => acceptanceNotice(readStored(), today));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { setItem(acceptanceNotice(readStored(), today)); }, [today]);
  if (!item) return null;
  const notice = item;

  async function undo() {
    setBusy(true);
    setError("");
    const result = await undoOutline(notice.id);
    if (!result.ok) {
      setError(result.message);
      setBusy(false);
      return;
    }
    forgetAcceptance();
    window.location.reload();
  }

  return (
    <section aria-label="大纲已生效">
      <Card collapsed>
        <p>{notice.text}</p>
        <Button disabled={busy} onClick={() => void undo()}>撤销</Button>
      </Card>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

export function GoalFlowV2({ today: todayFromPlan }: { today: string }) {
  const [today, setToday] = useState(isIsoDate(todayFromPlan) ? todayFromPlan : "");
  const [state, setState] = useState<GoalState>(initialGoalState);
  const [history, setHistory] = useState<Line[]>([]);
  const [text, setText] = useState("");
  const [dateText, setDateText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [outline, setOutline] = useState<OutlineView | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const rootRef = useRef<HTMLElement>(null);
  const seq = useRef(0);

  useEffect(() => {
    let cancelled = false;
    void getPlanDate().then((date) => { if (!cancelled && date) setToday(date); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    rootRef.current?.querySelector("[data-v2-current]")?.scrollIntoView({ block: "nearest" });
  }, [state.step, outline, dismissed]);

  function push(role: Line["role"], line: string) {
    seq.current += 1;
    setHistory((list) => [...list, { id: `v2-${seq.current}`, role, text: line }]);
  }

  function choose(input: AnswerInput) {
    const result = applyAnswer(state, input, today);
    if (result.error) {
      setError(result.error);
      return;
    }
    const reply = input.type === "skip" ? "先跳过" : input.type === "date" ? input.date : input.type === "quick" ? input.label : input.text.trim();
    push("user", reply);
    if (result.notice) push("xiaoman", result.notice);
    setError("");
    setText("");
    setDateText("");
    setState(result.state);
  }

  async function submit() {
    const body = buildDraft(state);
    if (!body) {
      setError("还没答完，先把这一题定下来。");
      return;
    }
    setBusy(true);
    setError("");
    const result = await draftOutline(body);
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setOutline(result.outline);
  }

  async function patch(units: UnitInput[]) {
    if (!outline) return false;
    setBusy(true);
    setError("");
    const result = await patchOutline(outline.id, units);
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return false;
    }
    setOutline(result.outline);
    return true;
  }

  async function accept() {
    if (!outline) return;
    setBusy(true);
    setError("");
    const result = await acceptOutline(outline.id);
    if (!result.ok) {
      setError(result.message);
      setBusy(false);
      return;
    }
    const day = (await getPlanDate()) || today;
    rememberAcceptance(result.outline.id, day);
    window.location.reload();
  }

  const progress = stepProgress(state);
  const notes = state.step === "confirm" ? defaultNotes(state) : [];

  return (
    <section aria-label="计划线" className="v2-flow" ref={rootRef}>
      <Bubble role="xiaoman">{V2_OPENING}</Bubble>
      {history.map((line, index) => (
        <Bubble key={line.id} role={line.role} grouped={index > 0 && history[index - 1].role === line.role}>{line.text}</Bubble>
      ))}
      {dismissed && (
        <div data-v2-current>
          <Bubble role="xiaoman">先不用这份大纲，今天的安排没有变。</Bubble>
          <div className="btns"><Button onClick={() => setDismissed(false)}>再看看</Button></div>
        </div>
      )}
      {!dismissed && outline && (
        <div data-v2-current>
          <OutlineCard outline={outline} busy={busy} error={error} onPatch={patch} onAccept={() => void accept()} onDismiss={() => setDismissed(true)} />
        </div>
      )}
      {!dismissed && !outline && state.step === "confirm" && (
        <div data-v2-current>
          <Bubble role="xiaoman">按这些生成学习大纲？</Bubble>
          <Card aria-label="确认目标">
            <ul>{summaryLines(state).map((line) => <li key={line.label}>{line.label}：{line.value}</li>)}</ul>
            {notes.length > 0 && <p>{CONFIRM_SENTENCE}</p>}
            {notes.length > 0 && <ul>{notes.map((note) => <li key={note}>{note}</li>)}</ul>}
            <div className="btns">
              <Button variant="primary" disabled={busy} onClick={() => void submit()}>好，生成大纲</Button>
            </div>
            {error && <p role="alert">{error}</p>}
          </Card>
        </div>
      )}
      {!dismissed && !outline && state.step !== "confirm" && (
        <Question
          state={state}
          progress={progress}
          text={text}
          dateText={dateText}
          error={error}
          busy={busy}
          onText={setText}
          onDate={setDateText}
          onChoose={choose}
        />
      )}
    </section>
  );
}

function Question({ state, progress, text, dateText, error, busy, onText, onDate, onChoose }: {
  state: GoalState;
  progress: { current: number; total: number };
  text: string;
  dateText: string;
  error: string;
  busy: boolean;
  onText: (value: string) => void;
  onDate: (value: string) => void;
  onChoose: (input: AnswerInput) => void;
}) {
  if (state.step === "confirm") return null;
  if (state.step === "goalName") {
    const prompt = goalNamePrompt(state.goalType);
    return (
      <div data-v2-current>
        <Bubble role="xiaoman">{prompt}</Bubble>
        <Card aria-label="具体名称">
          <header><span className="aux">{progress.current} / {progress.total}</span></header>
          <div className="btns">
            <Button disabled={busy} onClick={() => onChoose({ type: "skip" })}>先跳过</Button>
          </div>
          <form onSubmit={(event) => { event.preventDefault(); onChoose({ type: "text", text }); }}>
            <div className="v2-field">
              <input aria-label={prompt} value={text} disabled={busy} placeholder="写下具体名称" onChange={(event) => onText(event.target.value)} />
              <Button type="submit" variant="primary" disabled={busy || !text.trim()}>好</Button>
            </div>
          </form>
          {error && <p role="alert">{error}</p>}
        </Card>
      </div>
    );
  }
  const question = QUESTIONS[state.step];
  return (
    <div data-v2-current>
      <Bubble role="xiaoman">{question.text}</Bubble>
      <Card aria-label="定目标">
        <header><span className="aux">{progress.current} / {progress.total}</span></header>
        <div className="btns">
          {question.quick.map((label) => (
            <Button key={label} disabled={busy} onClick={() => onChoose({ type: "quick", label })}>{label}</Button>
          ))}
          <Button disabled={busy} onClick={() => onChoose({ type: "skip" })}>先跳过</Button>
        </div>
        {state.step === "deadline" ? (
          <div className="v2-field">
            <label>
              具体日期
              <input type="date" aria-label="具体日期" value={dateText} disabled={busy} onChange={(event) => onDate(event.target.value)} />
            </label>
            <Button disabled={busy} onClick={() => onChoose({ type: "date", date: dateText })}>就选这一天</Button>
          </div>
        ) : (
          <form onSubmit={(event) => { event.preventDefault(); onChoose({ type: "text", text }); }}>
            <div className="v2-field">
              <input aria-label={question.text} value={text} disabled={busy} placeholder="也可以自己说" onChange={(event) => onText(event.target.value)} />
              <Button type="submit" variant="primary" disabled={busy || !text.trim()}>好</Button>
            </div>
          </form>
        )}
        {error && <p role="alert">{error}</p>}
      </Card>
    </div>
  );
}
