import type { Dashboard, NoteItem, PlanToday, Suggestion } from "./types";

export const mockPlan: PlanToday = {
  date: "2026-11-04",
  intensity: "normal",
  intensity_label: "正常",
  minutes: 30,
  label: "模拟",
  tasks: [
    { id: "local-learn", kind: "learn", kind_label: "学新的", title: "交第 6 讲课件", status: "todo", done_when: "课件交上来" },
    { id: "local-practice", kind: "practice", kind_label: "练一练", title: "第 6 讲做 2 道题", status: "todo", done_when: "做完一组题" },
    { id: "local-repair", kind: "repair", kind_label: "补一补", title: "看看还没掌握的那一点", status: "todo", done_when: "看完要点" },
  ],
};

export const mockNotes: NoteItem[] = [
  {
    id: "local-note",
    lecture_id: "lec-6",
    title: "第 6 讲 · 学习文档",
    edited_by_user: false,
    label: "AI 整理，可以改",
    point_count: 3,
    content: {
      label: "AI 整理，可以改",
      points: ["每天最多三件事", "想多学加强度，不加件数", "没做的不堆到今天"],
      terms: ["学新的", "练一练", "补一补"],
    },
  },
];

export const mockDashboard: Dashboard = {
  range: "week",
  studied_days: 1,
  attempt_count: 0,
  mistakes_due: 0,
  lectures: [{ id: "lec-6", title: "第 6 讲", mastery: 40 }],
  files: [{ id: "local-file", filename: "样例-第6讲.pdf", parse_status: "ready" }],
  goal_progress: 0.2,
  llm_calls: 0,
  label: "模拟",
  note: "只和自己的过去比。",
};

export const mockSuggestions: Suggestion[] = [
  {
    id: "local-suggest",
    status: "pending",
    suggestion: { title: "今天换成轻松", body: "还是三件，每件少一点，大约 15 分钟。", label: "模拟" },
  },
];

const pages = [
  { page: 1, text: "每天最多三件事，分别来自学新的、练一练、补一补。想多学，就把每件做深一点，不增加件数。" },
  { page: 2, text: "做了就算完成。对错只影响掌握度。没做的不堆到今天。" },
];

export function mockFor(path: string, method: string): unknown {
  const url = path.split("?")[0];
  if (url === "/api/plan/today" && method === "GET") return { ok: true, status: "ok", mock: true, data: mockPlan };
  if (url === "/api/plan/today" && method === "PATCH") return { ok: true, status: "ok", mock: true, data: { ...mockPlan, intensity: "light", intensity_label: "轻松", minutes: 15 } };
  if (url.startsWith("/api/tasks/")) return { ok: true, status: "ok", mock: true, data: { ...mockPlan.tasks[0], status: "done" } };
  if (url === "/api/notes") return { ok: true, status: "ok", mock: true, data: { items: mockNotes } };
  if (url.startsWith("/api/notes/")) return { ok: true, status: "ok", mock: true, data: mockNotes[0] };
  if (url === "/api/dashboard") return { ok: true, status: "ok", mock: true, data: mockDashboard };
  if (url === "/api/suggestions") return { ok: true, status: "ok", mock: true, data: { items: mockSuggestions } };
  if (url.includes("/accept") || url.includes("/undo")) {
    return { ok: true, status: "ok", mock: true, data: { ...mockSuggestions[0], status: url.includes("undo") ? "undone" : "executed", plan: mockPlan } };
  }
  if (url.startsWith("/api/lectures/")) return { ok: true, status: "ok", mock: true, data: { lecture_id: "lec-6", pages, label: "模拟" } };
  if (url === "/api/goals/current" || url === "/api/goals") {
    return { ok: true, status: "ok", mock: true, data: { id: "local-goal", title: "样例目标", card_type: "goal", label: "模拟", summary: { phases: ["每天最多三件"] } } };
  }
  if (url === "/api/files/upload-url") return { ok: true, status: "ok", mock: true, data: { file_id: "local-file", upload_url: "/api/files/local-file/raw", mock: true } };
  if (url.includes("/complete") || url.endsWith("/status")) return { ok: true, status: "ok", mock: true, data: { id: "local-file", parse_status: "ready", mock: true } };
  if (url === "/api/quizzes") {
    return { ok: true, status: "ok", mock: true, data: { label: "模拟", questions: [{ id: "q1", stem: "想多学的时候，应该怎么做？", options: [{ id: "A", text: "加到五件" }, { id: "B", text: "件数不变，做深一点" }] }] } };
  }
  if (url === "/api/me/permissions") return { ok: true, status: "ok", mock: true, data: { permissions: {}, chosen: false } };
  return { ok: true, status: "ok", mock: true, data: {} };
}
