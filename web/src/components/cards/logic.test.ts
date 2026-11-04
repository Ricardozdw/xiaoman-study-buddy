import { describe, expect, it } from "vitest";
import { mockPlan } from "../../api/mocks";
import { CARD_LABEL, collapseCard, previewCards, reopenCard } from "./logic";

describe("今天三件", () => {
  it("三件来自三个来源", () => {
    expect(mockPlan.tasks.map((task) => task.kind)).toEqual(["learn", "practice", "repair"]);
    expect(new Set(mockPlan.tasks.map((task) => task.kind_label))).toEqual(new Set(["学新的", "练一练", "补一补"]));
  });
});

describe("卡片", () => {
  it("七种都能收成一行再展开", () => {
    const cards = previewCards();
    expect(cards.map((card) => card.type)).toEqual(["goal", "progress", "summary", "quiz", "suggestion", "reschedule", "done"]);
    expect(Object.keys(CARD_LABEL)).toHaveLength(7);
    for (const card of cards) {
      const done = collapseCard(card);
      expect(done.status).toBe("done");
      expect(done.collapsedText.length).toBeGreaterThan(0);
      expect(reopenCard(done).status).toBe("open");
    }
  });
});
