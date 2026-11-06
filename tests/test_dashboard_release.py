from deploy.xiaoman.preflight import check
from deploy.xiaoman.study_schema import render
from deploy.xiaoman.preflight import valid_databases, valid_origins
import pytest


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


@pytest.mark.parametrize("value", ["https://","https://user:pass@example.test","https://example.test/path","https://example.test?token=secret","*","https://example.test:broken"])
def test_invalid_origins_do_not_pass_preflight(value):
    assert not valid_origins(value)


def test_database_roles_and_connection_types_are_checked():
    assert not valid_databases("sqlite:///db","sqlite:///db")
    assert not valid_databases("postgresql://postgres@db/study","postgresql://system@db/study")
    assert not valid_databases("postgresql://same@db/study","postgresql://same@db/study")
    assert valid_databases("postgresql+psycopg://app_login@db/study","postgresql+psycopg://system_login@db/study")


@pytest.mark.parametrize("config", ['null','[]','{"models":[],"tiers":null}','{"models":{},"tiers":{"fast":{}}}'])
def test_bad_model_configuration_is_a_failed_check_not_a_crash(monkeypatch,config):
    monkeypatch.setenv("LLM_CONFIG_JSON",config)
    assert not next(row["passed"] for row in check()["checks"] if row["check"]=="主备模型")
