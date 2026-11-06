// 正式资料请求不降级成假数据；出错时交给上传卡显示和重试。
export type MaterialStatus = {
  id: string;
  filename: string;
  lecture_id: string;
  parse_status: "awaiting_upload" | "uploaded" | "reading" | "parsed" | "ready" | "failed";
  page_count: number;
  processed_pages: number;
  error: { code: string; message: string } | null;
  can_retry: boolean;
  mock: false;
  reused?: boolean;
  summary_status?: "not_started" | "pending" | "generating" | "ready" | "failed" | "unavailable";
  summary_error?: { code: string; message: string } | null;
  note_id?: string | null;
  notes_ready?: boolean;
};

export type MaterialPage = { lecture_id: string; page: number; text: string; mock: false };
export type Citation = { page: number; quote: string };
export type SummaryItem = Citation & { text: string };
export type KnowledgePoint = Citation & { id?: string; name: string; explanation: string };
export type TermItem = Citation & { term: string; definition: string };
export type NoteContent = {
  schema_version: number;
  file_id: string;
  summaries: SummaryItem[];
  knowledge_points: KnowledgePoint[];
  terms: TermItem[];
  points?: string[];
  [key: string]: unknown;
};
export type MaterialNote = {
  id: string;
  lecture_id: string;
  title: string;
  label: string;
  edited_by_user: boolean;
  point_count: number;
  term_count: number;
  summary_count: number;
  mock: false;
  content: NoteContent;
};
type UploadTarget = { file_id: string; upload_url: string; method: string };

function messageFrom(value: unknown): string | undefined {
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object") return undefined;
  const item = value as Record<string, unknown>;
  if (typeof item.message === "string") return item.message;
  return messageFrom(item.detail) || messageFrom(item.error);
}

export async function materialRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    const timeout = AbortSignal.timeout(30_000);
    const signal = init.signal ? AbortSignal.any([init.signal, timeout]) : timeout;
    response = await fetch(path, { ...init, signal, credentials: "include", headers: { Accept: "application/json", ...init.headers } });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    if (error instanceof Error && error.name === "TimeoutError") throw new Error("资料请求超时，文件可能已保存，请稍后重试。");
    throw new Error("没有连上后端，请确认服务已启动后重试。");
  }
  let body: unknown;
  try { body = await response.json(); }
  catch { throw new Error(response.ok ? "后端返回的资料数据格式不正确。" : `资料请求失败（${response.status}），请重试。`); }
  if (!response.ok) throw new Error(messageFrom(body) || `资料请求失败（${response.status}），请重试。`);
  if (!body || typeof body !== "object") throw new Error("后端返回的资料数据格式不正确。");
  const envelope = body as { ok?: boolean; mock?: boolean; data?: T };
  if (envelope.ok !== true || envelope.mock !== false || envelope.data === undefined) {
    throw new Error(messageFrom(body) || "真实资料接口尚未接通，不能把模拟数据当作上传结果。");
  }
  return envelope.data;
}

export function validatePdf(file: Pick<File, "name" | "size">): string | null {
  if (!file.name.toLowerCase().endsWith(".pdf")) return "请上传文字版 PDF 文件。";
  if (file.size === 0) return "这个文件是空的，请重新选择。";
  if (file.size > 20 * 1024 * 1024) return "PDF 超过 20 MB，请选择小一些的课件。";
  return null;
}

export async function createUpload(file: File, signal?: AbortSignal): Promise<UploadTarget> {
  const target = await materialRequest<UploadTarget>("/api/files/upload-url", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filename: file.name, mime: "application/pdf" }), signal });
  // 上传只交给本应用同源后端，防止接口配置错误把课件传到外站。
  if (!target.file_id || target.method !== "PUT" || target.upload_url !== `/api/files/${target.file_id}/raw`) throw new Error("后端返回的上传地址不正确。");
  return target;
}

export const uploadBytes = (target: UploadTarget, file: File, signal?: AbortSignal) =>
  materialRequest<MaterialStatus>(target.upload_url, { method: "PUT", headers: { "Content-Type": "application/pdf" }, body: file, signal });

export const beginParsing = (fileId: string, lectureId: string, signal?: AbortSignal) =>
  materialRequest<MaterialStatus>(`/api/files/${encodeURIComponent(fileId)}/complete`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lecture_id: lectureId }), signal });

export const readStatus = (fileId: string, signal?: AbortSignal) =>
  materialRequest<MaterialStatus>(`/api/files/${encodeURIComponent(fileId)}/status`, { signal });

export const listFiles = (signal?: AbortSignal) => materialRequest<{ items: MaterialStatus[] }>("/api/files", { signal });

export const readPages = (lectureId: string, signal?: AbortSignal, fileId?: string) =>
  materialRequest<{ pages: MaterialPage[] }>(`/api/lectures/${encodeURIComponent(lectureId)}/pages${fileId ? `?file_id=${encodeURIComponent(fileId)}` : ""}`, { signal });

export const beginSummary = (fileId: string, signal?: AbortSignal) =>
  materialRequest<MaterialStatus>(`/api/files/${encodeURIComponent(fileId)}/summarize`, { method: "POST", signal });

function validNote(value: unknown): value is MaterialNote {
  if (!value || typeof value !== "object") return false;
  const note = value as Partial<MaterialNote>;
  const content = note.content;
  const cited = (item: unknown) => !!item && typeof item === "object" && Number.isInteger((item as Citation).page) && (item as Citation).page > 0 && typeof (item as Citation).quote === "string";
  return typeof note.id === "string" && typeof note.lecture_id === "string" && typeof note.title === "string" && note.mock === false && !!content && typeof content.file_id === "string" && !!content.file_id &&
    Array.isArray(content.summaries) && content.summaries.every((item) => cited(item) && typeof item.text === "string") &&
    Array.isArray(content.knowledge_points) && content.knowledge_points.every((item) => cited(item) && typeof item.name === "string" && typeof item.explanation === "string") &&
    Array.isArray(content.terms) && content.terms.every((item) => cited(item) && typeof item.term === "string" && typeof item.definition === "string");
}

export async function readNote(noteId: string, signal?: AbortSignal): Promise<MaterialNote> {
  const note = await materialRequest<unknown>(`/api/notes/${encodeURIComponent(noteId)}`, { signal });
  if (!validNote(note)) throw new Error("笔记内容格式不正确，请重试加载。");
  return note;
}

export async function saveNote(noteId: string, content: NoteContent, title: string, signal?: AbortSignal): Promise<MaterialNote> {
  const note = await materialRequest<unknown>(`/api/notes/${encodeURIComponent(noteId)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content, title }), signal });
  if (!validNote(note)) throw new Error("笔记保存结果格式不正确，请重新打开笔记确认。");
  return note;
}

export const isProcessing = (status: MaterialStatus) =>
  status.parse_status === "reading" || status.parse_status === "uploaded" || status.summary_status === "pending" || status.summary_status === "generating";

export function statusText(status: MaterialStatus): string {
  if (status.summary_status === "pending") return "正文已读取，准备整理学习笔记……";
  if (status.summary_status === "generating") return `已读取 ${status.page_count} 页，正在整理学习笔记……`;
  if (status.notes_ready && status.note_id) return `学习笔记已整理好，来自 ${status.page_count} 页课件`;
  if (status.summary_status === "failed" || status.summary_status === "unavailable") return status.summary_error?.message || "正文已保存，笔记整理暂未完成，可以稍后重试。";
  switch (status.parse_status) {
    case "awaiting_upload": return "等待上传文件";
    case "uploaded": return "文件已保存，准备读取";
    case "reading": return status.page_count ? `正在读取，第 ${status.processed_pages}／${status.page_count} 页` : "正在打开 PDF";
    case "parsed": return `已读取 ${status.page_count} 页，可以整理成学习笔记`;
    case "ready": return "学习笔记已整理好";
    case "failed": return status.error?.message || "读取失败，可以重试。";
  }
}

export const formatPages = (pages: Pick<MaterialPage, "page" | "text">[]) =>
  pages.map((page) => `【第 ${page.page} 页】\n${page.text || "（本页没有可提取文字）"}`).join("\n\n");
