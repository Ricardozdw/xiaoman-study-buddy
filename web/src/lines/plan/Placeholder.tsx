import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { Badge, Bubble } from "../../components/ui";
import { DemoClockPanel } from "./DemoClockPanel";
import { GoalSetup } from "./GoalSetup";
import { changesLeftColumn, type Answers } from "./logic";
import { PlanCardView } from "./PlanCardView";
import type { DemoClock, GoalQuestion, Opening, PlanCard, PlanOption, PlanTodayExt } from "./types";

// 计划线面板：小满开场、定目标、当前这张卡（目标拆解 / 建议 / 重排）、撤销、收工卡、快捷回复、演示开关。
// A 统一挂载（11-06）：inChat 时挂在对话流开头，开场白用小满气泡；还没定目标时直接开始问目标。
// 演示开关只在开发模式（showDemo）显示。
// 改到左栏的操作（生效、撤销、跳日期）做完刷新整页，因为左栏归共用的 Shell 管。

type Props = { inChat?: boolean; showDemo?: boolean };

export function PlanLine({ inChat = false, showDemo = true }: Props = {}) {
  const [plan, setPlan] = useState<PlanTodayExt | null>(null);
  const [opening, setOpening] = useState<Opening | null>(null);
  const [questions, setQuestions] = useState<GoalQuestion[]>([]);
  const [asking, setAsking] = useState(false);
  const [clock, setClock] = useState<DemoClock | null>(null);
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState("");

  const load = useCallback(async () => {
    const [planRes, openRes, clockRes] = await Promise.all([
      api<PlanTodayExt>("/api/plan/today"),
      api<Opening>("/api/plan/opening"),
      api<DemoClock>("/api/demo/clock"),
    ]);
    if (planRes.source !== "api") return; // 后端没接上时不显示计划线面板
    const today = planRes.envelope.data;
    setPlan(today);
    if (openRes.source === "api") setOpening(openRes.envelope.data);
    if (clockRes.source === "api") setClock(clockRes.envelope.data);
    // 在对话里：还没定目标、也没有待处理的卡时，直接开始问目标（一次一题，可以跳过）。
    if (inChat && today.needs_setup && !today.card) {
      const res = await api<{ questions: GoalQuestion[] }>("/api/goals/questions");
      if (res.source === "api" && res.envelope.data.questions.length) {
        setQuestions(res.envelope.data.questions);
        setAsking(true);
      }
    }
  }, [inChat]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: Parameters<typeof changesLeftColumn>[0], path: string, body?: unknown) {
    if (busy) return;
    setBusy(true);
    setReply("");
    const result = await api<{ message?: string; reply?: string; card?: PlanCard | null }>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = result.envelope.data;
    if (result.source === "api" && result.envelope.ok !== false && changesLeftColumn(action)) {
      window.location.reload();
      return;
    }
    if (data?.message) setReply(data.message);
    if (data?.reply) setReply(data.reply);
    await load();
    setBusy(false);
  }

  async function startSetup() {
    const res = await api<{ questions: GoalQuestion[] }>("/api/goals/questions");
    if (res.source === "api") {
      setQuestions(res.envelope.data.questions);
      setAsking(true);
    }
  }

  async function step(path: string, body?: unknown) {
    setBusy(true);
    const res = await api(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
    if (res.source === "api") window.location.reload();
    else setBusy(false);
  }

  if (!plan) {
    return inChat ? null : <p className="line-placeholder">计划线：后端没接上时这里不显示。</p>;
  }
  const card = plan.card;

  return (
    <section aria-label="计划线">
      {opening && (inChat ? (
        <Bubble role="xiaoman">
          {opening.label && <><Badge sim={opening.label === "模拟"}>{opening.label}</Badge><br /></>}
          {opening.greeting}
        </Bubble>
      ) : (
        <p className="line-placeholder">
          <span className="badge">{opening.label}</span> 小满：{opening.greeting}
        </p>
      ))}

      {card ? (
        <PlanCardView
          card={card}
          busy={busy}
          onPick={(option: PlanOption, examDate?: string) =>
            void run("accept", `/api/suggestions/${card.id}/accept`, { option: option.id, exam_date: examDate })
          }
          onDecline={() => void run("dismiss", `/api/suggestions/${card.id}/dismiss`)}
          onRevise={card.kind === "goal_setup" ? (text) => void run("revise", `/api/goals/draft/${card.id}/revise`, { text }) : undefined}
        />
      ) : asking && questions.length ? (
        <GoalSetup
          questions={questions}
          busy={busy}
          onDone={(answers: Answers) => {
            setAsking(false);
            void run("draft", "/api/goals/draft", answers);
          }}
        />
      ) : null}

      {plan.undoable && !card && (
        <div className="card collapsed">
          <p>{plan.undoable.text}</p>
          <button type="button" className="btn" disabled={busy} onClick={() => void run("undo", `/api/actions/${plan.undoable!.id}/undo`)}>
            撤销
          </button>
        </div>
      )}

      {plan.done_card && !card && (
        <article className="card" aria-label="收工">
          <header>
            <h3>{plan.done_card.title}</h3>
            <span className="badge sim">{plan.done_card.badge}</span>
            <span className="aux">收工</span>
          </header>
          <ul>
            {plan.done_card.lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </article>
      )}

      {reply && <p className="aux">{reply}</p>}

      {!card && !asking && plan.quick_replies.length > 0 && (
        <div className="btns" aria-label="快捷回复">
          {plan.quick_replies.map((item) => (
            <button
              key={item.text}
              type="button"
              className="btn"
              disabled={busy || item.action === "start_task" || item.action === "tomorrow" || item.action === "dashboard"}
              onClick={() => {
                if (item.action === "goal_setup") void startSetup();
                if (item.action === "adjust") void run("adjust", "/api/plan/adjust", { text: item.text });
              }}
            >
              {item.text}
            </button>
          ))}
        </div>
      )}

      {showDemo && clock?.enabled && (
        <DemoClockPanel
          clock={clock}
          busy={busy}
          onStep={(days) => void step("/api/demo/clock", { days })}
          onReset={() => void step("/api/demo/clock/reset")}
        />
      )}
    </section>
  );
}
