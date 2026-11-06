"""只读上线预检。返回非零即仍有待办，不创建部署。"""
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def check(evidence=None):
    items=[]
    def add(name, passed, detail):
        items.append({"check":name,"passed":bool(passed),"detail":detail})
    add("会话签名", len(os.getenv("AUTH_SECRET", "")) >= 32, "至少32字符，勿使用示例值")
    add("MVP范围", os.getenv("XIAOMAN_MVP") == "1", "XIAOMAN_MVP=1")
    add("关闭演示时钟", os.getenv("XIAOMAN_DEMO_CLOCK", "0").strip().lower() not in ("1", "true", "yes", "on"), "上线环境不能保留演示跳日")
    origins=os.getenv("CORS_ALLOW_ORIGINS", "")
    add("站点来源", bool(origins) and "*" not in origins and all(v.strip().startswith("https://") for v in origins.split(",")), "填写实际HTTPS站点来源")
    index = ROOT/"web/dist/index.html"
    add("前端产物", index.is_file() and "/study/assets/" in index.read_text(), "需要构建 /study/ 版本")
    try:
        registry=json.loads(os.getenv("LLM_CONFIG_JSON", "{}"))
        models=registry.get("models", {})
        chain=registry.get("tiers", {}).get("fast", [])
        if isinstance(chain, str):
            chain=[m.strip() for m in chain.split(",")]
        specs=[models[name] for name in chain]
        has_models=len({s["model"] for s in specs}) >= 2
        has_keys=True
        for spec in specs:
            names=spec.get("api_key_env", [])
            names=[names] if isinstance(names, str) else names
            has_keys=has_keys and any(os.getenv(name) for name in names)
        model_ready=has_models and has_keys
    except (ValueError, TypeError, KeyError):
        model_ready=False
    add("主备模型", model_ready, "FAST链须含两个不同且已配置凭据的模型")
    add("数据库", bool(os.getenv("DATABASE_URL") and os.getenv("SYSTEM_DATABASE_URL")), "分别使用非owner的app/system连接")
    required=("unit_tests", "golden_rules", "golden_hybrid", "harness", "web_tests", "web_build", "study_rls", "public_pdf", "demo_8_steps", "manual_model_review", "fixed_cases_exported", "budget_approved", "persistent_storage", "live_evaluation", "dependency_review", "container_smoke")
    evidence=evidence or {}
    for name in required:
        add(name, evidence.get(name) is True, "请填写有证据支持的验收结果")
    return {"ready":all(i["passed"] for i in items),"checks":items}


if __name__ == "__main__":
    evidence=json.loads(Path(sys.argv[1]).read_text()) if len(sys.argv)>1 else None
    report=check(evidence)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(int(not report["ready"]))
