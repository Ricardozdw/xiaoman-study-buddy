import { mockFor } from "./mocks";
import type { Envelope } from "./types";

export async function api<T>(path: string, init: RequestInit = {}): Promise<{ envelope: Envelope<T>; source: "api" | "mock" }> {
  const method = (init.method || "GET").toUpperCase();
  try {
    const response = await fetch(path, {
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
    const response = await fetch("/api/session", { method: "POST", credentials: "include" });
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
