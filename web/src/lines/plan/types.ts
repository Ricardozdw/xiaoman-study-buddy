// 计划线自己用的接口类型（只加在本文件夹，不改共用的 api/types.ts）。

export type PlanOption = { id: string; label: string; needs?: "exam_date" };

export type PlanCard = {
  id: string;
  kind: string;
  type: "goal" | "suggestion" | "reschedule" | "done";
  title: string;
  lines: string[];
  badge: string;
  collapsed_text: string;
  decline_label?: string;
  revise_label?: string;
  options: PlanOption[];
  status: string;
  defaults_used?: string[];
};

export type DoneCard = {
  type: "done";
  title: string;
  lines: string[];
  badge: string;
  options: { id: string; label: string }[];
};

export type QuickReply = { text: string; action: "goal_setup" | "adjust" | "start_task" | "tomorrow" | "dashboard"; task_id?: string };

export type PlanTodayExt = {
  date: string;
  intensity: string;
  needs_setup: boolean;
  card: PlanCard | null;
  undoable: { id: string; kind: string; text: string } | null;
  done_card: DoneCard | null;
  quick_replies: QuickReply[];
  all_done: boolean;
};

export type Opening = { greeting: string; source: "ai" | "rule"; label: string };

export type GoalQuestion = {
  key: string;
  text: string;
  quick_replies: string[];
  skip_label: string;
  default_text: string;
};

export type DemoClock = { enabled: boolean; offset_days: number; today: string; real_today: string; label: string };
