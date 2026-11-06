"""把明确标为公开样例的已修复案例导出；缺回归说明时报告阻塞。"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def export_rows(rows):
    cases, blocked = [], []
    for row in rows:
        if row.status not in ("已修复", "已回归"):
            continue
        try:
            payload = json.loads(row.input_json)
            evaluation = payload["evaluation"]
            if payload.get("public_sample") is not True or not evaluation.get("checks"):
                raise ValueError("需要公开样例标记和 checks")
            # Regression must call the fixed prompt, not replay its expected answer.
            if not evaluation.get("prompt", {}).get("name") or not evaluation["prompt"].get("version"):
                raise ValueError("需要修复后的提示词名称和版本")
            cases.append({"id":"fixed-"+row.id, "capability":evaluation["capability"], "kind":"ai",
                          "prompt":evaluation["prompt"], "payload":evaluation["payload"], "checks":evaluation["checks"]})
        except (KeyError, TypeError, ValueError):
            blocked.append(row.id)
    return cases, blocked


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True, help="服务端运维身份明确指定要导出的用户")
    parser.add_argument("--output", type=Path, default=Path("evals/cases/fixed.json"))
    args=parser.parse_args()
    from sqlalchemy import select
    from app.data_access import user_scope
    from app.data_access.session import SessionLocal
    from app.study.common.db import ensure_schema
    from app.study.common.models import BadCase
    ensure_schema()
    with user_scope(args.user_id), SessionLocal() as session:
        cases, blocked=export_rows(session.scalars(select(BadCase).where(BadCase.user_id == args.user_id)).all())
    if blocked:
        print(json.dumps({"blocked_case_ids":blocked,"reason":"补充 public_sample 与 input_json.evaluation 后再导出；未覆盖全部已修复案例"}, ensure_ascii=False))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cases, ensure_ascii=False, indent=2))
    print(f"已导出 {len(cases)} 条公开回归用例")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
