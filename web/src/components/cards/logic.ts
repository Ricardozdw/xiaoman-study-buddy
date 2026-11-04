export type CardType = "goal" | "progress" | "summary" | "quiz" | "suggestion" | "reschedule" | "done";

export type StudyCard = {
  id: string;
  type: CardType;
  title: string;
  status: "open" | "done";
  collapsedText: string;
  badge: "模拟" | "AI 整理，可以改";
  lines: string[];
};

export const CARD_LABEL: Record<CardType, string> = {
  goal: "目标拆解",
  progress: "进度",
  summary: "文档摘要",
  quiz: "题目",
  suggestion: "建议",
  reschedule: "重排",
  done: "收工",
};

export function previewCards(): StudyCard[] {
  return [
    {
      id: "card-goal",
      type: "goal",
      title: "先把目标拆开",
      status: "open",
      collapsedText: "目标已记下",
      badge: "模拟",
      lines: ["每天最多三件", "默认强度是正常，大约 30 分钟", "点「好」才生效，也可以撤销"],
    },
    {
      id: "card-progress",
      type: "progress",
      title: "第 6 讲",
      status: "open",
      collapsedText: "第 6 讲已读完",
      badge: "模拟",
      lines: ["样例正文 2 页", "状态：好了"],
    },
    {
      id: "card-summary",
      type: "summary",
      title: "学习文档",
      status: "open",
      collapsedText: "学习文档已收起",
      badge: "AI 整理，可以改",
      lines: ["每天最多三件事", "想多学加强度，不加件数", "没做的不堆到今天"],
    },
    {
      id: "card-quiz",
      type: "quiz",
      title: "练一练",
      status: "open",
      collapsedText: "这组题做完了",
      badge: "模拟",
      lines: ["想多学的时候，应该怎么做？", "A 加到五件", "B 件数不变，做深一点"],
    },
    {
      id: "card-suggestion",
      type: "suggestion",
      title: "今天换成轻松",
      status: "open",
      collapsedText: "已按建议调整",
      badge: "模拟",
      lines: ["还是三件，每件少一点，大约 15 分钟。", "点了才生效"],
    },
    {
      id: "card-reschedule",
      type: "reschedule",
      title: "回来之后怎么补",
      status: "open",
      collapsedText: "已选好一种补法",
      badge: "模拟",
      lines: ["只看今天的三件", "把落下的讲放进这周的复习", "先休息一阵"],
    },
    {
      id: "card-done",
      type: "done",
      title: "今天三件都做完了",
      status: "open",
      collapsedText: "今天收工",
      badge: "模拟",
      lines: ["明天仍是三件", "可以打开看板看看变化"],
    },
  ];
}

export function collapseCard(card: StudyCard): StudyCard {
  return { ...card, status: "done" };
}

export function reopenCard(card: StudyCard): StudyCard {
  return { ...card, status: "open" };
}
