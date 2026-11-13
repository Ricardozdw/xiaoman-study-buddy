import { afterEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { InviteGate, checkSession } from "./InviteGate";

afterEach(() => vi.unstubAllGlobals());
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("邀请码登录", () => {
  it("后端要求邀请码时进入输入页", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(401, { detail: { code: "invite_required", message: "请输入邀请码" } })));
    expect(await checkSession()).toEqual({ state: "need", invite: true });
  });

  it("已登录的邀请码账号直接进，并允许退出登录；匿名账号（本地）不显示退出", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(200, { ok: true, data: { user_id: "u_inv_abc" } })));
    expect(await checkSession()).toEqual({ state: "ok", invite: true });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(200, { ok: true, data: { user_id: "u_123" } })));
    expect(await checkSession()).toEqual({ state: "ok", invite: false });
  });

  it("其它 401（比如会话坏了）不当成要邀请码", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(401, { detail: { code: "unauthenticated" } })));
    expect((await checkSession()).state).toBe("ok");
  });

  it("输入页有邀请码输入框和说明", () => {
    const html = renderToStaticMarkup(createElement(InviteGate, { onDone: () => {} }));
    expect(html).toContain('aria-label="邀请码"');
    expect(html).toContain("同一个邀请码在手机和电脑上登录");
  });
});
