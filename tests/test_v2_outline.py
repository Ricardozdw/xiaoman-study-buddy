"""T03：能力、分阶段边界、草稿到撤销、跨用户隔离及事务回滚。"""
import importlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.data_access.session import SessionLocal
from app.study.common.models import Attempt, Chapter, Goal, MaterialPage, PlanTask, Question, StudyFile
from app.study.v2 import outline, service
from tests.conftest import RawTestClient


@pytest.fixture
def api(monkeypatch):
    import app.study.router as routes
    monkeypatch.setenv("XIAOMAN_V2", "1")
    importlib.reload(routes)
    app = FastAPI()
    app.include_router(routes.router)
    with RawTestClient(app) as client:
        yield client
    monkeypatch.delenv("XIAOMAN_V2", raising=False)
    importlib.reload(routes)


@pytest.fixture
def owner(auth):
    uid = "outline-" + uuid4().hex
    return uid, auth(uid)


def body(**changes):
    return {"goal_type": "exam", "title": "考 PMP", "deadline": None, "daily_minutes": 30,
            "progress": "还没开始", "materials": "none", **changes}


def draft(api, owner):
    response = api.post("/api/v2/outline/draft", headers=owner[1], json=body())
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.parametrize("count,sizes", [(1,[1]),(4,[4]),(5,[3,2]),(6,[3,3]),(7,[4,3]),(9,[3,3,3]),(10,[4,3,3]),(20,[4,4,4,4,4])])
def test_balanced_stage_boundaries(count, sizes):
    stages = outline.split_stages(count)
    assert [len(stage["unit_nos"]) for stage in stages] == sizes
    assert [n for stage in stages for n in stage["unit_nos"]] == list(range(1, count+1))
    assert all(stage["started_at"] == "" for stage in stages)
    stages[0]["unit_nos"].clear()
    assert outline.split_stages(count)[0]["unit_nos"]  # 每次调用互不影响。


@pytest.mark.parametrize("count", [0,21,True,1.5])
def test_stage_count_rejects_invalid_values(count):
    with pytest.raises(ValueError):
        outline.split_stages(count)


CASES = json.loads(
    (Path(__file__).parents[1] / "app/study/v2/evals/goal_outline.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CASES, ids=lambda case:case["title"])
def test_offline_evaluation(case, owner, monkeypatch):
    monkeypatch.setattr(outline, "has_llm", lambda **_:False)
    units, mocked = outline.generate_outline(owner[0], {**case, "today":"2026-11-07"})
    assert mocked and 4 <= len(units) <= 12
    assert len({unit["title"] for unit in units}) == len(units)
    assert all(3 <= len(unit["points"]) <= 6 for unit in units)
    assert not outline.UNVERIFIED.search(json.dumps(units,ensure_ascii=False))


def test_mock_size_depends_on_budget():
    small = outline.mock_units({**body(deadline="2026-11-08",daily_minutes=15),"today":"2026-11-07"})
    large = outline.mock_units({**body(deadline="2027-02-07",daily_minutes=50),"today":"2026-11-07"})
    assert len(small) == 4 and len(large) == 12


def test_draft_patch_accept_and_undo(api, owner):
    uid, headers = owner
    before = api.get("/api/plan/today",headers=headers).json()["data"]
    data = draft(api, owner)
    assert data["status"] == "draft" and data["label"] == "模拟" and data["mock"]
    assert api.get("/api/plan/today",headers=headers).json()["data"]["needs_setup"]
    edited = [{"title":unit["title"],"points":unit["points"]} for unit in data["units"]]
    edited[0]["title"] = "用户改过的准备单元"
    patched = api.patch(f'/api/v2/outline/{data["id"]}',headers=headers,json={"units":edited})
    assert patched.status_code == 200
    assert patched.json()["data"]["units"][0]["title"] == edited[0]["title"]
    path = f'/api/v2/outline/{data["id"]}'
    result = api.post(path+"/accept",headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["outline"]["stages"][0]["started_at"]
    today = api.get("/api/plan/today",headers=headers).json()
    assert today["mock"] is False and today["data"]["needs_setup"] is False
    assert today["data"]["tasks"][0]["title"].startswith("学第 1 讲")
    assert len(today["data"]["tasks"]) <= 3
    lecture_data = api.get("/api/qa/lectures", headers=headers).json()["data"]
    assert lecture_data["current_lecture_id"] == "lec-1"
    lectures = lecture_data["items"]
    assert {item["id"] for item in lectures} == {f'lec-{i}' for i in range(1,len(edited)+1)}
    assert all(item["title"] == service.FILENAME for item in lectures)
    with SessionLocal() as session:
        assert session.scalar(select(Chapter).where(Chapter.user_id==uid,Chapter.sort_order==1)).title == edited[0]["title"]
        assert session.scalar(select(MaterialPage).where(MaterialPage.user_id==uid,MaterialPage.lecture_id=="lec-1")).text.startswith(edited[0]["title"])
    assert api.post(path+"/accept",headers=headers).status_code == 200  # 重复提交幂等。
    assert api.patch(path,headers=headers,json={"units":edited}).status_code == 409
    undone = api.post(path+"/undo",headers=headers)
    assert undone.status_code == 200 and undone.json()["data"]["plan_today"]["needs_setup"] == before["needs_setup"]
    with SessionLocal() as session:
        for model in (StudyFile, MaterialPage, Chapter):
            assert not list(session.scalars(select(model).where(model.user_id==uid,model.id.startswith('v2-outline-'))))
    assert api.post(path+"/undo",headers=headers).status_code == 409


@pytest.mark.parametrize("count", [1,4,5,6,7,9,10,20])
def test_patch_recalculates_stages(api, owner, count):
    data = draft(api, owner)
    units = [{"title":f"单元{i}","points":["用户要点"]} for i in range(count)]
    result = api.patch(f'/api/v2/outline/{data["id"]}',headers=owner[1],json={"units":units})
    assert result.status_code == 200
    assert result.json()["data"]["stages"] == outline.split_stages(count)


def test_isolation_and_invalid_inputs(api, owner, auth):
    data = draft(api, owner)
    stranger = auth("stranger-"+uuid4().hex)
    path = f'/api/v2/outline/{data["id"]}'
    assert api.patch(path,headers=stranger,json={"units":[{"title":"一","points":["要点"]}]}).status_code == 404
    for operation in ("accept","undo"):
        assert api.post(path+"/"+operation,headers=stranger).status_code == 404
    for units in ([],[{"title":" ","points":["要点"]}],[{"title":"重复","points":["要点"]}]*2,[{"title":"一","points":[""]}]):
        assert api.patch(path,headers=owner[1],json={"units":units}).status_code == 422
    assert api.post("/api/v2/outline/draft",json=body()).status_code == 401
    assert api.post("/api/v2/outline/draft",headers=owner[1],json=body(title="  ")).status_code == 422


def test_undo_only_same_day(api,owner,monkeypatch):
    from datetime import timedelta
    data=draft(api,owner);path=f'/api/v2/outline/{data["id"]}'
    assert api.post(path+"/accept",headers=owner[1]).status_code==200
    today=service.plan_service.today_for(owner[0])
    monkeypatch.setattr(service.plan_service,"today_for",lambda _:today+timedelta(days=1))
    assert api.post(path+"/undo",headers=owner[1]).status_code==409


def test_accept_preserves_attempted_sample_question_and_real_rows(api,owner):
    uid,headers=owner
    api.get('/api/plan/today',headers=headers)
    with SessionLocal() as session:
        session.add(Attempt(id=uuid4().hex,user_id=uid,question_id=uid+':q1',answer='B',correct=1))
        session.add(StudyFile(id='real-'+uuid4().hex,user_id=uid,filename='real.pdf',lecture_id='real-lecture',parse_status='parsed'))
        session.commit()
    data=draft(api,owner);path=f'/api/v2/outline/{data["id"]}'
    assert api.post(path+'/accept',headers=headers).status_code==200
    with SessionLocal() as session:
        assert session.get(Question,uid+':q1') is not None
        assert session.get(Question,uid+':q2') is None
        assert list(session.scalars(select(Attempt).where(Attempt.user_id==uid)))
        assert session.scalar(select(StudyFile).where(StudyFile.user_id==uid,StudyFile.lecture_id=='real-lecture'))
    assert api.post(path+'/undo',headers=headers).status_code==200
    with SessionLocal() as session:
        assert session.get(Question,uid+':q2') is not None


def test_accept_rolls_back_all_changes_on_failure(api,owner,monkeypatch):
    data=draft(api,owner)
    api.get('/api/plan/today',headers=owner[1])
    with SessionLocal() as session:
        before=session.scalar(select(Goal).where(Goal.user_id==owner[0])).summary_json
    def fail(*_):raise RuntimeError('synthetic failure')
    monkeypatch.setattr(service,'_write_materials',fail)
    with pytest.raises(RuntimeError,match='synthetic failure'):
        api.post(f'/api/v2/outline/{data["id"]}/accept',headers=owner[1])
    with SessionLocal() as session:
        assert session.scalar(select(Goal).where(Goal.user_id==owner[0])).summary_json==before
        assert session.get(StudyFile,owner[0]+':file') is not None


def test_retry_records_calls_and_bad_case_after_two_invalid_outputs(owner,monkeypatch):
    from app.study.common.models import BadCase,LlmCall
    monkeypatch.setattr(outline,'has_llm',lambda **_:True)
    calls=[]
    def bad(*args,**kwargs):calls.append(args);return {"units":[]}
    monkeypatch.setattr(outline,'chat_json',bad)
    units,mocked=outline.generate_outline(owner[0],{**body(),"today":"2026-11-07"})
    assert mocked and len(calls)==2 and 4<=len(units)<=12
    assert '<source>' in calls[0][1] and outline.UNTRUSTED_DATA_RULE in calls[0][0]
    with SessionLocal() as session:
        assert len(list(session.scalars(select(LlmCall).where(LlmCall.user_id==owner[0]))))==2
        assert session.scalar(select(BadCase).where(BadCase.user_id==owner[0]))


def test_retries_once_then_accepts_valid_live_output(owner,monkeypatch):
    monkeypatch.setattr(outline,'has_llm',lambda **_:True)
    good=outline.mock_units({**body(),"today":"2026-11-07"})
    replies=iter([{"units":[]},{"units":good,"_mode":"live"}])
    monkeypatch.setattr(outline,'chat_json',lambda *a,**k:next(replies))
    units,mocked=outline.generate_outline(owner[0],{**body(),"today":"2026-11-07"})
    assert not mocked and len(units)==len(good)


@pytest.mark.parametrize("forbidden", ["2026年12月20日考试", "报名费 500 元", "满分 100 分", "教材第 3 页", "官方考纲第 1 章"])
def test_generated_outline_rejects_unverified_fact_forms(forbidden):
    units=outline.mock_units({**body(),"today":"2026-11-07"})
    units[0]["points"][0]=forbidden
    with pytest.raises(ValueError):outline.validate_units(units,generated=True)


def test_undo_keeps_completed_task_and_attempt_records(api,owner):
    uid,headers=owner
    data=draft(api,owner);path=f'/api/v2/outline/{data["id"]}'
    response=api.post(path+'/accept',headers=headers).json()["data"]
    task_id=response["plan_today"]["tasks"][0]["id"]
    assert api.patch('/api/tasks/'+task_id,headers=headers,json={"status":"done"}).status_code==200
    assert api.post(path+'/undo',headers=headers).status_code==200
    with SessionLocal() as session:
        assert session.get(PlanTask,task_id).status=='done'


def test_switch_off_keeps_outline_routes_absent(monkeypatch):
    import app.study.router as routes
    monkeypatch.delenv('XIAOMAN_V2',raising=False)
    importlib.reload(routes)
    app=FastAPI();app.include_router(routes.router)
    with RawTestClient(app) as client:
        assert client.post('/api/v2/outline/draft',json=body()).status_code==404
        assert not any(path.startswith('/api/v2/') for path in client.get('/openapi.json').json()['paths'])


def test_real_application_session_middleware_can_bind_request_identity(owner,monkeypatch):
    from app.session_identity import SessionIdentityMiddleware
    from app.study.v2.routes import router
    app=FastAPI();app.include_router(router)
    app.add_middleware(SessionIdentityMiddleware,router=app.router)
    with RawTestClient(app) as client:
        assert client.post('/api/v2/outline/draft',headers=owner[1],json=body(user_id='untrusted-user')).status_code==404
        response=client.post('/api/v2/outline/draft',headers=owner[1],json=body())
        assert response.status_code==200,response.text
        data=response.json()['data']
        assert client.patch('/api/v2/outline/'+data['id'],headers=owner[1],json={'units':[{'title':'用户修改','points':['要点']}]}).status_code==200
    from app.study.v2.models import GoalOutline
    with SessionLocal() as session:
        assert session.get(GoalOutline,data['id']).user_id==owner[0]


def test_current_outline_follows_accept_undo_and_owner(api, owner, auth):
    """块4：确认后能读回当前大纲；撤销后为空；别人读不到。"""
    _, headers = owner
    assert api.get("/api/v2/outline/current", headers=headers).json()["data"]["outline"] is None
    data = draft(api, owner)
    assert api.get("/api/v2/outline/current", headers=headers).json()["data"]["outline"] is None  # 草稿不算
    path = f'/api/v2/outline/{data["id"]}'
    assert api.post(path + "/accept", headers=headers).status_code == 200
    got = api.get("/api/v2/outline/current", headers=headers).json()["data"]["outline"]
    assert got["id"] == data["id"] and got["status"] == "accepted" and got["units"] == data["units"]
    other = auth("outline-other-" + uuid4().hex)
    assert api.get("/api/v2/outline/current", headers=other).json()["data"]["outline"] is None
    assert api.post(path + "/undo", headers=headers).status_code == 200
    assert api.get("/api/v2/outline/current", headers=headers).json()["data"]["outline"] is None
