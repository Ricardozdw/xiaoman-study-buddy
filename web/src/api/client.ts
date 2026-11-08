import { mockFor } from "./mocks";
import type { Envelope } from "./types";

// 线上服务闲置会缩到 0 个实例，第一次访问要等它启动（冷启动），期间网关会回 502/503/504 或直接断开。
// 只读请求遇到这类“暂时性”失败时等一等再试（共约 15 秒），不要马上退回样例数据，免得新用户看到假内容。
// 会改数据的请求（POST/PATCH/…）不重试，避免重复提交。
const TRANSIENT = new Set([502, 503, 504]);
const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000];
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function fetchWithRetry(path: string, init: RequestInit, retries = RETRY_DELAYS_MS): Promise<Response> {
  const method = (init.method || "GET").toUpperCase();
  const idempotent = method === "GET" || method === "HEAD" || path === "/api/session";
  for (let attempt = 0; ; attempt += 1) {
    try {
      const response = await fetch(path, init);
      if (!idempotent || !TRANSIENT.has(response.status) || attempt >= retries.length) return response;
    } catch (error) {
      if (!idempotent || attempt >= retries.length) throw error;
    }
    await sleep(retries[attempt]);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<{ envelope: Envelope<T>; source: "api" | "mock" }> {
  const method = (init.method || "GET").toUpperCase();
  try {
    const response = await fetchWithRetry(path, {
      ...init,
      credentials: "include",
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(init.headers || {}),
      },
    });
    if (!response.ok) throw new Error(String(response.status));
    const envelope = (await response.json()) as Envelope<T>;
    return { envelope, source: "api" };
  } catch {
    return { envelope: mockFor(path, method) as Envelope<T>, source: "mock" };
  }
}

export async function ensureSession(): Promise<boolean> {
  try {
    const response = await fetchWithRetry("/api/session", { method: "POST", credentials: "include" });
    return response.ok;
  } catch {
    return false;
  }
}

export async function readStream(path: string, body: unknown, onDelta?: (text: string) => void): Promise<string> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) throw new Error(String(response.status));
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let text = "";
  while (true) {
    const step = await reader.read();
    if (step.done) break;
    buffer += decoder.decode(step.value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      const line = chunk.split("\n").find((item) => item.startsWith("data:"));
      if (!line) continue;
      const data = line.slice(5).trim();
      if (data === "[DONE]") return text;
      const parsed = JSON.parse(data) as { delta?: string };
      text += parsed.delta || "";
      onDelta?.(text);
    }
  }
  return text;
}
