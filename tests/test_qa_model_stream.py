"""Streaming wire tests; all HTTP is local MockTransport."""
import json

import httpx
import pytest
from sqlalchemy import select

from app.gateway import limiter, providers, usage
from app.gateway.config import GatewayConfig, ModelSpec
from app.study.qa import model_stream as stream
from app.data_access import user_scope
from app.data_access.session import SessionLocal
from app.study.common.models import LlmCall


class Bytes(httpx.SyncByteStream):
    def __init__(self, wire, fail=False):
        self.wire, self.fail, self.closed = wire, fail, False

    def __iter__(self):
        for offset in range(0, len(self.wire), 3):
            yield self.wire[offset:offset + 3]
        if self.fail:
            raise httpx.ReadError('SECRET upstream details')

    def close(self):
        self.closed = True


def frame(data):
    return ('data: ' + json.dumps(data, ensure_ascii=False) + '\r\n\r\n').encode()


def openai(text='你好'):
    return frame({'choices': [{'delta': {'content': text}}]}) + frame({'choices': [], 'usage': {'prompt_tokens': 12, 'completion_tokens': 4}}) + b'data: [DONE]\r\n\r\n'


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv('QA_TEST_KEY', 'secret-test-key')
    specs = [ModelSpec(id=n, model=n, base_url='https://upstream.test/v1', api_key_env=('QA_TEST_KEY',)) for n in ('primary', 'backup')]
    cfg = GatewayConfig(models={s.id:s for s in specs}, tiers={'fast':['primary','backup']}, tasks={}, sources=[])
    monkeypatch.setattr(stream, 'get_config', lambda: cfg)
    limiter.reset()
    usage.reset()
    yield cfg
    providers.set_transport_factory(None)
    limiter.reset()
    usage.reset()


def transport(handler):
    providers.set_transport_factory(lambda: httpx.MockTransport(handler))


def test_openai_fragments_usage_and_user_attribution():
    wire = Bytes(openai())
    def handler(request):
        body = json.loads(request.content)
        assert body['stream'] is True
        assert body['stream_options']['include_usage'] is True
        return httpx.Response(200, stream=wire)
    transport(handler)
    with user_scope('qa-stream-test'):
        events = list(stream.stream_text('system', 'question', user_id='qa-stream-test', prompt_version='v7'))
    assert events[0] == {'delta':'你好'}
    assert events[-1] == {'type':'usage','model':'primary','prompt_tokens':12,'completion_tokens':4,'estimated':False,'ok':True,'mock':False}
    assert wire.closed
    with SessionLocal() as session:
        call = session.scalars(select(LlmCall).where(LlmCall.user_id == 'qa-stream-test')).all()[-1]
        assert (call.prompt_version, call.prompt_name, call.estimated) == ('v7','qa.answer',0)
    assert usage.recent()[-1]['ok'] is True


def test_missing_key_no_answer(monkeypatch):
    monkeypatch.delenv('QA_TEST_KEY')
    transport(lambda _: pytest.fail('network used without key'))
    events = list(stream.stream_text('s','u'))
    assert len(events) == 1
    assert events[0]['mock'] is True and events[0]['ok'] is False
    assert events[0]['error'] == 'no_key'


def test_fallback_before_text_only():
    models = []
    def handler(request):
        models.append(json.loads(request.content)['model'])
        return httpx.Response(503, text='SECRET') if len(models) == 1 else httpx.Response(200, stream=Bytes(openai('backup')))
    transport(handler)
    events = list(stream.stream_text('s','u'))
    assert models == ['primary','backup']
    assert events[0]['error'] == 'server'
    assert events[1] == {'delta':'backup'}
    assert len(usage.recent()) == 2


def test_partial_failure_no_fallback_and_safe_error():
    requests = []
    wire = Bytes(frame({'choices':[{'delta':{'content':'partial'}}]}), fail=True)
    transport(lambda r: requests.append(r) or httpx.Response(200, stream=wire))
    iterator = stream.stream_text('s','u')
    assert next(iterator) == {'delta':'partial'}
    assert next(iterator)['error'] == 'connect'
    with pytest.raises(stream.StreamError) as exc:
        next(iterator)
    assert exc.value.code == 'connect' and 'SECRET' not in str(exc.value)
    assert len(requests) == 1 and wire.closed


def test_cancel_closes_response_records_failure_releases_slot():
    wire = Bytes(openai())
    transport(lambda _: httpx.Response(200, stream=wire))
    iterator = stream.stream_text('s','u')
    assert next(iterator)['delta']
    iterator.close()
    assert wire.closed
    assert usage.recent()[-1]['error'] == 'cancelled'
    assert all(v['in_flight'] == 0 for v in limiter.stats().values())


def test_anthropic_stream(isolated):
    isolated.models['primary'] = ModelSpec(id='primary',model='claude',protocol='anthropic',base_url='https://upstream.test',api_key_env=('QA_TEST_KEY',))
    wire = b''.join(frame(data) for data in [
        {'type':'message_start','message':{'usage':{'input_tokens':9,'output_tokens':0}}},
        {'type':'content_block_delta','delta':{'type':'text_delta','text':'回答'}},
        {'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':3}},
        {'type':'message_stop'},
    ])
    def handler(r):
        assert str(r.url).endswith('/v1/messages')
        assert r.headers['anthropic-version'] == providers.ANTHROPIC_VERSION
        return httpx.Response(200, stream=Bytes(wire))
    transport(handler)
    events = list(stream.stream_text('s','u'))
    assert events[0] == {'delta':'回答'}
    assert events[-1]['prompt_tokens'] == 9 and events[-1]['completion_tokens'] == 3
    assert events[-1]['estimated'] is False


@pytest.mark.parametrize('wire,error', [(b'data: {broken}\n\n','protocol'), (frame({'choices':[{'delta':{'content':'cut'}}]}),'truncated')])
def test_malformed_or_missing_terminal(wire,error,isolated):
    isolated.tiers['fast'] = ['primary']
    transport(lambda _: httpx.Response(200,stream=Bytes(wire)))
    events=[]
    with pytest.raises(stream.StreamError) as exc:
        for item in stream.stream_text('s','u'):
            events.append(item)
    assert exc.value.code == error
    assert events[-1]['ok'] is False and events[-1]['estimated'] is True


def test_unreported_usage_estimated_and_metered():
    from app.agent.token_meter import metered
    wire = frame({'choices':[{'delta':{'content':'answer'}}]}) + b'data: [DONE]\n\n'
    transport(lambda _: httpx.Response(200, stream=Bytes(wire)))
    with metered() as meter:
        events = list(stream.stream_text('system','question'))
    assert events[-1]['estimated'] is True
    assert events[-1]['completion_tokens'] > 0
    assert meter.calls == 1 and meter.tokens > 0


def test_sandbox_values_masked_before_upstream(monkeypatch):
    from app.agent.harness import leak
    monkeypatch.setattr(leak, 'sandbox_values', lambda *a, **kw: ['private phrase'])
    def handler(request):
        assert b'private phrase' not in request.content
        body = json.loads(request.content)
        assert all('[隐私已隐藏]' in message['content'] for message in body['messages'])
        return httpx.Response(200, stream=Bytes(openai()))
    transport(handler)
    assert list(stream.stream_text('system private phrase','user private phrase'))[-1]['ok']


@pytest.mark.parametrize('status,code',[(401,'auth'),(429,'rate_limited'),(400,'bad_request'),(503,'server')])
def test_classified_exhaustion_no_upstream_body_or_key(status,code,isolated,caplog):
    transport(lambda _: httpx.Response(status,text='secret-test-key raw private upstream body'))
    events=[]
    with pytest.raises(stream.StreamError) as exc:
        for event in stream.stream_text('s','u'):
            events.append(event)
    assert exc.value.code == code
    assert len(events) == 2
    assert all(e['error'] == code for e in events)
    assert 'secret-test-key' not in str(exc.value) + caplog.text
    assert 'raw private' not in json.dumps(events) + caplog.text


def test_multiline_sse_comments_and_ping():
    wire = (b': keepalive\n\nevent: message\ndata: {"choices":\ndata: [{"delta":{"content":"hello"}}]}\n\n'
            b'data: [DONE]\n\n')
    transport(lambda _:httpx.Response(200, stream=Bytes(wire)))
    events = list(stream.stream_text('s','u'))
    assert events[0] == {'delta':'hello'}
    assert events[-1]['ok'] is True
