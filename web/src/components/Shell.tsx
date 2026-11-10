import { Fragment, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { mockDashboard, mockPlan } from "../api/mocks";
import type { Dashboard, Intensity, Permissions, PlanToday } from "../api/types";
import { DashboardLine } from "../lines/dashboard/Placeholder";
import { DashboardPanel, DashboardSummary } from "../lines/dashboard/Dashboard";
import { fetchBoard, isDashboardRequest } from "../lines/dashboard/client";
import { mergeDashboardTurns, type DashboardTurn } from "../lines/dashboard/conversation";
import { MaterialsLine, type MaterialsHandle } from "../lines/materials/Placeholder";
import { NoteView, OriginalView } from "../lines/materials/NoteView";
import { useMaterialsWorkspace } from "../lines/materials/useMaterialsWorkspace";
import { PlanLine } from "../lines/plan/Placeholder";
import { PracticeLine } from "../lines/practice/Placeholder";
import { LecturePicker, QaAnswer, QaHandoff, QaSourcePanel, openQuizId, useQaConversation, type Reference } from "../lines/qa";
import type { Handoff } from "../lines/qa/types";
import { Avatar } from "./Avatar";
import { logout } from "./InviteGate";
import { collapseCard, reopenCard, type StudyCard } from "./cards/logic";
import { StudyCardView } from "./cards/StudyCardView";
import { advanceProgress, getCurrentOutline, getMistakes, getStatus, getTodaySummary, type OutlineView } from "../lines/v2/api";
import { ExamCard } from "../lines/v2/ExamCard";
import { DaySummaryCard } from "../lines/v2/DaySummaryCard";
import { MistakeBookCard } from "../lines/v2/MistakeBookCard";
import { currentUnitNo, firstLectureStep } from "../lines/v2/logic";
import { PathEntry, PathPanel } from "../lines/v2/PathPanel";
import { attentionItems, headline, type AttnItem, type AttnTask } from "../lines/v2/attention";
import { GOAL_DONE_RAIL, NEXT_GOAL_HINT } from "../lines/v2/cards";
import { subscribeGoalDone } from "../lines/v2/done";
import { AcceptedOutlineBar } from "../lines/v2/GoalFlowV2";
import { OUTLINE_BADGE, answerUsesOutlineSource, isOutlineFilename } from "../lines/v2/source";
import { V2Cards } from "../lines/v2/V2Cards";
import { LectureCard } from "../lines/v2/LectureCard";
import { Badge, Bubble, Button, Card, Icon, IconButton, TaskArt } from "./ui";

type FontSize = "sm" | "md" | "lg";
type Tab = "note" | "page" | "board" | "path";
type Notice = { id: string; role: "user" | "xiaoman"; text: string };

const INTENSITY: { id: Intensity; label: string }[] = [
  { id: "light", label: "轻松" },
  { id: "normal", label: "正常" },
  { id: "sprint", label: "冲刺" },
];

// 开发模式（地址加 ?dev=1）：显示“五条线的位置”面板和演示日期开关，正式页面不显示。
const DEV = typeof window !== "undefined" && new URLSearchParams(window.location.search).has("dev");

export function Shell({ canLogout = false }: { canLogout?: boolean } = {}) {
  const [source, setSource] = useState<"loading" | "api" | "mock">("loading");
  const [plan, setPlan] = useState<PlanToday>(mockPlan);
  const [, setBoard] = useState<Dashboard>(mockDashboard);
  const materials = useRef<MaterialsHandle>(null);
  const [pageText, setPageText] = useState("");
  const [pageLoading, setPageLoading] = useState(false);
  // 一开始对话流里不放卡片；各线接上真实业务后，由它们按“一次只出一张”往这里加。
  // 七种卡片的样子仍可用 cards/logic.ts 的 previewCards() 查看。
  const [cards, setCards] = useState<StudyCard[]>([]);
  const [bubbles] = useState<Notice[]>([
    { id: "hi", role: "xiaoman", text: "我是小满。今天有三件小事，想从哪件开始都行；有不懂的，直接问我。" },
  ]);
  const [draft, setDraft] = useState("");
  const qa = useQaConversation();
  const { lectureId, setLectureId } = qa;
  const [dashboardTurns, setDashboardTurns] = useState<DashboardTurn[]>([]);
  const [dashboardBusy, setDashboardBusy] = useState(false);
  const dashboardRequest = useRef<AbortController | null>(null);
  const busy = qa.busy || dashboardBusy;
  const conversation = mergeDashboardTurns(qa.messages, dashboardTurns);
  // 只记本次会话实际选择 / 拖入文件的时刻；保持同一 keyed 节点，移动时不重启上传。
  const [uploadAfter, setUploadAfter] = useState<{ qa: number; dashboard: number } | null>(null);
  const uploadPosition = uploadAfter ? Math.min(uploadAfter.qa + uploadAfter.dashboard, conversation.length) : conversation.length;
  const conversationWithMaterials = [
    ...conversation.slice(0, uploadPosition),
    { kind: "materials" as const },
    ...conversation.slice(uploadPosition),
  ];
  function markUpload() { setUploadAfter({ qa: qa.messages.length, dashboard: dashboardTurns.length }); }
  useEffect(() => () => dashboardRequest.current?.abort(), []);
  const workspace = useMaterialsWorkspace(lectureId, qa.currentLectureId, qa.sessionReady, setLectureId);
  const effectiveLectureId = workspace.lectureId;
  const materialsReady = qa.sessionReady && Boolean(effectiveLectureId);
  const availableLectures = workspace.lectures || qa.lectures;
  // 交资料默认交到计划里下一个要交的那一讲（“交第 N 讲课件”），用户用 @ 选了讲次时以选的为准。
  // 开始上传时把讲次钉住，免得交完自动勾掉任务后，卡片跟着跳到下一讲。
  const [pinnedUpload, setPinnedUpload] = useState("");
  const planUploadLecture = plan.tasks.find((task) => task.status === "todo" && task.kind === "learn" && task.ref?.source === "upload")?.ref?.lecture_id || "";
  const uploadLectureId = lectureId || pinnedUpload || planUploadLecture || effectiveLectureId;
  const needsGoal = source === "api" && plan.needs_setup === true;
  const [sourceReference, setSourceReference] = useState<Reference | null>(null);
  const [tab, setTab] = useState<Tab | null>(null);
  const [rail, setRail] = useState(false);
  const [font, setFont] = useState<FontSize>("md");
  const [permissions, setPermissions] = useState<Permissions | null>(null);
  // 往下滑时小满缩成顶部小头像，给对话腾出地方。
  const [compact, setCompact] = useState(false);
  // 只读一次。404 或连不上时 getStatus 为 false，对话仍走计划线原来的定目标。
  const [v2Enabled, setV2Enabled] = useState<boolean | null>(null);
  const [activeLecture, setActiveLecture] = useState<{ unitNo: number; taskId: string } | null>(null);
  const [outline, setOutline] = useState<OutlineView | null>(null);
  const [activeExam, setActiveExam] = useState(false);
  const [extraLecture, setExtraLecture] = useState<number | null>(null);
  const [reviewLecture, setReviewLecture] = useState<number | null>(null);
  const [mistakeCount, setMistakeCount] = useState<number | null>(null);
  const [showMistakes, setShowMistakes] = useState(false);
  const [mistakeTick, setMistakeTick] = useState(0);
  const [goalDone, setGoalDone] = useState(false);
  const [nextGoalHint, setNextGoalHint] = useState(false);
  const [doneNote, setDoneNote] = useState("");
  // 在对话里刚确认大纲：今天的安排接在对话后面，不插到最上面。
  const [justAccepted, setJustAccepted] = useState(false);
  // 确认大纲的那条回答在对话里的位置：确认后的计划卡 / 撤销条紧跟在它后面，后来的消息照常往下排。
  const [acceptedIndex, setAcceptedIndex] = useState<number | null>(null);
  // 正在做的那一件（左栏显示“进行中”，再点只是回到它，不重新开始）。
  const [inProgress, setInProgress] = useState<string | null>(null);
  // 刷新前没做完的练习：接着做。
  const [resumeQuiz, setResumeQuiz] = useState<Handoff["data"] | null>(null);
  const [totalDays, setTotalDays] = useState(0);
  const [settings, setSettings] = useState(false);
  const [tools, setTools] = useState(false);
  const activityRef = useRef<HTMLDivElement>(null);
  // 打开一张卡（错题本 / 讲解 / 考试 / 重看 / 接着练）时，定位到“这一张”的开头，停在顶栏下面。
  // 卡片内容是异步出来的（“正在准备” → 正文），头 2 秒里高度变了就再对齐一次；用户自己滚了就不再跟。
  const [focus, setFocus] = useState<{ key: string; n: number } | null>(null);
  const focusOn = (key: string) => setFocus({ key, n: Date.now() });
  useEffect(() => { if (showMistakes) focusOn("mistakes"); }, [showMistakes]);
  useEffect(() => { if (activeExam) focusOn("exam"); }, [activeExam]);
  useEffect(() => { if (activeLecture) focusOn("lecture"); }, [activeLecture]);
  useEffect(() => { if (reviewLecture !== null) focusOn("review"); }, [reviewLecture]);
  useEffect(() => { if (extraLecture !== null) focusOn("extra"); }, [extraLecture]);
  useEffect(() => {
    const stream = streamRef.current;
    if (!focus || !stream) return;
    let userMoved = false;
    const stop = () => { userMoved = true; };
    const align = (smooth: boolean) => {
      const target = stream.querySelector<HTMLElement>(`[data-focus="${focus.key}"]`);
      if (!target || userMoved) return;
      // 只滚对话列表本身（不用 scrollIntoView，它会连外层一起滚）；让开浮在上面的顶栏。
      const bar = (document.querySelector(".chat-top") as HTMLElement | null)?.offsetHeight ?? 0;
      const top = target.getBoundingClientRect().top - stream.getBoundingClientRect().top + stream.scrollTop - bar - 8;
      stream.scrollTo({ top: Math.max(0, top), behavior: smooth ? "smooth" : "auto" });
    };
    const frame = requestAnimationFrame(() => align(true));
    const target = stream.querySelector<HTMLElement>(`[data-focus="${focus.key}"]`);
    const observer = target && typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => align(false)) : null;
    if (observer && target) observer.observe(target);
    // 讲解 / 考试要 7–15 秒才出来：跟到内容出来为止（最多 25 秒），用户自己滚了就停。
    const done = window.setTimeout(() => observer?.disconnect(), 25000);
    stream.addEventListener("wheel", stop, { passive: true });
    stream.addEventListener("touchmove", stop, { passive: true });
    stream.addEventListener("keydown", stop);
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(done);
      observer?.disconnect();
      stream.removeEventListener("wheel", stop);
      stream.removeEventListener("touchmove", stop);
      stream.removeEventListener("keydown", stop);
    };
  }, [focus]);
  const streamRef = useRef<HTMLDivElement>(null);

  // 首屏（日期 + 状态 + 关注卡）是对话流的一部分，跟着一起滚；滚过它之后顶部收成一条。
  const heroRef = useRef<HTMLElement>(null);
  function onStreamScroll() {
    const el = streamRef.current;
    if (!el) return;
    const heroBottom = (heroRef.current?.offsetHeight ?? 0) - 40;
    const next = el.scrollTop > Math.max(24, heroBottom);
    if (next !== compact) setCompact(next);
  }

  // 有新消息时滚到最底下；小满的回复边生成边变长时，只要用户本来就在底部附近，也跟着滚。
  const lastCount = useRef(0);
  useEffect(() => {
    const el = streamRef.current;
    if (!el) return;
    const count = bubbles.length + qa.messages.length + dashboardTurns.length * 2 + cards.length;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160;
    if (count !== lastCount.current || nearBottom) el.scrollTop = el.scrollHeight;
    lastCount.current = count;
  }, [bubbles, qa.messages, dashboardTurns, cards.length]);

  // 暗色模式暂不做（以后作为换肤加回来），这里只管字号。
  useEffect(() => {
    document.documentElement.dataset.font = font;
  }, [font]);

  useEffect(() => {
    if (!qa.sessionReady) return;
    let cancelled = false;
    void getStatus().then((enabled) => { if (!cancelled) setV2Enabled(enabled); });
    return () => { cancelled = true; };
  }, [qa.sessionReady]);

  // V2.2 错题本数字：做完题、考完试、再做一次后刷新。
  useEffect(() => {
    if (v2Enabled !== true || plan.needs_setup === true) { setMistakeCount(null); return; }
    let cancelled = false;
    void getMistakes().then((book) => { if (!cancelled) setMistakeCount(book ? book.count : null); });
    return () => { cancelled = true; };
  }, [v2Enabled, plan.needs_setup, plan.date, plan.tasks.filter((task) => task.status === "done").length, mistakeTick, qa.messages.length]);

  // 块4：确认后的大纲留在左栏。
  useEffect(() => {
    if (v2Enabled !== true || plan.needs_setup === true) {
      setOutline(null);
      return;
    }
    let cancelled = false;
    void getCurrentOutline().then((data) => { if (!cancelled) setOutline(data); });
    return () => { cancelled = true; };
  }, [v2Enabled, plan.needs_setup, plan.date, plan.tasks.filter((task) => task.status === "done").length]);

  useEffect(() => {
    if (v2Enabled !== true || plan.needs_setup === true) return;
    let cancelled = false;
    void getTodaySummary().then((data) => { if (!cancelled && data) setTotalDays(data.total_days); });
    return () => { cancelled = true; };
  }, [v2Enabled, plan.needs_setup, plan.tasks.filter((task) => task.status === "done").length]);

  // 练习没出来（回答失败）：左栏不再显示“进行中”，再点就能重新出题。
  const lastAnswer = qa.messages.at(-1);
  useEffect(() => {
    if (lastAnswer?.role === "assistant" && lastAnswer.status === "error") setInProgress(null);
  }, [lastAnswer?.id, lastAnswer?.status]);

  // 只在刚打开页面时查一次：今天有没做完的练习组。
  const resumeChecked = useRef(false);
  useEffect(() => {
    if (resumeChecked.current || v2Enabled !== true || source !== "api" || plan.needs_setup === true) return;
    const practice = plan.tasks.find((task) => task.kind === "practice" && task.status !== "done");
    const quizId = openQuizId();
    resumeChecked.current = true;
    if (!practice || !quizId) return;
    void api<Handoff["data"]>(`/api/quizzes/${encodeURIComponent(quizId)}`).then((result) => {
      if (result.source === "api" && !result.envelope.data.completed && result.envelope.data.questions?.length) {
        setResumeQuiz(result.envelope.data);
        setInProgress(practice.id);
      }
    });
  }, [v2Enabled, source, plan.needs_setup, plan.tasks]);

  useEffect(() => {
    if (v2Enabled !== true) {
      setGoalDone(false);
      return;
    }
    return subscribeGoalDone((done) => {
      setGoalDone(done);
      if (!done) setNextGoalHint(false);
    });
  }, [v2Enabled]);

  // 今天的安排：只在会话就绪时取一次，不跟着讲次变化重取（线上每次要 2–3 秒）。
  useEffect(() => {
    if (!qa.sessionReady) return;
    let cancelled = false;
    (async () => {
      const [planRes, boardRes, permRes] = await Promise.all([
        api<PlanToday>("/api/plan/today"),
        api<Dashboard>("/api/dashboard?range=week"),
        api<Permissions>("/api/me/permissions"),
      ]);
      if (cancelled) return;
      const fromApi = [planRes, boardRes, permRes].every((item) => item.source === "api");
      setSource(fromApi ? "api" : "mock");
      setPlan(planRes.envelope.data);
      setBoard(boardRes.envelope.data);
      setPermissions(permRes.envelope.data);
    })();
    return () => {
      cancelled = true;
    };
  }, [qa.sessionReady]);

  // 当前讲的原文：讲次变了才重取，和今天的安排互不等待。
  useEffect(() => {
    setPageText("");
    setPageLoading(qa.sessionReady && Boolean(effectiveLectureId));
    if (!qa.sessionReady || !effectiveLectureId) return;
    let cancelled = false;
    void api<{ pages: { page: number; text: string }[] }>(`/api/lectures/${encodeURIComponent(effectiveLectureId)}/pages`).then((pageRes) => {
      if (cancelled) return;
      const pages = pageRes.envelope.data.pages || [];
      setPageText(pages.map((item) => `【第 ${item.page} 页】${item.text}`).join("\n\n"));
      setPageLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [effectiveLectureId, qa.sessionReady]);

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
    if (!text || busy || dashboardRequest.current || !qa.sessionReady) return;
    setDraft("");
    if (!isDashboardRequest(text)) {
      await qa.send(text);
      return;
    }
    const id = crypto.randomUUID();
    const controller = new AbortController();
    dashboardRequest.current = controller;
    setDashboardBusy(true);
    setDashboardTurns((list) => [...list, { id, after: qa.messages.length, question: text }]);
    try {
      const dashboard = await fetchBoard(controller.signal);
      setDashboardTurns((list) => list.map((turn) => turn.id === id ? { ...turn, board: dashboard } : turn));
      setBoard(dashboard);
    } catch (error) {
      if (!controller.signal.aborted) {
        const message = error instanceof Error ? error.message : "看板暂时没接上，请稍后重试。";
        setDashboardTurns((list) => list.map((turn) => turn.id === id ? { ...turn, error: message } : turn));
      }
    } finally {
      dashboardRequest.current = null;
      setDashboardBusy(false);
    }
  }

  async function refreshStudy() {
    const [planRes, boardRes] = await Promise.all([api<PlanToday>("/api/plan/today"), api<Dashboard>("/api/dashboard?range=week"), workspace.refresh()]);
    if (planRes.source === "api") setPlan(planRes.envelope.data);
    if (boardRes.source === "api") setBoard(boardRes.envelope.data);
  }

  // 每一件只有一个入口：点任务卡就开始；做完一件，自动接下一件。
  function canStart(task: PlanToday["tasks"][number]) {
    if (task.kind === "learn") return task.ref?.source === "lecture" || (task.ref?.source === "upload" && Boolean(task.ref.lecture_id));
    if (task.kind === "practice") return Boolean(v2Enabled && task.ref?.lecture_no);
    return task.kind === "exam";
  }

  function scrollToBottom() {
    const el = streamRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }

  function startTask(task: PlanToday["tasks"][number]) {
    setRail(false);
    setDoneNote("");
    // 已经在做这一件：回到它，不重新开始（练习不会再出一组新题）。
    if (task.id === inProgress || task.id === activeLecture?.taskId) {
      if (task.id === activeLecture?.taskId) focusOn("lecture");
      else if (task.kind === "exam" && activeExam) focusOn("exam");
      else if (resumeQuiz && task.kind === "practice") focusOn("resume");
      else scrollToBottom();
      return;
    }
    setInProgress(task.id);
    if (task.kind === "learn" && task.ref?.source === "lecture") setActiveLecture({ unitNo: task.ref.lecture_no!, taskId: task.id });
    else if (task.kind === "learn" && task.ref?.lecture_id) { setPinnedUpload(task.ref.lecture_id); materials.current?.chooseFile(); }
    else if (task.kind === "practice" && task.ref?.lecture_no) void qa.send(`出几道第 ${task.ref.lecture_no} 讲的练习题`);
    else if (task.kind === "exam") setActiveExam(true);
  }

  async function startNext(skipId?: string) {
    const fresh = await api<PlanToday>("/api/plan/today");
    const tasks = fresh.source === "api" ? fresh.envelope.data.tasks : plan.tasks;
    if (fresh.source === "api") setPlan(fresh.envelope.data);
    const next = tasks.find((task) => task.status !== "done" && task.id !== skipId && canStart(task));
    if (next) startTask(next);
  }

  async function finishLecture(taskId: string, unitNo: number) {
    await api(`/api/tasks/${taskId}`, { method: "PATCH", body: JSON.stringify({ status: "done" }) });
    setActiveLecture(null);
    // 小步庆祝：放进对话流里（不是模型说的，不标 AI），紧接着出练习。
    qa.addNote(`✓ 第 ${unitNo} 讲学完了，接着练几道题巩固一下。`);
    await startNext(taskId);
  }

  const doneCount = plan.tasks.filter((task) => task.status === "done").length;
  const waitForV2 = source === "api" && v2Enabled === null && plan.needs_setup === true;
  const firstStep = goalDone ? null : firstLectureStep(outline, plan.tasks);
  const examInPlan = plan.tasks.some((task) => task.kind === "exam");
  const learnedUpTo = outline?.learned_up_to ?? 0;
  const allLearned = !outline || learnedUpTo >= outline.units.length;
  const allDoneToday = plan.tasks.length > 0 && plan.tasks.every((task) => task.status === "done");
  const nextUnit = outline && !goalDone && allDoneToday && !allLearned ? outline.units[learnedUpTo] : undefined; // 当日总结卡里的「学下一讲」
  const nextExtra = nextUnit ? { no: nextUnit.no ?? learnedUpTo + 1, title: nextUnit.title } : null;
  const currentId = plan.tasks.find((task) => task.status !== "done")?.id;
  const nextTask = plan.tasks.find((task) => task.status !== "done");
  // @ 选讲：AI 大纲的各讲在接口里同名，这里换成“第 N 讲 · 单元标题”；可选的讲有两讲以上才显示。
  // （小满回答里会提示“请用 @ 选讲”，所以有多讲时入口必须在。）
  const realLectures = availableLectures.filter((item) => !item.mock).map((item) => {
    if (!isOutlineFilename(item.title)) return item;
    const no = Number(/^lec-(\d+)$/.exec(item.id)?.[1] || 0);
    const unit = outline?.units.find((row, index) => (row.no ?? index + 1) === no);
    return { ...item, title: unit ? `第 ${no} 讲 · ${unit.title}` : `第 ${no} 讲` };
  }).sort((a, b) => Number(/\d+/.exec(a.id)?.[0] || 0) - Number(/\d+/.exec(b.id)?.[0] || 0));
  const planOpening = <>
    {source === "api" && !waitForV2 && plan.needs_setup !== true && <PlanLine inChat showDemo={DEV} hideDoneCard={v2Enabled === true} />}
    {source === "api" && v2Enabled === true && plan.needs_setup !== true && <AcceptedOutlineBar today={plan.date} />}
  </>;
  const localToday = new Date().toLocaleDateString("sv-SE");
  const [, monthNum = "", dayNum = ""] = /^\d{4}-(\d{2})-(\d{2})$/.exec(source === "loading" ? localToday : plan.date) || [];
  const attnInput = {
    needsGoal: needsGoal || (source === "api" && v2Enabled === true && plan.needs_setup === true),
    goalDone,
    tasks: plan.tasks as unknown as AttnTask[],
    stageReady: outline?.checkpoints?.find((gate) => gate.status === "ready")?.stage_no ?? null,
    resumeLectureNo: resumeQuiz ? plan.tasks.find((task) => task.kind === "practice" && task.status !== "done")?.ref?.lecture_no ?? null : null,
    totalDays,
  };
  // 首次加载要几秒（线上库在东京），这期间 plan 还是内置样例：不能把样例当成用户的安排显示出来。
  const loading = source === "loading";
  const hero = loading ? { title: "正在准备今天的安排…", sub: "小满在整理你的进度，稍等一下" } : headline(attnInput);
  const attention = source === "loading" ? [] : attentionItems(attnInput);
  function onAttention(item: AttnItem) {
    if (item.action === "resume") { focusOn("resume"); return; }
    if (item.action === "summary") { focusOn("summary"); return; }
    const task = plan.tasks.find((row) => row.id === item.taskId);
    if (task && canStart(task)) startTask(task);
    else if (task) setRail(true);
  }
  const EXAMPLES = ["两周后考 PMP，每天半小时", "三个月学会 Python 入门", "零基础学吉他，每天 20 分钟"];

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
            <h2>今天</h2>
            <span className="count">
              {loading ? "…" : goalDone ? "已完成" : needsGoal ? "0 / 0" : `${doneCount} / ${plan.tasks.length}`}
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
            {loading ? "　" : `约 ${plan.minutes} 分钟${totalDays > 0 ? ` · 累计学了 ${totalDays} 天` : ""}`}
          </p>
          {loading ? (
            <div className="rail-empty" role="status"><p>正在读取今天的安排…</p></div>
          ) : goalDone ? (
            <div className="rail-empty">
              <p>{GOAL_DONE_RAIL}</p>
              <Button variant="primary" onClick={() => setNextGoalHint(true)}>定下一个目标</Button>
              {nextGoalHint && <p>{NEXT_GOAL_HINT}</p>}
            </div>
          ) : needsGoal ? (
            <div className="rail-empty">
              <p>先定个学习目标，我帮你拆成每天三件。</p>
              <Button variant="primary" onClick={() => { setRail(false); document.querySelector<HTMLInputElement>('input[aria-label="跟小满说一句"]')?.focus(); }}>
                定目标
              </Button>
            </div>
          ) : (
          <ol className="today-list">
            {plan.tasks.map((task) => {
              const done = task.status === "done";
              const state = done ? "done" : task.id === currentId ? "current" : "";
              const startable = !done && canStart(task);
              return (
                <li key={task.id}>
                  <button type="button" className={`task-card ${state}`} aria-pressed={done}
                    disabled={startable && !qa.sessionReady}
                    aria-label={startable ? `开始：${task.title}` : undefined}
                    onClick={() => (startable ? startTask(task) : void toggleTask(task.id, task.status))}>
                    <TaskArt kind={task.kind} />
                    <span className="task-copy">
                      <span className="kind">{task.kind_label}</span>
                      <strong>{task.title}</strong>
                      <span className="meta">{done ? "已完成" : task.minutes ? `约 ${task.minutes} 分钟` : task.done_when}</span>
                    </span>
                    {!done && (task.id === inProgress || task.id === activeLecture?.taskId) ? <span className="task-go live">进行中</span>
                      : state === "current" && startable ? <span className="task-go">开始</span> : (
                      <span className="task-mark" aria-hidden="true">
                        {done && <Icon name="check" />}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ol>
          )}
          {outline && !goalDone && mistakeCount !== null && (
            <div className="rail-section">
              <Button className="list-row" onClick={() => { setShowMistakes(true); focusOn("mistakes"); setRail(false); }}>
                <span className="grow">错题本</span>
                <span className="aux">{mistakeCount ? `${mistakeCount} 题没做对` : "暂无"}</span>
              </Button>
            </div>
          )}
          {outline && !goalDone && <PathEntry outline={outline} onOpen={() => { setTab("path"); setRail(false); }} />}
          <section className="rail-section">
            <h2>我的资料</h2>
            {workspace.listError && <p role="alert" className="aux">{workspace.listError}</p>}
            {!workspace.notes.length && <p className="aux">{qa.sessionReady ? "先交一份 PDF，整理好的笔记会放在这里。" : "正在读取学习笔记……"}</p>}
            {workspace.notes.length > 0 && <ul className="list-group">
              {workspace.notes.map((item) => (
                <li key={item.id}>
                  <Button className="list-row" onClick={() => { workspace.openStored(item); setSourceReference(null); setTab("note"); setRail(false); }}>
                    <span className="list-icon"><Icon name="file" /></span>
                    <span className="grow">{item.title}</span>
                    <span className="aux">第 {item.lecture_id.replace("lec-", "")} 讲</span>
                  </Button>
                </li>
              ))}
            </ul>}
          </section>
        </aside>
        <main className={compact ? "chat compact" : "chat"}
          onDragOver={event => { if (Array.from(event.dataTransfer.types).includes("Files")) event.preventDefault(); }}
          onDrop={event => { if (!event.dataTransfer.files.length) return; event.preventDefault(); if (event.dataTransfer.files.length !== 1) materials.current?.rejectDrop(); else { markUpload(); setPinnedUpload(uploadLectureId); materials.current?.uploadFile(event.dataTransfer.files[0]); } }}
        >
          <div className="chat-top">
            <div className="chat-brand">
              <IconButton icon="menu" label="打开今天三件" onClick={() => setRail((open) => !open)} />
              <strong>小满</strong>
            </div>
            {/* 往下滑过首屏后：顶部收成一条，小头像 + 今天的状态 */}
            {compact && <div className="mini-status"><Avatar mood="wave" size={30} /><strong>小满</strong><span>{hero.title}</span></div>}
            <div className="grow" />
            {source === "mock" && <span className="source-label" title="后端没接上，用的是本地假数据">离线演示</span>}
            <Button className="settings-btn" aria-label="设置" aria-expanded={settings} onClick={() => { setTools(false); setSettings((open) => !open); }}>Aa</Button>
            {settings && (
              <div className="settings-pop" role="dialog" aria-label="设置">
                <h3>字号</h3>
                <div className="seg" role="group" aria-label="字号">
                  {([["sm", "标准"], ["md", "大"], ["lg", "更大"]] as const).map(([id, label]) => (
                    <button key={id} type="button" aria-pressed={font === id} onClick={() => setFont(id)}>{label}</button>
                  ))}
                </div>
                {permissions && (
                  <>
                    <h3>小满可以</h3>
                    <p className="aux">只影响给你的建议，随时可以改。</p>
                    <div className="list-group">
                      {permissions.switches.filter((item) => !item.placeholder).map((item) => (
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
                  </>
                )}
                <div className="settings-actions">
                  {canLogout && <Button onClick={() => void logout()}>退出登录</Button>}
                  <Button onClick={() => setSettings(false)}>好</Button>
                </div>
              </div>
            )}
            <IconButton className={mistakeCount ? "tools-btn has-dot" : "tools-btn"} icon="grid" label="更多" aria-expanded={tools} onClick={() => { setSettings(false); setTools((open) => !open); }} />
            {tools && (
              <div className="tools-pop" role="menu" aria-label="更多">
                {outline && !goalDone && <button type="button" role="menuitem" onClick={() => { setTools(false); setTab("path"); }}><Icon name="path" /><span className="grow">学习路径</span><span className="aux">{Math.min(learnedUpTo, outline.units.length)} / {outline.units.length} 讲</span></button>}
                {outline && !goalDone && mistakeCount !== null && <button type="button" role="menuitem" onClick={() => { setTools(false); setShowMistakes(true); focusOn("mistakes"); }}><Icon name="pen" /><span className="grow">错题本</span>{mistakeCount ? <span className="tools-count">{mistakeCount}</span> : <span className="aux">暂无</span>}</button>}
                <button type="button" role="menuitem" aria-label="打开学习文档" onClick={() => { setTools(false); materials.current?.openNote(); }}><Icon name="book" /><span className="grow">学习文档</span></button>
                <button type="button" role="menuitem" disabled={!materialsReady} onClick={() => { setTools(false); setPinnedUpload(uploadLectureId); materials.current?.chooseFile(); }}><Icon name="file" /><span className="grow">交课件</span><span className="aux">PDF</span></button>
              </div>
            )}
            {compact && !loading && !needsGoal && !goalDone && plan.tasks.length > 0 && (
              <div className="today-bar" aria-label="今天的进度">
                <button type="button" className="today-bar-info" onClick={() => setRail(true)}>
                  <span className="today-bar-count">今天 {doneCount}/{plan.tasks.length}</span>
                  <span className="today-bar-meter" aria-hidden="true"><span style={{ width: `${(doneCount / plan.tasks.length) * 100}%` }} /></span>
                  <span className="today-bar-next">{nextTask ? `下一件：${nextTask.title}` : "今天的都做完了"}</span>
                </button>
                {nextTask && canStart(nextTask) && <Button variant="primary" disabled={!qa.sessionReady} onClick={() => startTask(nextTask)}>{nextTask.id === inProgress || nextTask.id === activeLecture?.taskId ? "继续" : "开始"}</Button>}
              </div>
            )}
          </div>
          <div className="stream" ref={streamRef} onScroll={onStreamScroll}>
            <section className="hero" ref={heroRef} aria-label="今天">
              <p className="hero-date" aria-label={`今天 ${plan.date}`}><b>{monthNum}</b>/{dayNum}</p>
              <h1 className="hero-title">{hero.title}</h1>
              <p className="hero-sub"><Avatar mood="wave" size={28} /><span>{hero.sub}</span></p>
              {attention.length > 0 && (
                <div className="attn-list" aria-label="需要你关注">
                  {attention.map((item) => (
                    <button key={item.key} type="button" className="attn-card" disabled={!qa.sessionReady} onClick={() => onAttention(item)}>
                      <TaskArt kind={item.kind} />
                      <span className="attn-copy"><strong>{item.title}</strong><span>{item.sub}</span></span>
                      <Icon name="chevron" />
                    </button>
                  ))}
                </div>
              )}
            </section>
            {source === "api" && v2Enabled === true && plan.needs_setup === true && <>
              <Bubble role="xiaoman">我是小满。说说你想学什么、什么时候学完、每天有多少时间，我帮你拆成每天的小任务。</Bubble>
              {qa.messages.length === 0 && (
                <div className="quick-replies examples" role="group" aria-label="可以这样说">
                  {EXAMPLES.map((text) => <Button key={text} disabled={!qa.sessionReady || busy} onClick={() => void qa.send(text)}>{text}</Button>)}
                </div>
              )}
            </>}
            {!justAccepted && planOpening}
            {source !== "api" && bubbles.map((bubble, index) => (
              <Bubble key={bubble.id} role={bubble.role} grouped={index > 0 && bubbles[index - 1].role === bubble.role}>
                {bubble.text}
              </Bubble>
            ))}
            {conversationWithMaterials.map((entry, index) => entry.kind === "materials" ? (
              <div key="materials" hidden={!uploadAfter} onChangeCapture={event => {
                const target = event.target;
                if (target instanceof HTMLInputElement && target.type === "file" && target.files?.length) markUpload();
              }}>
                <MaterialsLine
                  ref={materials}
                  lectureId={uploadLectureId}
                  enabled={materialsReady}
                  showIdle={false}
                  currentNote={workspace.note}
                  onOpenOriginal={pages => { workspace.showOriginal(pages); setSourceReference(null); setTab("page"); }}
                  onOpenNote={opened => { workspace.showNote(opened); setTab("note"); }}
                  onTextReady={() => { void refreshStudy(); }}
                  onReady={() => { void refreshStudy(); }}
                />
              </div>
            ) : entry.kind === "qa" ? (
              <Fragment key={entry.answer.id}>
                {answerUsesOutlineSource({ references: entry.answer.references, handoffIntent: entry.answer.handoff?.intent, lectureId: qa.currentLectureId || effectiveLectureId }, availableLectures) && (
                  <p className="v2-source"><Badge>{OUTLINE_BADGE}</Badge></p>
                )}
                <QaAnswer answer={entry.answer} active={index === conversationWithMaterials.length - 1 || (index === conversationWithMaterials.length - 2 && conversationWithMaterials.at(-1)?.kind === "materials")} onPlanChange={setPlan} onQuickReply={(text) => void qa.send(text)} onRetry={() => { const prev = conversationWithMaterials.slice(0, index).reverse().find((item) => item.kind === "qa" && item.answer.role === "user"); if (prev && prev.kind === "qa") void qa.send(prev.answer.text); }} onNextTask={() => void startNext()} onGoalAccepted={() => { setDoneNote(""); setAcceptedIndex(index); setJustAccepted(true); void refreshStudy(); }} onReference={(reference) => { workspace.clearOriginal(); setSourceReference(reference); setTab("page"); }} />
                {justAccepted && index === acceptedIndex && planOpening}
              </Fragment>
            ) : (
              <Fragment key={entry.turn.id}>
                <Bubble role="user">{entry.turn.question}</Bubble>
                {entry.turn.board ? <DashboardSummary board={entry.turn.board} onOpen={() => setTab("board")} />
                  : entry.turn.error ? <Bubble role="xiaoman">{entry.turn.error}</Bubble>
                    : <p role="status">正在读取看板…</p>}
              </Fragment>
            ))}
            {qa.lectureError && <p role="alert">{qa.lectureError}</p>}
            {justAccepted && (acceptedIndex === null || acceptedIndex >= conversationWithMaterials.length || conversationWithMaterials[acceptedIndex]?.kind !== "qa") && planOpening}
            <div className="activity" ref={activityRef}>
            {resumeQuiz && (
              <section aria-label="接着做练习" data-focus="resume">
                <p className="done-note" role="status">上次的练习还没做完，接着来。</p>
                <QaHandoff handoff={{ intent: "quiz", data: resumeQuiz }} onPlanChange={setPlan} onNextTask={() => { setResumeQuiz(null); void startNext(); }} />
              </section>
            )}
            {v2Enabled && !activeLecture && firstStep && (
              <Card as="section" aria-label="下一步">
                <p>{firstStep.text}</p>
                <div className="btns">
                  <Button variant="primary" disabled={!qa.sessionReady} onClick={() => setActiveLecture({ unitNo: firstStep.unitNo, taskId: firstStep.taskId })}>开始第 1 讲</Button>
                </div>
              </Card>
            )}
            {v2Enabled && <V2Cards doneCount={doneCount} examInPlan={examInPlan} allLearned={allLearned} />}
            {/* 完成卡在前；用户刚打开的东西排在它后面（最新的在最下面，并且会自动定位过去） */}
            {v2Enabled && outline && !goalDone && allDoneToday && !activeLecture && !activeExam && extraLecture === null && (
              <div data-focus="summary"><DaySummaryCard refreshKey={`${plan.date}-${learnedUpTo}`} next={nextExtra} busy={!qa.sessionReady} onNext={setExtraLecture} /></div>
            )}
            {reviewLecture !== null && (
              <div data-focus="review"><LectureCard key={`review-${reviewLecture}`} unitNo={reviewLecture} doneLabel="看完了" onDone={() => setReviewLecture(null)} /></div>
            )}
            {extraLecture !== null && (
              <div data-focus="extra"><LectureCard unitNo={extraLecture} doneLabel="学完了" onDone={() => {
                void advanceProgress(extraLecture).then(async () => { setOutline(await getCurrentOutline()); setExtraLecture(null); });
              }} /></div>
            )}
            {showMistakes && <div data-focus="mistakes"><MistakeBookCard onClose={() => { setShowMistakes(false); setMistakeTick((n) => n + 1); }} onChanged={() => setMistakeTick((n) => n + 1)} /></div>}
            {activeExam && <div data-focus="exam"><ExamCard onDone={() => { setActiveExam(false); setDoneNote(""); setMistakeTick((n) => n + 1); void refreshStudy(); }} /></div>}
            {activeLecture && (
              <div data-focus="lecture"><LectureCard unitNo={activeLecture.unitNo} onDone={() => void finishLecture(activeLecture.taskId, activeLecture.unitNo)} /></div>
            )}
            </div>
            {doneNote && <p className="done-note" role="status"><Icon name="check" />{doneNote}</p>}
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
            <IconButton icon="plus" label="交资料" disabled={!materialsReady} onClick={() => { setPinnedUpload(uploadLectureId); materials.current?.chooseFile(); }} />
            <input
              value={draft}
              maxLength={4000}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={needsGoal ? "比如：两周后考 PMP，每天半小时" : "有不懂的，直接问小满"}
              aria-label="跟小满说一句"
            />
            {realLectures.length >= 2 && <LecturePicker value={lectureId} onChange={setLectureId} lectures={realLectures} currentLectureId={effectiveLectureId} disabled={busy} />}
            {qa.busy && <Button onClick={qa.stop}>停止</Button>}
            <IconButton type="submit" icon="up" label="发送" variant="primary" disabled={busy || !qa.sessionReady} />
          </form>
          <p className="disclaimer">小满整理的内容可能有误，重要内容请对照原文</p>
        </main>
        {tab && (
          <aside className={tab === "path" ? "workbench path-wide" : "workbench"}>
            <header>
              <h2>{tab === "note" ? "学习文档" : tab === "page" ? "原文" : tab === "path" ? "学习路径" : "看板"}</h2>
              {tab === "page" && workspace.note && !sourceReference && <Button onClick={() => setTab("note")}>返回笔记</Button>}
              <Button onClick={() => setTab(null)} aria-label="关闭工作台">
                关闭
              </Button>
            </header>
            {tab === "note" && (workspace.opening ? <p role="status">正在打开学习笔记……</p>
              : workspace.error ? <p role="alert">{workspace.error}</p>
                : workspace.note?.lecture_id === effectiveLectureId ? <NoteView key={workspace.note.id} note={workspace.note}
                  onSaved={saved => { workspace.showNote(saved); void refreshStudy(); }}
                  onCitation={citation => { setSourceReference(null); setTab("page"); void workspace.openCitation(citation); }} />
                  : outline && learnedUpTo > 0 ? <div className="doc-learned">
                    <p className="aux">还没交课件，这里先放你学过的讲解，点开可以重看。</p>
                    <ul className="list-group">
                      {outline.units.slice(0, learnedUpTo).map((unit, index) => (
                        <li key={index}><Button className="list-row" onClick={() => { setReviewLecture(unit.no ?? index + 1); setTab(null); }}>
                          <span className="list-icon"><Icon name="book" /></span><span className="grow">第 {unit.no ?? index + 1} 讲 · {unit.title}</span><Icon name="chevron" />
                        </Button></li>
                      ))}
                    </ul>
                  </div>
                  : <p>这里会放你的学习笔记。学完一讲，或交一份 PDF 课件，内容就会出现在这里。</p>)}
            {tab === "page" && (sourceReference ? <QaSourcePanel reference={sourceReference} />
              : workspace.openingOriginal ? <p role="status">正在读取出处……</p>
                : workspace.originalError ? <p role="alert">{workspace.originalError}</p>
                  : !workspace.originalText && pageLoading ? <p role="status">正在读取当前讲原文……</p>
                    : <OriginalView text={workspace.originalText || pageText || "这一讲还没有可用正文，请先交一份 PDF。"} citation={workspace.citation} />)}
            {tab === "board" && <DashboardPanel onUpdate={setBoard} />}
            {tab === "path" && (outline
              ? <PathPanel outline={outline} currentNo={currentUnitNo(plan.tasks)}
                onReview={(no) => { setReviewLecture(no); setTab(null); }}
                onContinue={() => {
                  setTab(null);
                  const learn = plan.tasks.find((task) => task.kind === "learn" && task.status !== "done" && canStart(task));
                  if (learn) startTask(learn); else scrollToBottom();
                }} />
              : <p className="aux">还没有学习路径，先定个目标吧。</p>)}
            {DEV && <section className="lines">
              <h3>五条线的位置</h3>
              <PracticeLine />
              <DashboardLine />
            </section>}
          </aside>
        )}
      </div>
    </div>
  );
}
