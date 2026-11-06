import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Shell } from "../../components/Shell";

describe("资料线在软件中的入口", () => {
  it("未读取真实资料前提供上传入口，不展示已经读完或生成笔记的假结果", () => {
    const page = renderToStaticMarkup(createElement(Shell));
    expect(page).toContain('aria-label="交资料"');
    expect(page).toContain('aria-label="选择 PDF 文件"');
    expect(page).toContain("正在读取学习笔记");
    expect(page).not.toContain("样例正文 2 页");
    expect(page).not.toContain("学习笔记已整理好");
    expect(page).not.toContain("笔记摘要");
    expect(page).not.toContain("打开全文");
  });
});
