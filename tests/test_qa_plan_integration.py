"""QA hands plan decisions to the formal plan service without inventing actions."""
import json

import pytest


def events(client, headers, text):
    response = client.post('/api/chat/stream', json={'message':text}, headers=headers)
    assert response.status_code == 200
    return [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith('data:') and '[DONE]' not in line]


def plan(client, headers):
    return client.get('/api/plan/today',headers=headers).json()['data']


@pytest.fixture
def plan_intent(monkeypatch):
    from app.study.qa import service
    monkeypatch.setattr(service,'classify',lambda *_:{'intent':'plan','mock':False})


def test_formal_card_confirm_undo_and_single_pending(client, auth, uid, plan_intent):
    headers = auth(uid)
    before = plan(client,headers)
    result = events(client,headers,'今天只有15分钟')
    handoff = next(e['data'] for e in result if e.get('type') == 'handoff')
    card = handoff['card']
    assert handoff['mock'] is True and handoff['label'] == '模拟'
    assert card['kind'] == 'adjust_intensity' and card['badge'] == '模拟'
    assert card['options'] == [{'id':'apply','label':'就这样'}]
    assert not any('effect' in option for option in card['options'])
    pending = plan(client,headers)
    assert pending['intensity'] == before['intensity']
    assert pending['tasks'] == before['tasks']
    second = events(client,headers,'今天想冲刺')
    repeated = next(e['data'] for e in second if e.get('type') == 'handoff')
    assert repeated['card']['id'] == card['id']
    assert repeated['reply'] == '先把这张卡定下来，再说别的'
    assert repeated['reply'] in ''.join(e.get('delta','') for e in second)
    intruder = client.post(f"/api/suggestions/{card['id']}/accept",json={'option':'apply'},headers=auth('qa-plan-intruder'))
    assert intruder.status_code == 404
    accepted = client.post(f"/api/suggestions/{card['id']}/accept",json={'option':'apply'},headers=headers)
    assert accepted.status_code == 200
    data = accepted.json()['data']
    assert data['status'] == 'executed' and data['plan']['intensity'] == 'light'
    assert len(data['plan']['tasks']) <= 3
    assert sum(t['minutes'] for t in data['plan']['tasks']) == 15
    undone = client.post(f"/api/actions/{card['id']}/undo",headers=headers).json()['data']
    assert undone['status'] == 'undone'
    assert undone['plan']['intensity'] == before['intensity']


@pytest.mark.parametrize('text,reply',[('今天有30分钟','已经是正常'),('调整安排但还不知道怎么调','可以说“今天只有 15 分钟”')])
def test_no_card_uses_formal_reply_without_handoff(client,auth,uid,plan_intent,text,reply):
    headers = auth(uid)
    before = plan(client,headers)
    result = events(client,headers,text)
    assert not any(e.get('type') == 'handoff' for e in result)
    assert reply in ''.join(e.get('delta','') for e in result)
    complete = next(e for e in result if e.get('type') == 'complete')
    assert complete['ok'] is True and complete['mock'] is True
    assert next(e for e in result if e.get('type') == 'meta')['mock'] is True
    assert '模拟' in ''.join(e.get('delta','') for e in result)
    after = plan(client,headers)
    assert after['intensity'] == before['intensity'] and after['card'] is None


def test_dismiss_native_card_keeps_plan(client,auth,uid,plan_intent):
    headers=auth(uid)
    before=plan(client,headers)
    result=events(client,headers,'今天只有15分钟')
    card=next(e['data']['card'] for e in result if e.get('type') == 'handoff')
    response=client.post(f"/api/suggestions/{card['id']}/dismiss",headers=headers)
    assert response.status_code == 200
    assert response.json()['data']['status'] == 'declined'
    after=plan(client,headers)
    assert after['intensity'] == before['intensity'] and after['card'] is None
