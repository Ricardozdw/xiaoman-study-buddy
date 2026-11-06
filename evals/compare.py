"""对同一评测集的两份真实模型报告比较；缺证据时不选主模型。"""
import argparse
import json
from pathlib import Path
import statistics


def metrics(report):
    rows = [r for r in report["results"] if r["kind"] == "ai"]
    prices = json.loads((Path(__file__).parents[1] / "app/study/dashboard/prices.json").read_text())
    price = prices["models"].get(report.get("model"))
    latencies = sorted(r["latency_ms"] for r in rows if "latency_ms" in r)
    complete = bool(rows) and all(r.get("state") == "completed" and r.get("model") == report.get("model") for r in rows)
    reported = complete and all(r.get("usage_reported") for r in rows)
    cost = sum((r["tokens_in"] * price["input_per_million"] + r["tokens_out"] * price["output_per_million"]) / 1_000_000 for r in rows) if price and reported else None
    return {"model":report.get("model"), "mode":report["mode"], "cases":len(rows),
            "accuracy":sum(r["passed"] for r in rows)/len(rows) if rows else None,
            "median_latency_ms":statistics.median(latencies) if latencies else None,
            "p95_latency_ms":latencies[min(len(latencies)-1, __import__("math").ceil(len(latencies)*.95)-1)] if latencies else None,
            "cost_estimate_cny":cost, "price":price,
            "qualified":report["mode"] == "live" and complete and report["release_ready"],
            "pricing_source":prices["source"], "pricing_basis":prices["basis"]}


def compare(first, second):
    if first["dataset_sha256"] != second["dataset_sha256"]:
        raise ValueError("两份报告必须使用相同评测集")
    if first.get("model") == second.get("model"):
        raise ValueError("需要两个不同模型的报告")
    rows = [metrics(first), metrics(second)]
    qualified = [r for r in rows if r["qualified"] and r["cost_estimate_cny"] is not None]
    qualified.sort(key=lambda r: (-r["accuracy"], r["cost_estimate_cny"], r["median_latency_ms"] or float("inf")))
    recommendation = f"建议 {qualified[0]['model']} 当主模型；先比较达标与准确率，再比较费用和延迟。" if qualified else "暂不确定主模型：还缺完整的真实模型评测或费用证据。"
    return {"models":rows, "recommendation":recommendation, "ready":bool(qualified)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/evals/comparison.json"))
    args=parser.parse_args()
    report=compare(json.loads(args.first.read_text()), json.loads(args.second.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(report["recommendation"])
    return int(not report["ready"])


if __name__ == "__main__":
    raise SystemExit(main())
