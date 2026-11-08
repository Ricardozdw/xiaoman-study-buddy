import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchWithRetry } from "./client";

afterEach(() => vi.unstubAllGlobals());
const res = (status: number) => new Response("{}", { status });

describe("冷启动时的重试", () => {
  it("只读请求遇到 502/503/504 或断网会再试，成功即返回", async () => {
    const f = vi.fn().mockRejectedValueOnce(new TypeError("network")).mockResolvedValueOnce(res(503)).mockResolvedValueOnce(res(200));
    vi.stubGlobal("fetch", f);
    const r = await fetchWithRetry("/api/plan/today", {}, [0, 0, 0]);
    expect(r.status).toBe(200);
    expect(f).toHaveBeenCalledTimes(3);
  });

  it("会改数据的请求不重试（避免重复提交）", async () => {
    const f = vi.fn().mockResolvedValue(res(503));
    vi.stubGlobal("fetch", f);
    expect((await fetchWithRetry("/api/attempts", { method: "POST" }, [0, 0])).status).toBe(503);
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("建会话是幂等的，也重试；业务错误（如 401/404）不重试", async () => {
    const f = vi.fn().mockResolvedValueOnce(res(502)).mockResolvedValueOnce(res(200));
    vi.stubGlobal("fetch", f);
    expect((await fetchWithRetry("/api/session", { method: "POST" }, [0])).status).toBe(200);
    const g = vi.fn().mockResolvedValue(res(401));
    vi.stubGlobal("fetch", g);
    expect((await fetchWithRetry("/api/plan/today", {}, [0, 0])).status).toBe(401);
    expect(g).toHaveBeenCalledTimes(1);
  });

  it("一直失败就按次数停下", async () => {
    const f = vi.fn().mockResolvedValue(res(504));
    vi.stubGlobal("fetch", f);
    expect((await fetchWithRetry("/api/plan/today", {}, [0, 0])).status).toBe(504);
    expect(f).toHaveBeenCalledTimes(3);
  });
});
