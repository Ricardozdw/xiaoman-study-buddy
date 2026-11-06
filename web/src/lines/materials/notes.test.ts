import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { NoteContent } from "./api";
import { OriginalView } from "./NoteView";
import { cloneNoteContent, contentForSave, noteDraftError, quoteParts } from "./notes";

const content: NoteContent = {
  schema_version: 1, file_id: "f1", points: ["原重点"],
  summaries: [{ text: "原重点", page: 3, quote: "来源原句" }],
  knowledge_points: [{ id: "kp-1", name: "知识点", explanation: "解释", page: 4, quote: "知识点原句" }],
  terms: [{ term: "术语", definition: "定义", page: 5, quote: "术语原句" }],
};

describe("笔记修改", () => {
  it("草稿修改不会提前污染已保存内容和来源", () => {
    const draft = cloneNoteContent(content);
    draft.summaries[0].text = "用户重点";
    draft.knowledge_points[0].explanation = "用户解释";
    draft.terms[0].definition = "用户定义";
    const saved = contentForSave(draft);
    expect(content.summaries[0].text).toBe("原重点");
    expect(content.knowledge_points[0].explanation).toBe("解释");
    expect(content.terms[0].definition).toBe("定义");
    expect(saved.points).toEqual(["用户重点"]);
    expect(saved.knowledge_points[0]).toEqual({ id: "kp-1", name: "知识点", explanation: "用户解释", page: 4, quote: "知识点原句" });
    expect(saved.file_id).toBe("f1");
  });
  it("用户不能意外保存空的标题或知识点解释", () => {
    expect(noteDraftError(" ", content)).toContain("标题");
    const draft = cloneNoteContent(content);
    draft.knowledge_points[0].explanation = " ";
    expect(noteDraftError("笔记", draft)).toContain("知识点");
  });
});

describe("原文引用", () => {
  it("高亮保留PDF实际换行和全角字符，不改写原文", () => {
    const text = "前文：ＡＢＣ 是\n关键路径。后文";
    const parts = quoteParts(text, "ABC是关键路径");
    expect(parts).toEqual({ before: "前文：", match: "ＡＢＣ 是\n关键路径", after: "。后文" });
    expect(parts.before + parts.match + parts.after).toBe(text);
  });
  it("不存在的引文不会高亮其他内容", () => {
    expect(quoteParts("真实课件", "不存在的原句")).toEqual({ before: "真实课件", match: "", after: "" });
  });
  it("课件文本以安全文本呈现，不能执行HTML", () => {
    const html = renderToStaticMarkup(createElement(OriginalView, { text: "<script>alert('x')</script>原句", citation: { page: 1, quote: "原句" } }));
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
    expect(html).toContain("<mark>原句</mark>");
  });
});
