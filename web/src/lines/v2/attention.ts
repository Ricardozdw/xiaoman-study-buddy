/**
 * 首屏（参考灵光）：大日期 + 一句话状态 + 最多两张“需要你关注”的卡。
 * 只读已有的计划、大纲、错题和“没做完的练习”，不调模型。
 */
export type AttnTask = {
  id: string;
  kind: "learn" | "practice" | "repair" | "exam";
  kind_label: string;
  title: string;
  status: "todo" | "done";
  minutes?: number;
  ref?: { lecture_no?: number; mistake_ids?: string[] } & Record<string, unknown>;
};

export type AttnItem = {
  key: string;
  kind: AttnTask["kind"];
  title: string;
  sub: string;
  action: "start" | "resume" | "summary";
  taskId?: string;
};

export type AttnInput = {
  needsGoal: boolean;
  goalDone: boolean;
  tasks: AttnTask[];
  stageReady?: number | null; // 可以考的阶段号
  resumeLectureNo?: number | null; // 有没做完的练习时，它属于第几讲
  totalDays?: number;
};

export function headline(input: AttnInput): { title: string; sub: string } {
  if (input.needsGoal) return { title: "先定个学习目标", sub: "小满在这儿，陪你慢慢学" };
  if (input.goalDone) return { title: "这个目标学完了", sub: "辛苦了，可以定下一个目标" };
  const left = input.tasks.filter((task) => task.status !== "done");
  if (!input.tasks.length) return { title: "今天还没有安排", sub: "跟小满说说今天想学点什么" };
  if (!left.length) return { title: "今天的都做完了", sub: input.totalDays ? `累计学了 ${input.totalDays} 天，明天见` : "明天见" };
  const minutes = left.reduce((sum, task) => sum + (task.minutes || 0), 0);
  const steps = left.map((task) => task.kind_label).join(" → ");
  return { title: `今天还有 ${left.length} 件事`, sub: minutes ? `${steps} · 大约 ${minutes} 分钟` : steps };
}

export function attentionItems(input: AttnInput): AttnItem[] {
  if (input.needsGoal || input.goalDone || !input.tasks.length) return [];
  const items: AttnItem[] = [];
  const todo = input.tasks.filter((task) => task.status !== "done");
  const practice = todo.find((task) => task.kind === "practice");
  const exam = todo.find((task) => task.kind === "exam");

  if (input.resumeLectureNo && practice) {
    items.push({ key: "resume", kind: "practice", title: "上次的练习还没做完，接着做", sub: `练一练 · 第 ${input.resumeLectureNo} 讲`, action: "resume", taskId: practice.id });
  }
  if (exam && input.stageReady) {
    items.push({ key: "stage", kind: "exam", title: `阶段 ${input.stageReady} 测验可以考了`, sub: `今天的考试就是它${exam.minutes ? ` · 约 ${exam.minutes} 分钟` : ""}`, action: "start", taskId: exam.id });
  } else if (exam && exam.ref?.mistake_ids?.length) {
    items.push({ key: "mistakes", kind: "exam", title: `之前错了 ${exam.ref.mistake_ids.length} 题，今天考试先考它们`, sub: `考试 · ${exam.title}`, action: "start", taskId: exam.id });
  }
  const next = todo.find((task) => !items.some((item) => item.taskId === task.id));
  if (next && items.length < 2) {
    items.push({ key: `next-${next.id}`, kind: next.kind, title: next.title, sub: `${next.kind_label}${next.minutes ? ` · 约 ${next.minutes} 分钟` : ""}`, action: "start", taskId: next.id });
  }
  // 全做完时不再出卡：标题已经说了，下面紧跟着就是“今天完成”卡。
  return items.slice(0, 2);
}
