import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { PathEntry, PathPanel } from "./PathPanel";
import type { OutlineView } from "./api";

const outline = {
  id: "o1", title: "AI产品经理", status: "accepted", label: "", mock: false, learned_up_to: 3,
  units: Array.from({ length: 6 }, (_, i) => ({ no: i + 1, title: `第${i + 1}个主题`, points: [`要点${i + 1}`] })),
  checkpoints: [{ stage_no: 1, after_unit: 4, status: "locked" }],
} as unknown as OutlineView;

describe("学习路径", () => {
  it("左栏只放一行入口：进度和下一站", () => {
    const html = renderToStaticMarkup(createElement(PathEntry, { outline, onOpen: () => {} }));
    expect(html).toContain("学了 3 / 6 讲");
    expect(html).toContain("下一站：第 4 讲");
    expect(html).not.toContain("要点1");
  });

  it("完整路径：学过的可重看，今天展开要点并能继续学，没学的只显示标题，阶段测验是关卡", () => {
    const html = renderToStaticMarkup(createElement(PathPanel, { outline, currentNo: 4, onReview: () => {}, onContinue: () => {} }));
    expect(html).toContain("重看");
    expect(html).toContain("继续学");
    expect(html).toContain("要点4");      // 今天这一讲的要点展开
    expect(html).not.toContain("要点5");  // 没学的默认不展开
    expect(html).toContain("阶段 1 测验");
  });

  it("今天这一讲学完了：显示重看，不再显示继续学", () => {
    const html = renderToStaticMarkup(createElement(PathPanel, { outline: { ...outline, learned_up_to: 4 } as OutlineView, currentNo: 4, onReview: () => {}, onContinue: () => {} }));
    expect(html).toContain("今天学过");
    expect(html).not.toContain("继续学");
  });
});
