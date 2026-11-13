import { useState } from "react";
import { fetchWithRetry } from "../api/client";
import { Avatar } from "./Avatar";
import { Button } from "./ui";

export type SessionState = { state: "checking" | "ok" | "need"; invite: boolean };

/** 进页面先确认会话：线上开了邀请码、又没登录时，后端回 401 invite_required。 */
export async function checkSession(): Promise<SessionState> {
  try {
    const response = await fetchWithRetry("/api/session", { method: "POST", credentials: "include" });
    if (response.status === 401) {
      const body = await response.json().catch(() => ({}));
      if (body?.detail?.code === "invite_required") return { state: "need", invite: true };
    }
    const body = response.ok ? await response.json().catch(() => ({})) : {};
    return { state: "ok", invite: String(body?.data?.user_id || "").startsWith("u_inv_") };
  } catch {
    return { state: "ok", invite: false }; // 连不上后端时交给主页面按离线处理
  }
}

export async function logout() {
  try { await fetch("/api/session/logout", { method: "POST", credentials: "include" }); } catch { /* 忽略 */ }
  window.location.reload();
}

/** 输入邀请码：一个码就是一个账号，手机、电脑用同一个码看到同一份进度。 */
export function InviteGate({ onDone }: { onDone: () => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    if (!code.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/session/invite", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      const body = await response.json().catch(() => ({}));
      if (response.ok) { onDone(); return; }
      setError(body?.detail?.message || "没能登录，请稍后再试");
    } catch {
      setError("网络不太好，请稍后再试");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="invite-gate">
      <form className="invite-card" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <Avatar mood="wave" size={88} />
        <h1>小满学习搭子</h1>
        <p className="aux">现在是邀请试用，输入邀请码就能开始。</p>
        <input
          aria-label="邀请码"
          value={code}
          autoFocus
          autoCapitalize="characters"
          autoComplete="off"
          spellCheck={false}
          maxLength={64}
          placeholder="例如 XM-XXXX-XXXX"
          onChange={(event) => setCode(event.target.value)}
        />
        {error && <p className="invite-error" role="alert">{error}</p>}
        <Button type="submit" variant="primary" disabled={busy || !code.trim()}>{busy ? "正在进入…" : "进入"}</Button>
        <p className="aux">同一个邀请码在手机和电脑上登录，看到的是同一份学习进度。</p>
      </form>
    </main>
  );
}
