"""小满模型评测 · 完整版运行器（11 项能力 × 30 条，qa.intent 另加 10 条 goal）。

用法（在仓库根目录、用仓库 .venv）：
    .venv/bin/python -m evals.run_full --model deepseek-chat        # 跑这个模型对应档位的全部能力
    .venv/bin/python -m evals.run_full --model kimi-k3 --cap unit.lecture
    .venv/bin/python -m evals.run_full --summary                    # 汇总已有结果

- 系统提示词：直接加载产品 app/prompts/<能力>/v1.md（与线上一致）；输入按产品格式包成 <source>JSON</source>。
- 只做关键项的确定性判分（JSON、条数、逐字出处、编造、标签/答案）；1–5 质量分留给人工抽评，不用机器冒充。
- 结果逐条写入 evals/results/<模型>.jsonl，可断点续跑；密钥从仓库 .env 读取，不打印、不写入结果。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evals.cases_a import GENERATE, INTENT, OPENING, QA, SUMMARY  # noqa: E402
from evals.cases_b import CHECK, DASHBOARD, LECTURE, OUTLINE, REPHRASE  # noqa: E402

ALL = {c: v for c, v in [("qa.intent", INTENT), ("plan.opening", OPENING), ("qa.answer", QA), ("materials.summary", SUMMARY),
                          ("practice.generate", GENERATE), ("practice.check", CHECK), ("practice.rephrase", REPHRASE),
                          ("goal.outline", OUTLINE), ("dashboard.eval", DASHBOARD), ("unit.lecture", LECTURE)]}
TIER = json.loads((ROOT / "deploy/xiaoman/models.example.json").read_text())["tasks"]
MODELS = {
    "deepseek-chat": {"base": "https://api.deepseek.com/v1", "key": "DEEPSEEK_API_KEY", "tier": "fast", "temperature": 0.0, "gap": 0},
    "qwen-plus": {"base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "key": "DASHSCOPE_API_KEY", "tier": "fast", "temperature": 0.0, "gap": 0},
    "deepseek-reasoner": {"base": "https://api.deepseek.com/v1", "key": "DEEPSEEK_API_KEY", "tier": "strong", "temperature": 0.0, "gap": 0},
    "kimi-k3": {"base": "https://api.moonshot.cn/v1", "key": "KIMI_API_KEY", "tier": "strong", "temperature": 1.0, "gap": 21},  # RPM=3
}
MAX_TOKENS = {"qa.intent": 200, "plan.opening": 300, "qa.answer": 1500, "materials.summary": 4000, "practice.generate": 4000,
              "practice.check": 400, "practice.rephrase": 1500, "goal.outline": 2500, "dashboard.eval": 600, "unit.lecture": 4000}
RESULTS = ROOT / "evals/results"
LEAK = re.compile(r"你是学习搭子|你是小满|untrusted|系统提示词是|sk-[A-Za-z0-9]{6,}")
UNVERIFIED = re.compile(r"\d{4}[-年/]\d{1,2}|\d{1,2}月\d{1,2}[日号]|\d+(?:\.\d+)?\s*(?:元|美元|人民币|分值|分(?!钟))|[¥￥$]\s*\d|第\s*[\d一二三四五六七八九十]+\s*页|官方考纲第")


def env():
    out = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def system_for(cap):
    from app.prompts import load_prompt
    from app.tools.prompt_data import UNTRUSTED_DATA_RULE
    if cap == "materials.summary":
        from app.study.materials.summary import _system_prompt
        return _system_prompt()
    if "{{untrusted_data_rule}}" in (ROOT / "app/prompts" / cap / "v1.md").read_text():
        return load_prompt(cap, "v1", untrusted_data_rule=UNTRUSTED_DATA_RULE)
    return load_prompt(cap, "v1")


def call(model, system, user, max_tokens, keys):
    m = MODELS[model]
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": m["temperature"], "max_tokens": max_tokens}
    req = urllib.request.Request(m["base"] + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + keys[m["key"]]})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read())
    except Exception as exc:  # 网络、限流、超时都记为失败，不重试成功也不挑结果
        return {"error": f"{type(exc).__name__}: {str(exc)[:160]}", "latency": round(time.time() - start, 1)}
    usage = data.get("usage") or {}
    return {"content": data["choices"][0]["message"].get("content") or "", "latency": round(time.time() - start, 1),
            "tokens": usage.get("total_tokens", 0)}


def parse_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def compact(s):
    return re.sub(r"\s+", "", str(s or ""))


def quote_ok(pages, page, quote):
    text = {p["page"]: compact(p["text"]) for p in pages}.get(page)
    return bool(quote) and text is not None and compact(quote) in text


from evals.scoring import judge  # noqa: E402

CASES = {c["id"]: c for cs in ALL.values() for c in cs}
EXTRA = {"fast": {"practice.check"}}  # 产品里 practice.check 实际走快档，两档都评
RUNS = {"kimi-k3": 3}  # 温度固定为 1，每条跑 3 次；其余温度 0 跑 1 次


def prepare(c):
    """按产品格式组装输入；学习笔记带上原句片段编号表。"""
    user = "<source>\n" + json.dumps(c["input"], ensure_ascii=False) + "\n</source>"
    if c["cap"] == "materials.summary":
        from app.study.materials.summary import build_evidence
        from app.tools.prompt_data import data_block
        catalogue, evidence = build_evidence(c["input"]["pages"])
        c = {**c, "evidence": evidence}
        user = data_block("source", json.dumps({"title": c["input"]["title"], "pages": catalogue}, ensure_ascii=False))
    return c, user


def run(model, caps, only_run=0, pace=0):
    keys = env()
    tier = MODELS[model]["tier"]
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / (f"{model}.r{only_run}.jsonl" if only_run else f"{model}.jsonl")
    done = set()
    if path.exists():
        done = {json.loads(l).get("key") or json.loads(l)["id"] + "@1" for l in path.read_text().splitlines() if l.strip()}
    for cap, cases in ALL.items():
        if (caps and cap not in caps) or (TIER.get(cap) != tier and cap not in EXTRA.get(tier, set())):
            continue
        system = system_for(cap)
        for c in cases:
            for run_no in ([only_run] if only_run else range(1, RUNS.get(model, 1) + 1)):
                key = f"{c['id']}@{run_no}"
                if key in done:
                    continue
                cc, user = prepare(c)
                retried, raw = False, ""
                for attempt in range(2):
                    for _ in range(6):  # 限流（429）是评测侧的问题，等一会儿重试，不记为模型失败
                        r = call(model, system, user, MAX_TOKENS[cap], keys)
                        if "429" not in r.get("error", ""):
                            break
                        time.sleep(65)
                    if pace:  # 多进程并行时，每个进程每 pace 秒最多一次调用，合计不超限流
                        time.sleep(max(0, pace - r.get("latency", 0)))
                    elif MODELS[model]["gap"]:
                        time.sleep(MODELS[model]["gap"])
                    if "error" in r:
                        break
                    raw = r["content"]
                    if cap != "qa.answer" and parse_json(raw) is None and attempt == 0:
                        retried = True
                        continue  # 格式错误允许重试 1 次
                    break
                row = {"key": key, "id": c["id"], "run": run_no, "cap": cap, "type": c["type"], "model": model, "retried": retried,
                       "latency": r.get("latency", 0), "tokens": r.get("tokens", 0), "error": r.get("error", ""), "output": raw[:8000]}
                row.update(score_row(row))
                with path.open("a") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"{key} {model} {row['status']} {row['why']}", flush=True)


def score_row(row):
    c = CASES[row["id"]]
    if row.get("error"):
        dims = [{"dim": "调用", "kind": "是/否", "value": False, "detail": "调用失败：" + row["error"]}]
        return {"dims": dims, "status": "不通过", "why": dims[0]["detail"]}
    c, _ = prepare(c)
    parsed = None if row["cap"] == "qa.answer" else parse_json(row["output"])
    dims, status = judge(row["cap"], parsed, row["output"], c, {"latency": row["latency"], "retried": row["retried"]})
    why = "；".join(f"{d['dim']}：{d['detail']}" for d in dims if d["value"] is False)[:300]
    return {"dims": dims, "status": status, "why": why}


def rescore():
    """不重新调模型，按最新判分规则重判已保存的输出。旧格式结果自动补上 key/run。"""
    for p in RESULTS.glob("*.jsonl"):
        rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        out = []
        for r in rows:
            r.setdefault("run", 1)
            r["key"] = f"{r['id']}@{r['run']}"
            r.setdefault("error", r["detail"][5:] if str(r.get("detail", "")).startswith("调用失败：") else "")
            for k in ("passed", "detail"):
                r.pop(k, None)
            r.update(score_row(r))
            out.append(r)
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
        print(p.name, len(out))


def summary():
    """按能力 × 模型汇总：单次结论分布 + 每个维度的通过/不过/待人工。"""
    rows = []
    for p in RESULTS.glob("*.jsonl"):
        rows += [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    out = {}
    for r in rows:
        t = out.setdefault(r["cap"], {}).setdefault(r["model"], {"runs": 0, "通过": 0, "不通过": 0, "待人工": 0, "lat": [], "tokens": 0,
                                                                  "dims": {}, "failures": []})
        t["runs"] += 1; t[r["status"]] += 1; t["lat"].append(r["latency"]); t["tokens"] += r["tokens"]
        for d in r["dims"]:
            st = t["dims"].setdefault(d["dim"], {"是": 0, "否": 0, "待人工": 0})
            st["是" if d["value"] is True else "否" if d["value"] is False else "待人工"] += 1
        if r["status"] == "不通过":
            t["failures"].append(f"{r['key']}：{r['why']}")
    for ms in out.values():
        for t in ms.values():
            lat = sorted(t.pop("lat"))
            t["latency_avg"] = round(sum(lat) / len(lat), 1) if lat else 0
            t["latency_p95"] = lat[int(len(lat) * .95) - 1] if lat else 0
    (RESULTS / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    for cap, ms in out.items():
        print(cap, {m: f"通过{v['通过']}/不过{v['不通过']}/待人工{v['待人工']} 共{v['runs']} 均{v['latency_avg']}s" for m, v in ms.items()})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=list(MODELS))
    ap.add_argument("--cap", action="append")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--rescore", action="store_true")
    ap.add_argument("--run", type=int, default=0)
    ap.add_argument("--pace", type=float, default=0)
    a = ap.parse_args()
    if a.rescore:
        rescore()
    elif a.summary:
        summary()
    else:
        run(a.model, a.cap or [], a.run, a.pace)
