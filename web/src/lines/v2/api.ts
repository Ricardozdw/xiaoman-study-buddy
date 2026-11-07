// V2 大纲接口。404 或连不上时，api() 会落到本地假数据；那种结果一律当成 V2 关闭或失败，不当真。
import { api } from "../../api/client";
import { isIsoDate, type DraftBody, type UnitInput } from "./logic";

export type { UnitInput };

export type OutlineUnit = { no?: number; title: string; points: string[] };
export type OutlineView = {
  id: string;
  title: string;
  status: string;
  units: OutlineUnit[];
  stages: { no: number; title: string; unit_nos: number[]; started_at?: string }[];
  label: string;
  mock: boolean;
};

type Fail = { ok: false; message: string };
type OutlineResult = { ok: true; outline: OutlineView } | Fail;

function asOutline(data: Partial<OutlineView> | undefined): OutlineView | null {
  if (!data || typeof data.id !== "string" || !Array.isArray(data.units) || typeof data.label !== "string") return null;
  return data as OutlineView;
}

/** 404 或连不上 = 关闭。只认真实接口里的 enabled: true。 */
export async function getStatus(): Promise<boolean> {
  const result = await api<{ enabled?: boolean }>("/api/v2/status");
  return result.source === "api" && result.envelope.ok !== false && result.envelope.data?.enabled === true;
}

export async function getPlanDate(): Promise<string | null> {
  const result = await api<{ date?: string }>("/api/plan/today");
  const date = result.envelope.data?.date;
  if (result.source !== "api" || typeof date !== "string" || !isIsoDate(date)) return null;
  return date;
}

export async function draftOutline(body: DraftBody): Promise<OutlineResult> {
  const payload: DraftBody = { ...body };
  if (!payload.deadline) delete payload.deadline;
  const result = await api<OutlineView>("/api/v2/outline/draft", { method: "POST", body: JSON.stringify(payload) });
  const outline = result.source === "api" && result.envelope.ok !== false ? asOutline(result.envelope.data) : null;
  if (!outline) return { ok: false, message: "大纲没能生成，请检查连接后再试。" };
  return { ok: true, outline };
}

export async function patchOutline(id: string, units: UnitInput[]): Promise<OutlineResult> {
  const result = await api<OutlineView>(`/api/v2/outline/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ units }),
  });
  const outline = result.source === "api" && result.envelope.ok !== false ? asOutline(result.envelope.data) : null;
  if (!outline) return { ok: false, message: "没能保存修改，请检查单元后再试。" };
  return { ok: true, outline };
}

export async function acceptOutline(id: string): Promise<OutlineResult> {
  const result = await api<{ outline?: OutlineView }>(`/api/v2/outline/${encodeURIComponent(id)}/accept`, { method: "POST" });
  const outline = result.source === "api" && result.envelope.ok !== false ? asOutline(result.envelope.data?.outline) : null;
  if (!outline) return { ok: false, message: "还没能按这份大纲安排，请再试一次。" };
  return { ok: true, outline };
}

export async function undoOutline(id: string): Promise<{ ok: true } | Fail> {
  const result = await api<{ plan_today?: { needs_setup?: boolean } }>(`/api/v2/outline/${encodeURIComponent(id)}/undo`, { method: "POST" });
  if (result.source !== "api" || result.envelope.ok === false) return { ok: false, message: "今天没能撤销，可以稍后再试。" };
  return { ok: true };
}
