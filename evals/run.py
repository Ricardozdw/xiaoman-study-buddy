"""统一评测：默认离线真实统计；显式 --mode live 才调用模型。

python evals/run.py --output data/evals/latest
python evals/run.py --mode live --model deepseek-flash --output data/evals/flash
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def field(value, path):
    for key in path.split("."):
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def grade(output, checks: dict) -> tuple[bool, list[str]]:
    errors = []
    for key, expected in checks.items():
        try:
            actual = field(output, key)
            if not json_equal(actual, expected):
                errors.append(f"{key}: expected {expected!r}, got {actual!r}")
        except (KeyError, IndexError, TypeError, ValueError):
            errors.append(f"{key}: missing")
    return not errors, errors


def json_equal(actual, expected):
    """JSON booleans are not numbers: Python's True == 1 is not a pass."""
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(json_equal(actual[key], expected[key]) for key in expected)
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(json_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def load_cases(directory: Path) -> list[dict]:
    cases = []
    capabilities = json.loads((ROOT / "evals/manifest.json").read_text())["required"]
    for path in sorted(directory.glob("*.json")):
        batch = json.loads(path.read_text())
        if not isinstance(batch, list):
            raise ValueError(f"{path.name} 必须是用例数组")
        for case in batch:
            if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"].strip():
                raise ValueError(f"{path.name} 的用例需要非空 id")
            if case.get("capability") not in capabilities:
                raise ValueError(f"{case['id']} 的能力不在评测清单中")
            if not isinstance(case.get("checks"), dict) or not case["checks"]:
                raise ValueError(f"{case.get('id')} 没有验收断言")
            if case.get("kind") not in ("dashboard", "ai"):
                raise ValueError("只接受 dashboard 或 ai 类型")
            if (case["kind"] == "dashboard") != (case["capability"] == "dashboard"):
                raise ValueError(f"{case['id']} 不能用看板离线用例代替其他能力")
            if not isinstance(case.get("payload"), dict):
                raise ValueError(f"{case['id']} 的 payload 必须是对象")
            if any(not key or any(not segment for segment in key.split(".")) for key in case["checks"]):
                raise ValueError(f"{case['id']} 的断言路径无效")
            if case["kind"] == "ai":
                prompt = case.get("prompt")
                if not isinstance(prompt, dict) or not all(isinstance(prompt.get(key), str) and prompt[key].strip() for key in ("name", "version")):
                    raise ValueError(f"{case['id']} 需要提示词名称和版本")
            cases.append(case)
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("用例 id 重复")
    return cases


def evaluate(cases: list[dict], *, mode: str, model: str | None) -> list[dict]:
    from app.study.dashboard.eval_adapter import run
    results = []
    for case in cases:
        started = time.perf_counter()
        item = {"id": case["id"], "capability": case["capability"], "kind": case["kind"],
                "state": "pending", "passed": False, "model": None, "tokens_in": None, "tokens_out": None}
        try:
            if case["kind"] == "dashboard":
                output = run(case["payload"])
            elif mode != "live":
                item["reason"] = "未运行真实模型"
                results.append(item)
                continue
            else:
                from app.gateway import core
                from app.prompts import load_prompt
                from app.tools.prompt_data import UNTRUSTED_DATA_RULE
                prompt = case["prompt"]
                system = load_prompt(prompt["name"], prompt["version"], untrusted_data_rule=UNTRUSTED_DATA_RULE)
                result = core.complete(system, json.dumps(case["payload"], ensure_ascii=False),
                                       tier="fast", task=prompt["name"], kind="json", temperature=0, max_tokens=2500, timeout=30)
                item["model"] = result.spec.model if result.spec else None
                item["tokens_in"] = sum(r.get("prompt_tokens") or 0 for r in result.attempts)
                item["tokens_out"] = sum(r.get("completion_tokens") or 0 for r in result.attempts)
                item["usage_reported"] = bool(result.attempts) and all(r.get("prompt_tokens") is not None and r.get("completion_tokens") is not None for r in result.attempts)
                if result.mode != "live" or not result.ok or item["model"] != model:
                    raise RuntimeError("未取得指定真实模型的输出，不能算通过")
                output = json.loads(result.content)
            item["state"] = "completed"
            item["passed"], item["errors"] = grade(output, case["checks"])
            # Never echo public fixture expected values into a candidate's output.
            item["output"] = output
            if not item["passed"]:
                from app.study.common.bad_cases import write_bad_case
                item["bad_case_id"] = write_bad_case(
                    user_id="evaluation", capability=case["capability"], input_payload=case["payload"],
                    actual_output=json.dumps(output, ensure_ascii=False), expected_output=json.dumps(case["checks"], ensure_ascii=False),
                    model=item["model"] or "deterministic", prompt_version=str(case.get("prompt", {})),
                    problem_type="评测失败", severity="高", source="evaluation")
        except Exception as exc:
            item.update(state="error", errors=[type(exc).__name__ + ": " + str(exc)[:200]])
        item["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        results.append(item)
    return results


def build_report(cases, results, mode, model, baseline=None):
    manifest = json.loads((ROOT / "evals/manifest.json").read_text())["required"]
    dataset = [{key: value for key, value in case.items() if key != "prompt"}
               for case in sorted(cases, key=lambda c: c["id"])]
    fingerprint = hashlib.sha256(json.dumps({"cases": dataset, "requirements": manifest}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    expected = {case["id"]: case for case in cases}
    actual = {result["id"]: result for result in results}
    data_errors = []
    if len(expected) != len(cases) or len(actual) != len(results) or expected.keys() != actual.keys():
        data_errors.append("用例与结果不一一对应，存在缺失、重复或额外结果")
    for case_id, result in actual.items():
        case = expected.get(case_id)
        if case and (result.get("capability") != case["capability"] or result.get("kind") != case["kind"]
                     or not isinstance(result.get("passed"), bool)):
            data_errors.append(f"{case_id} 的结果身份或通过标记无效")
    coverage = {}
    for capability, requirement in manifest.items():
        rows = [r for r in results if r["capability"] == capability]
        completed = [r for r in rows if r["state"] == "completed"]
        score = sum(r["passed"] is True for r in rows) / len(rows) if rows else 0
        coverage[capability] = {"cases": len(rows), "completed": len(completed), "score": score,
                                "ready": len(rows) >= requirement["minimum_cases"] and len(completed) == len(rows) and score >= requirement["pass_rate"]}
    regressions = []
    if baseline:
        if baseline["dataset_sha256"] != fingerprint or baseline["mode"] != mode:
            regressions.append("评测集或运行模式与基线不同，不能比较")
        else:
            previous = {r["id"]: r for r in baseline["results"]}
            regressions = [r["id"] for r in results if previous.get(r["id"], {}).get("passed") is True and r["passed"] is not True]
    fixed_failures = [case["id"] for case in cases if (case.get("regression") is True or case["id"].startswith("fixed-"))
                      and actual.get(case["id"], {}).get("passed") is not True]
    models_match = bool(model) and all(result.get("model") == model for result in results if result["kind"] == "ai")
    ran = [r for r in results if r["state"] != "pending"]
    return {"mode": mode, "model": model, "dataset_sha256": fingerprint,
            "prompts": {c["id"]: c["prompt"] for c in cases if c.get("prompt")}, "coverage": coverage,
            "regressions": regressions, "data_errors": data_errors, "fixed_case_failures": fixed_failures,
            "score": sum(r["passed"] is True for r in ran)/len(ran) if ran else 0,
            "release_ready": mode == "live" and models_match and all(c["ready"] for c in coverage.values()) and not (regressions or data_errors or fixed_failures),
            "results": results, "note": "离线分数仅验证规则与工程；真实模型质量、人工抽查、其他线和演示验收分别记录。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--model", choices=["deepseek-flash", "deepseek-v4-pro"])
    parser.add_argument("--cases", type=Path, default=ROOT / "evals/cases")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "data/evals/latest")
    parser.add_argument("--release-gate", action="store_true")
    args = parser.parse_args()
    if args.mode == "live" and (not args.model or not os.getenv("DEEPSEEK_API_KEY")):
        parser.error("真实模型评测需要 --model 和 DEEPSEEK_API_KEY；本命令不读取 .env")
    cases = load_cases(args.cases)
    if not cases:
        parser.error("评测集为空")
    # The process owns a temporary database, never the developer's study records.
    with tempfile.TemporaryDirectory(prefix="xiaoman-eval-") as data_dir:
        os.environ.update(DATA_DIR=data_dir, PYTHON_DOTENV_DISABLED="1", PROACTIVE_ENABLED="0")
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("SYSTEM_DATABASE_URL", None)
        if args.mode == "offline":
            for key in list(os.environ):
                if key.endswith("_API_KEY"):
                    os.environ.pop(key)
        elif args.model:
            os.environ["LLM_CONFIG_JSON"] = json.dumps({
                "models": {"evaluation-candidate": {"model":args.model, "base_url":"https://api.deepseek.com", "api_key_env":"DEEPSEEK_API_KEY", "params":{"thinking":{"type":"disabled"}}}},
                "tiers":{"fast":["evaluation-candidate"], "strong":["evaluation-candidate"]},
            })
            os.environ["LLM_FAST_CHAIN"] = os.environ["LLM_STRONG_CHAIN"] = "evaluation-candidate"
        results = evaluate(cases, mode=args.mode, model=args.model)
        baseline = json.loads(args.baseline.read_text()) if args.baseline else None
        report = build_report(cases, results, args.mode, args.model, baseline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    failures = [{"case": c, "result": r} for c, r in zip(cases, results) if r["state"] != "pending" and not r["passed"]]
    args.output.with_suffix(".bad-cases.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2))
    table = "".join(f"<tr><td>{html.escape(r['id'])}</td><td>{r['state']}</td><td>{'未运行' if r['state'] == 'pending' else '通过' if r['passed'] else '未通过'}</td></tr>" for r in results)
    args.output.with_suffix(".html").write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>小满评测报告</title><h1>小满评测报告</h1><p>' + html.escape(report["note"]) + '</p><table><tr><th>用例</th><th>状态</th><th>结果</th></tr>' + table + '</table><pre>' + html.escape(json.dumps(report["coverage"], ensure_ascii=False, indent=2)) + '</pre></html>')
    print(json.dumps({key: report[key] for key in ("score", "coverage", "regressions", "data_errors", "fixed_case_failures", "release_ready")}, ensure_ascii=False))
    return int(bool(failures or report["regressions"] or report["data_errors"] or report["fixed_case_failures"] or (args.release_gate and not report["release_ready"])))


if __name__ == "__main__":
    raise SystemExit(main())
