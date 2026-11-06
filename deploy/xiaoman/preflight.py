"""只读上线预检。返回非零即仍有待办，不创建部署。"""
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def valid_origins(raw):
    if not raw or "*" in raw:
        return False
    try:
        for item in raw.split(","):
            url = urlsplit(item.strip())
            if url.scheme != "https" or not url.hostname or url.path or url.query or url.fragment or url.username or url.password:
                return False
            _ = url.port
    except ValueError:
        return False
    return True


def valid_databases(app_url, system_url):
    try:
        urls = [urlsplit(value) for value in (app_url, system_url)]
        for url in urls:
            if (url.scheme not in ("postgres", "postgresql", "postgresql+psycopg") or not url.hostname
                    or not url.username or not url.path.strip("/") or url.fragment):
                return False
            if url.username.split(".")[0].lower() in ("postgres", "supabase_admin", "service_role"):
                return False
            _ = url.port
        return urls[0].username != urls[1].username
    except (TypeError, ValueError, AttributeError):
        return False


def check(evidence=None):
    items=[]
    def add(name, passed, detail):
        items.append({"check":name,"passed":bool(passed),"detail":detail})
    add("会话签名", len(os.getenv("AUTH_SECRET", "").strip()) >= 32, "至少32字符，勿使用示例值")
    add("MVP范围", os.getenv("XIAOMAN_MVP") == "1", "XIAOMAN_MVP=1")
    add("关闭演示时钟", os.getenv("XIAOMAN_DEMO_CLOCK", "0").strip().lower() not in ("1", "true", "yes", "on"), "上线环境不能保留演示跳日")
    origins=os.getenv("CORS_ALLOW_ORIGINS", "")
    add("站点来源", valid_origins(origins), "填写实际HTTPS来源，包含主机且不带路径、账号或查询参数")
    index = ROOT/"web/dist/index.html"
    add("前端产物", index.is_file() and "/study/assets/" in index.read_text(), "需要构建 /study/ 版本")
    try:
        registry=json.loads(os.getenv("LLM_CONFIG_JSON", "{}"))
        if not isinstance(registry, dict):
            raise ValueError("模型配置必须是对象")
        models=registry.get("models", {})
        model_ready=True
        for tier in ("fast", "strong"):
            chain=registry.get("tiers", {}).get(tier, [])
            if isinstance(chain, str):
                chain=[model.strip() for model in chain.split(",")]
            if not isinstance(chain, list):
                raise ValueError("模型链必须是列表")
            specs=[models[name] for name in chain]
            has_models=len({spec["model"] for spec in specs if isinstance(spec["model"], str) and spec["model"].strip()}) >= 2
            has_keys=True
            for spec in specs:
                names=spec.get("api_key_env", [])
                names=[names] if isinstance(names, str) else names
                has_keys=has_keys and any(os.getenv(name, "").strip() for name in names)
            model_ready=model_ready and has_models and has_keys
    except (ValueError, TypeError, KeyError, AttributeError):
        model_ready=False
    add("主备模型", model_ready, "FAST和STRONG链都须含两个不同且已配置凭据的模型")
    add("数据库", valid_databases(os.getenv("DATABASE_URL", ""), os.getenv("SYSTEM_DATABASE_URL", "")), "分别使用不同的PostgreSQL app/system登录角色；实际权限仍需RLS验收")
    required=("unit_tests", "golden_rules", "golden_hybrid", "harness", "web_tests", "web_build", "study_rls", "public_pdf", "demo_8_steps", "manual_model_review", "fixed_cases_exported", "budget_approved", "persistent_storage", "live_evaluation", "dependency_review", "container_smoke")
    evidence=evidence if isinstance(evidence, dict) else {}
    for name in required:
        add(name, evidence.get(name) is True, "请填写有证据支持的验收结果")
    return {"ready":all(i["passed"] for i in items),"checks":items}


if __name__ == "__main__":
    evidence=json.loads(Path(sys.argv[1]).read_text()) if len(sys.argv)>1 else None
    report=check(evidence)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(int(not report["ready"]))
