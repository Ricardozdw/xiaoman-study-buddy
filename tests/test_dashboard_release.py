from deploy.xiaoman.preflight import check
from deploy.xiaoman.study_schema import render


def test_preflight_cannot_succeed_with_missing_evidence(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "x" * 64)
    monkeypatch.setenv("XIAOMAN_MVP", "1")
    monkeypatch.setenv("LLM_CONFIG_JSON", "invalid")
    report=check({"unit_tests": True})
    assert not report["ready"]
    assert not next(r["passed"] for r in report["checks"] if r["check"] == "主备模型")
    assert not next(r["passed"] for r in report["checks"] if r["check"] == "live_evaluation")


def test_schema_uses_current_models_and_scoped_policies():
    sql=render()
    assert "CREATE TABLE IF NOT EXISTS bad_cases" in sql
    assert "CREATE TABLE IF NOT EXISTS llm_calls" in sql
    assert "auth.uid()" not in sql
    assert "WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), ''))" in sql
    assert sql.count("ENABLE ROW LEVEL SECURITY") == sql.count("CREATE TABLE IF NOT EXISTS")
    assert sql.count("FORCE ROW LEVEL SECURITY") == sql.count("CREATE TABLE IF NOT EXISTS")
