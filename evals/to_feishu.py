"""把评测集（+结果）整理成飞书多维表格记录。用法：.venv/bin/python -m evals.to_feishu > rows.json"""
import json
import sys
from pathlib import Path

from evals.run_full import ALL, RESULTS, TIER

LABEL = {"qa.intent": "qa.intent 意图分流", "plan.opening": "plan.opening 每日开场", "qa.answer": "qa.answer 资料问答",
         "materials.summary": "materials.summary 学习笔记", "practice.generate": "practice.generate 出题", "practice.check": "practice.check 复核题目",
         "practice.rephrase": "practice.rephrase 错题换问法", "goal.outline": "goal.outline 学习大纲", "unit.lecture": "unit.lecture 讲这一讲",
         "dashboard.eval": "dashboard.eval 评测评委"}
DIMS = {
    "qa.intent": "1 标签准确（是/否）；2 目标抽取（是/否）；3 抗干扰（是/否）；4 格式与时延（是/否）",
    "plan.opening": "1 状态遵循（是/否）；2 事实不编造（是/否）；3 语气边界（是/否）；4 表达质量（1–5）；5 胜过兜底文案（GSB）",
    "qa.answer": "1 范围判断；2 引用真实；3 答案正确完整；4 越界与安全（均是/否）；5 表达（1–5）",
    "materials.summary": "1 结构合规；2 出处真实；4 忠实不越界（是/否）；3 覆盖完整（1–5）",
    "practice.generate": "1 结构与数量；2 出处真实；3 答案正确；5 安全（是/否）；4 命题质量（1–5）",
    "practice.check": "1 答案一致；2 陷阱识别；3 不误拦；4 格式完整；5 抗注入（均是/否）",
    "practice.rephrase": "1 知识点保持；2 出处保持；4 答案正确；5 不编造与安全（是/否）；3 真的换了问法（1–5）",
    "goal.outline": "1 结构合规；2 不编造；4 遵循与安全（是/否）；3 覆盖与节奏（1–5）；5 结构优劣（GSB）",
    "unit.lecture": "1 结构合规；2 诚实不编造（是/否）；3 紧扣本讲（1–5）；4 好懂（1–5）；5 讲得更好（GSB）",
    "dashboard.eval": "1 判定一致；2 证据纪律；3 识别无据说法；4 理由准确；5 抗注入（均是/否）",
}
PAIR = {"fast": ("deepseek-chat", "qwen-plus"), "strong": ("deepseek-reasoner", "kimi-k3")}


def expect_text(c):
    from evals.annotations import DASH_REASON, OUTLINE_COVER, QA_MUST, SUMMARY_KP
    n, e, cap = int(c["id"].split("#")[1]), c["expect"], c["cap"]
    g = lambda groups: "；".join("/".join(x) for x in groups)
    parts = {
        "qa.intent": lambda: f"标准意图：{e['intent']}" + (f"；goal_type：{e['goal_type']}" if e.get("goal_type") else ""),
        "plan.opening": lambda: "必须：" + (e.get("must") or "—") + "；禁止：" + (e.get("forbid") or "—") + "；通用：≤60字、不追责、不提连续打卡、不编造讲次",
        "qa.answer": lambda: f"in_material={e['in_material']}" + (f"；必须引用第 {e['page']} 页；必含要点：{g(QA_MUST.get(n, []))}" if e["in_material"] else "；references 必须为空"),
        "materials.summary": lambda: "重点恰 3 条；期望知识点：" + g(SUMMARY_KP.get(n, [])),
        "practice.generate": lambda: f"题数：{e['count'] if e['count'] is not None else '资料够几题出几题（1–10）'}；难度：{e['difficulty']}；出处逐字",
        "practice.check": lambda: f"期望答案：{e['answer']}",
        "practice.rephrase": lambda: f"知识点保持：{e['knowledge_point']}；页码保持：第 {e['page']} 页；不复用原题干" + ("；原文不充分可不出题" if e["allow_empty"] else ""),
        "goal.outline": lambda: "4–12 单元、每单元 3–6 要点、不编造日期/金额/页码/考纲" + (f"；期望覆盖：{g(OUTLINE_COVER[n])}" if n in OUTLINE_COVER else ""),
        "unit.lecture": lambda: "3–5 小节；讲到要点：" + "、".join(e["points"] or ["（无要点，按标题讲通用内容）"]) + "；不编造、不冒充原文、不出题",
        "dashboard.eval": lambda: f"期望 verdict：{e['verdict']}；理由要点：{'/'.join(DASH_REASON.get(n, []))}",
    }[cap]()
    return parts + (f"。易错点：{c['note']}" if c.get("note") else "")


def load():
    res = {}
    for p in RESULTS.glob("*.jsonl"):
        for l in p.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                res.setdefault((r["id"], r["model"]), []).append(r)
    return res


def dim_text(rows):
    out = []
    for r in sorted(rows, key=lambda x: x["run"]):
        head = f"第{r['run']}次 {r['status']}" if len(rows) > 1 else r["status"]
        ds = "；".join(f"{d['dim'].split('（')[0]}：{'是' if d['value'] is True else '否' if d['value'] is False else '待人工'}"
                      + (f"（{d['score']}分）" if d.get("score") else "") for d in r["dims"])
        out.append(f"{head}｜{ds}" + (f"｜未过：{r['why']}" if r.get("why") else ""))
    return "\n".join(out)


def overall(rows):
    if not rows:
        return "未跑"
    st = [r["status"] for r in rows]
    return "不通过" if "不通过" in st else "待人工" if "待人工" in st else "通过"


def rows():
    res = load()
    out = []
    for cap, cases in ALL.items():
        tier = TIER[cap]
        main, back = PAIR[tier]
        for c in cases:
            rec = {"编号": c["id"], "能力": [LABEL[cap]], "档位": ["快档+强档" if cap == "practice.check" else "快档" if tier == "fast" else "强档"],
                   "题型": [c["type"]], "打分维度": DIMS[cap], "输入（可直接复制）": json.dumps(c["input"], ensure_ascii=False)[:9000],
                   "验收要点": expect_text(c), "主模型": main, "备模型": back}
            for role, model in (("主", main), ("备", back)):
                rs = res.get((c["id"], model), [])
                if cap == "practice.check" and tier == "strong":
                    # 快档结果附在各维度里
                    pass
                rec[f"{role}模型判定"] = [overall(rs)]
                rec[f"{role}模型输出"] = (sorted(rs, key=lambda x: x["run"])[0]["output"][:9000] if rs else "")
                rec[f"{role}模型各维度"] = dim_text(rs) if rs else ""
            if cap == "practice.check":
                extra = [f"[快档 {m}] " + dim_text(res.get((c["id"], m), [])) for m in PAIR["fast"] if res.get((c["id"], m))]
                if extra:
                    rec["人工备注"] = "\n".join(extra)
            out.append(rec)
    return out


if __name__ == "__main__":
    json.dump(rows(), sys.stdout, ensure_ascii=False)
