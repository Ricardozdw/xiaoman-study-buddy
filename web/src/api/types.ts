export type Intensity = "light" | "normal" | "sprint";

export type Task = {
  id: string;
  kind: "learn" | "practice" | "repair";
  kind_label: string;
  title: string;
  status: "todo" | "done";
  done_when: string;
  minutes?: number;
};

export type PlanToday = {
  date: string;
  intensity: Intensity;
  intensity_label: string;
  minutes: number;
  tasks: Task[];
  label: string;
};

export type NoteItem = {
  id: string;
  lecture_id: string;
  title: string;
  edited_by_user: boolean;
  label: string;
  point_count?: number;
  content?: { points?: string[]; terms?: string[]; label?: string };
};

export type Dashboard = {
  range: string;
  studied_days: number;
  attempt_count: number;
  mistakes_due: number;
  lectures: { id: string; title: string; mastery: number }[];
  files: { id: string; filename: string; parse_status: string }[];
  goal_progress: number;
  llm_calls: number;
  label: string;
  note: string;
};

export type Suggestion = {
  id: string;
  status: string;
  suggestion: { title?: string; body?: string; label?: string };
};

export type PermissionSwitch = {
  key: string;
  label: string;
  value: boolean | null;
  placeholder?: boolean;
};

export type Permissions = {
  chosen: boolean;
  note: string;
  switches: PermissionSwitch[];
  permissions: Record<string, boolean | null>;
};

export type Envelope<T> = {
  ok: boolean;
  status: string;
  mock: boolean;
  data: T;
};
