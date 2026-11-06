"""T02：开关、鉴权、共享表登记和学习表的显式 owner 查询约定。"""
import importlib
import json
import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from tests.conftest import RawTestClient


@pytest.fixture
def v2_client(monkeypatch):
    from app.study import router as routes

    def build(value):
        if value is None:
            monkeypatch.delenv("XIAOMAN_V2", raising=False)
        else:
            monkeypatch.setenv("XIAOMAN_V2", value)
        # 与应用启动时一样，先确定开关，再注册路由。
        importlib.reload(routes)
        app = FastAPI()
        app.include_router(routes.router)
        return RawTestClient(app)

    yield build
    monkeypatch.delenv("XIAOMAN_V2", raising=False)
    importlib.reload(routes)


@pytest.mark.parametrize("value", [None, "0", "false", "yes", ""])
def test_disabled_status_is_not_registered(v2_client, value):
    with v2_client(value) as client:
        assert client.get("/api/v2/status").status_code == 404
        assert "/api/v2/status" not in client.get("/openapi.json").json()["paths"]


@pytest.mark.parametrize("value", ["1", "true", " TRUE "])
def test_enabled_status_requires_auth_and_uses_real_envelope(v2_client, auth, value):
    with v2_client(value) as client:
        assert client.get("/api/v2/status").status_code == 401
        result = client.get("/api/v2/status", headers=auth("v2-status"))
        assert result.status_code == 200
        assert result.json() == {"ok": True, "status": "ok", "mock": False,
                                 "data": {"enabled": True, "version": "2.0-min"}}


def test_switch_is_read_each_time_but_routes_are_fixed_at_startup(v2_client, monkeypatch, auth):
    from app.study.v2 import enabled
    with v2_client("1") as client:
        monkeypatch.setenv("XIAOMAN_V2", "0")
        assert enabled() is False
        assert client.get("/api/v2/status", headers=auth("v2-status")).status_code == 200
        monkeypatch.setenv("XIAOMAN_V2", "true")
        assert enabled() is True


def test_schema_registers_tables_and_owner_scoped_reads_are_isolated():
    from app import db
    from app.data_access.session import SessionLocal
    from app.study.common.db import ensure_schema
    from app.study.v2.models import Assessment, GoalOutline

    ensure_schema()
    owner_a, owner_b = "v2-a-" + uuid.uuid4().hex, "v2-b-" + uuid.uuid4().hex
    ids = {owner: uuid.uuid4().hex for owner in (owner_a, owner_b)}
    with SessionLocal() as session:
        for owner, outline_id in ids.items():
            session.add(GoalOutline(id=outline_id, user_id=owner, title=owner,
                                    units_json=json.dumps([{"no": 1, "title": "单元", "points": ["要点"]}]),
                                    stages_json=json.dumps([{"no": 1, "title": "基础", "unit_nos": [1], "started_at": ""}])))
            session.add(Assessment(id="assessment-" + outline_id, user_id=owner,
                                   outline_id=outline_id, stage_no=1))
        session.commit()
    # 学习表与现有各线一样，由查询显式使用经过鉴权的 user_id。
    for owner, other in ((owner_a, owner_b), (owner_b, owner_a)):
        with SessionLocal() as session:
            outline = session.scalar(select(GoalOutline).where(GoalOutline.user_id == owner))
            assert outline.id == ids[owner] and outline.status == "draft"
            assert outline.label == "AI 整理，可以改" and outline.created_at and outline.updated_at
            assert json.loads(outline.units_json)[0]["points"] == ["要点"]
            assessment = session.scalar(select(Assessment).where(Assessment.user_id == owner))
            assert assessment.outline_id == outline.id and assessment.status == "open"
            assert assessment.score is None and assessment.submitted_at is None
            for model, row_id in ((GoalOutline, ids[other]), (Assessment, "assessment-" + ids[other])):
                assert session.scalar(select(model).where(model.id == row_id, model.user_id == owner)) is None
    assert {"goal_outlines", "assessments"} <= db.Base.metadata.tables.keys()
    for model in (GoalOutline, Assessment):
        assert any([column.name for column in index.columns] == ["user_id"] for index in model.__table__.indexes)


def test_postgres_schema_includes_v2_tables_with_forced_owner_policies():
    from deploy.xiaoman.study_schema import render
    sql = render()
    for name in ("goal_outlines", "assessments"):
        table = f'"public"."{name}"'
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" in sql
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;" in sql
        assert f"CREATE POLICY xiaoman_owner ON {table} TO personal_agent_app" in sql
        assert f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO personal_agent_app;" in sql
    assert "WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), ''))" in sql
