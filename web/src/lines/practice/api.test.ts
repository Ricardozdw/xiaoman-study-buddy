import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, request } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("练习请求不把失败当成成功", () => {
  it("上传发送文件本体，由浏览器设置 multipart 边界", async () => {
    const fake = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true, data: { page_count: 5 } })));
    vi.stubGlobal("fetch", fake);
    const file = new FormData(); file.append("file", new Blob(["%PDF-test"]), "lecture.pdf");
    await request("/api/practice/materials", file);
    expect(fake.mock.calls[0][1].body).toBe(file);
    expect(fake.mock.calls[0][1].headers).toBeUndefined();
  });
  it("提交携带同源会话和答案", async () => {
    const fake = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true, data: { correct: false } })));
    vi.stubGlobal("fetch", fake);
    expect(await request("/api/attempts", { answer: "A" })).toEqual({ correct: false });
    expect(fake.mock.calls[0][1]).toMatchObject({ method: "POST", credentials: "include", body: '{"answer":"A"}' });
  });
  it("保留 404 状态，让恢复流程能识别不存在的会话", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { message: "没有找到" } }), { status: 404 })));
    await expect(request("/api/quizzes/missing")).rejects.toMatchObject({ status: 404, message: "没有找到" });
  });
  it("网络失败明确报错，不返回假作答结果", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(request("/api/attempts", {})).rejects.toBeInstanceOf(ApiError);
  });
  it("代理返回非 JSON 错误时仍给出可读提示", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Bad gateway", { status: 502 })));
    await expect(request("/api/attempts", {})).rejects.toMatchObject({ status: 502, message: expect.stringContaining("重试") });
  });
});
