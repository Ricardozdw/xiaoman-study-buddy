import { useEffect, useState } from "react";
import { api, ensureSession, readStream } from "../api/client";
import { mockDashboard, mockNotes, mockPlan } from "../api/mocks";
import type { Dashboard, Intensity, NoteItem, Permissions, PlanToday } from "../api/types";
import { DashboardLine } from "../lines/dashboard/Placeholder";
import { MaterialsLine } from "../lines/materials/Placeholder";
import { PlanLine } from "../lines/plan/Placeholder";
import { PracticeLine } from "../lines/practice/Placeholder";
import { QaLine } from "../lines/qa/Placeholder";
import { Avatar } from "./Avatar";
import { collapseCard, previewCards, reopenCard, type StudyCard } from "./cards/logic";
import { StudyCardView } from "./cards/StudyCardView";
import { Bubble, Button, Icon, IconButton, TaskArt } from "./ui";

type FontSize = "sm" | "md" | "lg";
type Tab = "note" | "page" | "board";
type Bubble = { id: string; role: "user" | "xiaoman"; text: string };

const INTENSITY: { id: Intensity; label: string }[] = [
  { id: "light", label: "轻松" },
  { id: "normal", label: "正常" },
  { id: "sprint", label: "冲刺" },
];

export function Shell() {
  const [source, setSource] = useState<"loading" | "api" | "mock">("loading");
  const [plan, setPlan] = useState<PlanToday>(mockPlan);
  const [board, setBoard] = useState<Dashboard>(mockDashboard);
  const [note, setNote] = useState<NoteItem>(mockNotes[0]);
  const [pageText, setPageText] = useState(mockNotes[0].content?.points?.join("\n") || "");
  const [cards, setCards] = useState<StudyCard[]>(previewCards);
  const [bubbles, setBubbles] = useState<Bubble[]>([
    { id: "hi", role: "xiaoman", text: "我是小满。今天的三件在左边。下面这七张卡是地基预览，正式使用时一次只请你做一个决定。" },
  ]);
  const [draft, setDraft] = useState("");
  const [lectureId, setLectureId] = useState("lec-6");
  const [tab, setTab] = useState<Tab | null>(null);
  const [rail, setRail] = useState(false);
  const [font, setFont] = useState<FontSize>("md");
  const [busy, setBusy] = useState(false);
  const [permissions, setPermissions] = useState<Permissions | null>(null);

  // 暗色模式暂不做（以后作为换肤加回来），这里只管字号。
  useEffect(() => {
    document.documentElement.dataset.font = font;
  }, [font]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const session = await ensureSession();
      const [planRes, noteRes, boardRes, pageRes, permRes] = await Promise.all([
        api<PlanToday>("/api/plan/today"),
        api<{ items: NoteItem[] }>("/api/notes"),
        api<Dashboard>("/api/dashboard?range=week"),
        api<{ pages: { page: number; text: string }[] }>(`/api/lectures/${lectureId}/pages`),
        api<Permissions>("/api/me/permissions"),
      ]);
      if (cancelled) return;
      const fromApi = session && [planRes, noteRes, boardRes, pageRes, permRes].every((item) => item.source === "api");
      setSource(fromApi ? "api" : "mock");
      setPlan(planRes.envelope.data);
      const first = noteRes.envelope.data.items?.[0];
      if (first) {
        const detail = await api<NoteItem>(`/api/notes/${first.id}`);
        if (!cancelled) setNote(detail.envelope.data.content ? detail.envelope.data : { ...detail.envelope.data, content: first.content });
      }
      setBoard(boardRes.envelope.data);
      setPermissions(permRes.envelope.data);
      const pages = pageRes.envelope.data.pages || [];
      if (pages.length) setPageText(pages.map((item) => `【第 ${item.page} 页】${item.text}`).join("\n\n"));
    })();
    return () => {
      cancelled = true;
    };
  }, [lectureId]);

  async function changeIntensity(intensity: Intensity) {
    const total = intensity === "light" ? 15 : intensity === "sprint" ? 50 : 30;
    const result = await api<PlanToday>("/api/plan/today", { method: "PATCH", body: JSON.stringify({ intensity }) });
    if (result.source === "api") setPlan(result.envelope.data);
    else {
      const share = Math.floor(total / Math.max(plan.tasks.length, 1));
      setPlan({
        ...plan,
        intensity,
        intensity_label: INTENSITY.find((item) => item.id === intensity)?.label || intensity,
        minutes: total,
        tasks: plan.tasks.map((task) => ({ ...task, minutes: share })),
      });
    }
  }

  async function toggleTask(id: string, status: "todo" | "done") {
    const next = status === "done" ? "todo" : "done";
    const result = await api<{ status: string }>(`/api/tasks/${id}`, { method: "PATCH", body: JSON.stringify({ status: next }) });
    if (result.source === "api") {
      setPlan({ ...plan, tasks: plan.tasks.map((task) => (task.id === id ? { ...task, status: result.envelope.data.status as "todo" | "done" } : task)) });
    } else {
      setPlan({ ...plan, tasks: plan.tasks.map((task) => (task.id === id ? { ...task, status: next } : task)) });
    }
  }

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    const replyId = crypto.randomUUID();
    setBubbles((list) => [...list, { id: crypto.randomUUID(), role: "user", text }, { id: replyId, role: "xiaoman", text: "" }]);
    setBusy(true);
    try {
      const reply = await readStream("/api/chat/stream", { message: text, lecture_id: lectureId }, (full) => {
        setBubbles((list) => list.map((item) => (item.id === replyId ? { ...item, text: full } : item)));
      });
      if (!reply) {
        setBubbles((list) => list.map((item) => (item.id === replyId ? { ...item, text: "（模拟）我在。" } : item)));
      }
    } catch {
      setBubbles((list) => list.map((item) => (item.id === replyId ? { ...item, text: "（模拟）后端这会儿没接上，我先用本地的同一形状回你。" } : item)));
      setSource("mock");
    } finally {
      setBusy(false);
    }
  }

  async function handIn() {
    const created = await api<{ file_id: string }>("/api/files/upload-url", { method: "POST", body: JSON.stringify({ filename: "样例-第6讲.pdf" }) });
    const fileId = created.envelope.data.file_id;
    if (created.source === "api" && fileId) {
      await api(`/api/files/${fileId}/raw`, { method: "PUT" });
      await api(`/api/files/${fileId}/complete`, { method: "POST", body: JSON.stringify({ lecture_id: lectureId }) });
    }
    setBubbles((list) => [...list, { id: crypto.randomUUID(), role: "xiaoman", text: "（模拟）资料先记下来了。真正按页抽文字还没做。" }]);
    setCards((list) => list.map((card) => (card.type === "progress" ? collapseCard(card) : card)));
  }

  const doneCount = plan.tasks.filter((task) => task.status === "done").length;
  const currentId = plan.tasks.find((task) => task.status !== "done")?.id;
  const sourceText = source === "loading" ? "正在连接" : source === "api" ? "已接上后端假数据" : "模拟内容";
  const sourceTitle = source === "mock" ? "后端没接上，用的是本地假数据" : undefined;

  return (
    <div className="app">
      <div className={rail ? "shell rail-open" : "shell"}>
        <aside className="rail" aria-label="今天三件与资料">
          <div className="rail-brand">
            <Icon name="menu" />
            <strong>小满</strong>
            <IconButton className="rail-close" icon="close" label="收起今天三件" onClick={() => setRail(false)} />
          </div>
          <div className="rail-title">
            <h2>今天三件</h2>
            <span className="count">
              {doneCount} / {plan.tasks.length}
            </span>
          </div>
          <div className="seg" role="group" aria-label="今天的强度">
            {INTENSITY.map((item) => (
              <button key={item.id} type="button" aria-pressed={plan.intensity === item.id} onClick={() => changeIntensity(item.id)}>
                {item.label}
              </button>
            ))}
          </div>
          <p className="rail-caption">
            约 {plan.minutes} 分钟 · {plan.label}
          </p>
          <ol className="today-list">
            {plan.tasks.map((task) => {
              const done = task.status === "done";
              const state = done ? "done" : task.id === currentId ? "current" : "";
              return (
                <li key={task.id}>
                  <button type="button" className={`task-card ${state}`} aria-pressed={done} onClick={() => toggleTask(task.id, task.status)}>
                    <TaskArt kind={task.kind} />
                    <span className="task-copy">
                      <span className="kind">{task.kind_label}</span>
                      <strong>{task.title}</strong>
                      <span className="meta">{done ? "已完成" : task.minutes ? `约 ${task.minutes} 分钟` : task.done_when}</span>
                    </span>
                    <span className="task-mark" aria-hidden="true">
                      {done && <Icon name="check" />}
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
          <section className="rail-section">
            <h2>我的资料</h2>
            <ul className="list-group">
              {board.lectures.map((lecture) => (
                <li key={lecture.id}>
                  <button type="button" className="list-row" onClick={() => { setLectureId(lecture.id); setTab("page"); }}>
                    <span className="list-icon">
                      <Icon name="file" />
                    </span>
                    <span className="grow">{lecture.title}</span>
                    <span className="aux">掌握 {lecture.mastery}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
          {permissions && (
            <section className="rail-section">
              <h2>授权</h2>
              <p className="aux">{permissions.chosen ? "已选过" : permissions.note}</p>
              <div className="list-group">
                {permissions.switches.map((item) => (
                  <label key={item.key} className="list-row">
                    <input
                      type="checkbox"
                      checked={item.value === true}
                      onChange={() => {
                        const next = Object.fromEntries(permissions.switches.map((row) => [row.key, row.key === item.key ? row.value !== true : row.value === true]));
                        void api<Permissions>("/api/me/permissions", { method: "PATCH", body: JSON.stringify({ permissions: next }) }).then((result) => {
                          setPermissions(result.envelope.data);
                        });
                      }}
                    />
                    <span className="grow">{item.label}</span>
                  </label>
                ))}
              </div>
            </section>
          )}
        </aside>
        <main className="chat">
          <div className="chat-top">
            <div className="chat-brand">
              <IconButton icon="menu" label="打开今天三件" onClick={() => setRail((open) => !open)} />
              <strong>小满</strong>
            </div>
            <div className="grow" />
            <span className="source-label" title={sourceTitle}>
              {sourceText}
            </span>
            <label className="pill-select">
              字号
              <select value={font} onChange={(event) => setFont(event.target.value as FontSize)}>
                <option value="sm">标准</option>
                <option value="md">大</option>
                <option value="lg">更大</option>
              </select>
            </label>
          </div>
          <button type="button" className="floating-materials" onClick={() => setTab("note")} aria-label="打开学习文档">
            <Icon name="book" />
            <span>学习文档</span>
            <Icon name="chevron" />
          </button>
          <div className="companion">
            <Avatar mood="wave" />
            <h1>小满</h1>
            <p>在这儿，陪你慢慢学</p>
          </div>
          <div className="stream">
            <p className="day">今天 · {plan.date}</p>
            {bubbles.map((bubble, index) => (
              <Bubble key={bubble.id} role={bubble.role} grouped={index > 0 && bubbles[index - 1].role === bubble.role}>
                {bubble.text}
              </Bubble>
            ))}
            {cards.map((card) => (
              <StudyCardView
                key={card.id}
                card={card}
                onDone={(id) => setCards((list) => list.map((item) => (item.id === id ? collapseCard(item) : item)))}
                onReopen={(id) => setCards((list) => list.map((item) => (item.id === id ? reopenCard(item) : item)))}
                onOpenWorkbench={setTab}
              />
            ))}
          </div>
          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault();
              void send();
            }}
          >
            <IconButton icon="plus" label="交资料" onClick={() => void handIn()} />
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="跟小满说，或把课件交给它…"
              aria-label="跟小满说一句"
            />
            <label className="lecture-pill">
              @
              <select value={lectureId} onChange={(event) => setLectureId(event.target.value)} aria-label="这句话说的是哪一讲">
                <option value="lec-6">第 6 讲</option>
              </select>
            </label>
            <IconButton type="submit" icon="up" label="发送" variant="primary" disabled={busy} />
          </form>
          <p className="disclaimer">AI 整理，可以改 · 重要内容请对照原文</p>
        </main>
        {tab && (
          <aside className="workbench">
            <header>
              <h2>{tab === "note" ? "学习文档" : tab === "page" ? "原文" : "看板"}</h2>
              <Button onClick={() => setTab(null)} aria-label="关闭工作台">
                关闭
              </Button>
            </header>
            {tab === "note" && (
              <div>
                <p className="badge">{note.label}</p>
                <h3>{note.title}</h3>
                <ul>
                  {(note.content?.points || []).map((point) => (
                    <li key={point}>{point}</li>
                  ))}
                </ul>
              </div>
            )}
            {tab === "page" && <pre className="page">{pageText}</pre>}
            {tab === "board" && (
              <div>
                <p>{board.note}</p>
                <p>这周打开过 {board.studied_days} 天 · 做题 {board.attempt_count} · 待看错题 {board.mistakes_due}</p>
                <p className="badge">{board.label}</p>
              </div>
            )}
            <section className="lines">
              <h3>五条线的位置</h3>
              <MaterialsLine />
              <QaLine />
              <PracticeLine />
              <PlanLine />
              <DashboardLine />
            </section>
          </aside>
        )}
      </div>
    </div>
  );
}
