import { afterEach, describe, expect, it, vi } from "vitest";
import { beginSummary, createUpload, formatPages, isProcessing, materialRequest, readNote, readPages, saveNote, statusText, uploadBytes, validatePdf, type MaterialNote, type MaterialStatus } from "./api";

const note: MaterialNote = {
  id: "note-1", lecture_id: "lec-6", title: "项目管理", label: "AI 整理，可以改", edited_by_user: false,
  point_count: 1, term_count: 1, summary_count: 1, mock: false,
  content: { schema_version: 1, file_id: "source-1", summaries: [{ text: "本讲重点", page: 1, quote: "课件原句" }], knowledge_points: [{ id: "kp-1", name: "关键路径", explanation: "解释", page: 1, quote: "课件原句" }], terms: [{ term: "CPM", definition: "关键路径法", page: 1, quote: "课件原句" }] },
};

afterEach(() => { vi.unstubAllGlobals(); });

describe("真实资料请求", () => {
  it("服务端失败直接显示原因，不会返回模拟成功", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { code: "empty_pdf", message: "这份 PDF 没有可提取的文字。" } }), { status: 422 })));
    await expect(materialRequest("/api/files/a/status")).rejects.toThrow("这份 PDF 没有可提取的文字。");
  });
  it("拒绝旧接口的模拟结果", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true, mock: true, data: { parse_status: "ready" } }))));
    await expect(materialRequest("/api/files/a/status")).rejects.toThrow("模拟数据");
  });
  it("断网显示连接错误", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(materialRequest("/api/files/a/status")).rejects.toThrow("没有连上后端");
  });
  it("将 PDF 本身作为二进制上传，并带会话", async () => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true, mock: false, data: { parse_status: "uploaded" } })));
    vi.stubGlobal("fetch", request);
    const file = new File(["%PDF-1.7"], "课程.pdf", { type: "application/pdf" });
    await uploadBytes({ file_id: "a", upload_url: "/api/files/a/raw", method: "PUT" }, file);
    expect(request).toHaveBeenCalledWith("/api/files/a/raw", expect.objectContaining({ body: file, credentials: "include", headers: expect.objectContaining({ "Content-Type": "application/pdf" }) }));
  });
  it("不允许把原件发到其他站点", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true, mock: false, data: { file_id: "a", upload_url: "https://unexpected.example/a", method: "PUT" } }))));
    await expect(createUpload(new File(["pdf"], "a.pdf"))).rejects.toThrow("上传地址不正确");
  });
  it("保存完整修改和标题，保留每条出处", async () => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true, mock: false, data: { ...note, edited_by_user: true } })));
    vi.stubGlobal("fetch", request);
    const saved = await saveNote(note.id, note.content, "我的项目笔记");
    expect(saved.edited_by_user).toBe(true);
    expect(JSON.parse(request.mock.calls[0][1].body)).toEqual({ content: note.content, title: "我的项目笔记" });
  });
  it("保存失败明确报错，调用者的编辑内容不会丢失", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { message: "暂时无法保存" } }), { status: 503 })));
    const content = structuredClone(note.content);
    content.summaries[0].text = "用户正在修改的内容";
    await expect(saveNote(note.id, content, note.title)).rejects.toThrow("暂时无法保存");
    expect(content.summaries[0].text).toBe("用户正在修改的内容");
  });
  it("拒绝拿旧样例字符串数组当成带出处的真实笔记", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true, mock: false, data: { ...note, content: { points: ["旧占位笔记"] } } }))));
    await expect(readNote(note.id)).rejects.toThrow("格式不正确");
  });
  it("笔记引用按原文件版本取页，重试整理不重新上传PDF", async () => {
    const request = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ ok: true, mock: false, data: {} }))));
    vi.stubGlobal("fetch", request);
    await readPages("lec-6", undefined, "original-file");
    expect(request.mock.calls[0][0]).toBe("/api/lectures/lec-6/pages?file_id=original-file");
    await beginSummary("original-file");
    expect(request.mock.calls[1][0]).toBe("/api/files/original-file/summarize");
    expect(request.mock.calls[1][1].method).toBe("POST");
  });
});

describe("课件输入和展示", () => {
  it("拒绝空文件、非 PDF 和超过上限的文件", () => {
    expect(validatePdf({ name: "a.pdf", size: 0 })).toContain("空");
    expect(validatePdf({ name: "a.txt", size: 5 })).toContain("PDF");
    expect(validatePdf({ name: "a.pdf", size: 20 * 1024 * 1024 + 1 })).toContain("20 MB");
    expect(validatePdf({ name: "a.PDF", size: 5 })).toBeNull();
  });
  it("已解析不冒充 AI 已整理", () => {
    expect(statusText({ parse_status: "parsed", page_count: 33 } as MaterialStatus)).toBe("已读取 33 页，可以整理成学习笔记");
  });
  it("读取完成后仍等待AI生成，并明确展示不可用或失败原因", () => {
    const generating = { parse_status: "parsed", page_count: 33, summary_status: "generating" } as MaterialStatus;
    expect(isProcessing(generating)).toBe(true);
    expect(statusText(generating)).toContain("正在整理");
    const unavailable = { ...generating, summary_status: "unavailable", summary_error: { code: "no_key", message: "请在后端配置模型" } } as MaterialStatus;
    expect(isProcessing(unavailable)).toBe(false);
    expect(statusText(unavailable)).toBe("请在后端配置模型");
    expect(statusText({ ...generating, summary_status: "ready", parse_status: "ready", notes_ready: true, note_id: "n1" })).toContain("学习笔记已整理好");
  });
  it("正文到AI的交接阶段继续轮询，不把pending当作处理结束", () => {
    const pending = { parse_status: "parsed", page_count: 33, summary_status: "pending" } as MaterialStatus;
    expect(isProcessing(pending)).toBe(true);
    expect(statusText(pending)).toBe("正文已读取，准备整理学习笔记……");
  });
  it("空白页也保留原来的页码", () => {
    expect(formatPages([{ page: 1, text: "第一节" }, { page: 2, text: "" }, { page: 3, text: "第三节" }])).toBe("【第 1 页】\n第一节\n\n【第 2 页】\n（本页没有可提取文字）\n\n【第 3 页】\n第三节");
  });
});
