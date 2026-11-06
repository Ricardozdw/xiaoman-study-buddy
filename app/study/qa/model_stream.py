"""QA-only streaming adapter using the gateway's routing, pool and accounting.

Deltas are raw model text. The QA service validates complete NDJSON sentences
and applies outbound guards before sending anything to a browser.
"""
from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass

import httpx

from app.agent import token_meter
from app.gateway import limiter, providers, usage
from app.gateway.config import ModelSpec, PROTOCOL_ANTHROPIC, get_config
from app.gateway.llm_gateway import _mask_sandbox


class StreamError(Exception):
    """Allowlisted classification; upstream text and credentials never escape."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass
class _State:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    text: str = ''
    done: bool = False


def _frames(response: httpx.Response, deadline: float) -> Iterator[str]:
    # httpx incrementally decodes UTF-8 and CR/LF across arbitrary byte boundaries.
    lines: list[str] = []
    size = 0
    for line in response.iter_lines():
        if time.monotonic() > deadline:
            raise StreamError('timeout')
        if not line:
            if lines:
                yield '\n'.join(lines)
            lines, size = [], 0
        elif line.startswith('data:'):
            value = line[5:]
            value = value[1:] if value.startswith(' ') else value
            size += len(value)
            if size > 1_000_000:
                raise StreamError('protocol')
            lines.append(value)
    # An event without its terminating empty line is an interrupted SSE frame.
    if lines:
        raise StreamError('truncated')


def _tokens(value):
    if type(value) is not int or value < 0:
        raise StreamError('protocol')
    return value


def _receive(response: httpx.Response, anthropic: bool, state: _State, deadline: float) -> Iterator[str]:
    for raw in _frames(response, deadline):
        if raw == '[DONE]' and not anthropic:
            state.done = True
            break
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError
            if data.get('error') or data.get('type') == 'error':
                raise StreamError('server')
            text = ''
            if anthropic:
                kind = data.get('type')
                if kind == 'message_start':
                    counts = data['message'].get('usage') or {}
                    if 'input_tokens' in counts:
                        state.prompt_tokens = _tokens(counts['input_tokens'])
                    if 'output_tokens' in counts:
                        state.completion_tokens = _tokens(counts['output_tokens'])
                elif kind == 'message_delta':
                    counts = data.get('usage') or {}
                    if 'output_tokens' in counts:
                        state.completion_tokens = _tokens(counts['output_tokens'])
                    if (data.get('delta') or {}).get('stop_reason') == 'max_tokens':
                        raise StreamError('truncated')
                elif kind == 'content_block_delta' and data.get('delta', {}).get('type') == 'text_delta':
                    text = data['delta']['text']
                elif kind == 'message_stop':
                    state.done = True
                    break
            else:
                counts = data.get('usage') or {}
                if 'prompt_tokens' in counts:
                    state.prompt_tokens = _tokens(counts['prompt_tokens'])
                if 'completion_tokens' in counts:
                    state.completion_tokens = _tokens(counts['completion_tokens'])
                choices = data.get('choices') or []
                if choices:
                    choice = choices[0]
                    if choice.get('finish_reason') in ('length', 'content_filter'):
                        raise StreamError('truncated')
                    text = (choice.get('delta') or {}).get('content') or ''
            if not isinstance(text, str):
                raise ValueError
        except (ValueError, TypeError, AttributeError, KeyError, IndexError):
            raise StreamError('protocol') from None
        if text:
            if len(state.text) + len(text) > 1_000_000:
                raise StreamError('protocol')
            state.text += text
            yield text
    if not state.done:
        raise StreamError('truncated')
    if not state.text:
        raise StreamError('empty')


def _request(spec, key, system, user, tier, timeout, max_tokens, state):
    anthropic = spec.protocol == PROTOCOL_ANTHROPIC
    if anthropic:
        headers = {'x-api-key': key, 'anthropic-version': providers.ANTHROPIC_VERSION}
        url = spec.base_url.rstrip('/') + ('/messages' if spec.base_url.rstrip('/').endswith('/v1') else '/v1/messages')
        body = {'model':spec.model, 'system':system, 'messages':[{'role':'user','content':user}], 'max_tokens':max_tokens}
    else:
        headers = {'Authorization':f'Bearer {key}'}
        url = spec.base_url.rstrip('/') + '/chat/completions'
        body = {'model':spec.model, 'messages':[{'role':'system','content':system},{'role':'user','content':user}], 'max_tokens':max_tokens}
        body.update(providers.kimi_params(spec, tier))
    body.update(spec.params)
    # Streaming and identity-bearing fields cannot be disabled by custom params.
    body.update(model=spec.model, stream=True)
    if not anthropic:
        body['stream_options'] = {**(body.get('stream_options') or {}), 'include_usage':True}
    client = providers._client(spec.base_url, headers.get('Authorization','') + headers.get('x-api-key',''))
    with client.stream('POST', url, json=body, headers=headers,
                       timeout=httpx.Timeout(timeout, connect=min(5.0, timeout))) as response:
        status = response.status_code
        if status >= 400:
            code = 'auth' if status in (401,403) else 'rate_limited' if status == 429 else 'server' if status >= 500 or status == 408 else 'bad_request'
            raise StreamError(code)
        yield from _receive(response, anthropic, state, time.monotonic() + timeout)


def _record(spec, state, *, request_id, task, tier, attempt, user_id, prompt_version, system, user, started, error, mock=False):
    estimated = state.prompt_tokens is None or state.completion_tokens is None
    tin = state.prompt_tokens if state.prompt_tokens is not None else token_meter.estimate_tokens(system) + token_meter.estimate_tokens(user) + 8
    tout = state.completion_tokens if state.completion_tokens is not None else token_meter.estimate_tokens(state.text)
    latency = (time.monotonic() - started) * 1000
    usage.record(request_id=request_id,task=task,tier=tier,spec=spec,attempt=attempt,ok=not error,latency_ms=latency,error=error,prompt_tokens=tin,completion_tokens=tout)
    from app.data_access.session import SessionLocal
    from app.study.common.db import ensure_schema
    from app.study.common.models import LlmCall
    ensure_schema()
    with SessionLocal() as session:
        session.add(LlmCall(id=uuid.uuid4().hex,user_id=user_id,capability='问答',prompt_name=task[:64],prompt_version=prompt_version[:16],model=spec.model[:128],prompt_tokens=tin,completion_tokens=tout,latency_ms=int(latency),ok=int(not error),estimated=int(estimated)))
        session.commit()
    token_meter.record_completion(system, user, state.text, task=task)
    event = dict(type='usage',model=spec.model,prompt_tokens=tin,completion_tokens=tout,estimated=estimated,ok=not error,mock=mock)
    if error:
        event['error'] = error
    return event


def stream_text(system: str, user: str, *, task: str = 'qa.answer', user_id: str = '', prompt_version: str = 'v1', timeout: float = 20, max_tokens: int = 1800) -> Iterator[dict]:
    """Yield raw deltas and per-attempt usage; never mix models after a delta.

    ``close()`` on this iterator closes the response and releases its limiter
    slot immediately. Cancellation is recorded without yielding during close.
    Missing keys produce one explicit mock usage event and no generated answer.
    """
    if timeout <= 0 or max_tokens <= 0:
        raise StreamError('bad_request')
    system, user = _mask_sandbox(system, user)
    # QA requests can run outside graph tracing; apply trusted user's sandbox too.
    from app.agent.harness.leak import sandbox_values
    from app.agent.harness.redact import mask_values
    hidden = sandbox_values(user_id, strict=True)
    system = mask_values(system, hidden, '[隐私已隐藏]')[0]
    user = mask_values(user, hidden, '[隐私已隐藏]')[0]
    cfg = get_config()
    target = cfg.tasks.get(task.strip().lower())
    from app.agent.budget_tiers import classify_difficulty, model_tier_for
    tier = target if target in ('fast','strong') else model_tier_for(classify_difficulty(task)).value
    chain = cfg.task_chain(task, tier)
    keyed = [(spec, spec.api_key()) for spec in chain if spec.has_key()]
    request_id = uuid.uuid4().hex[:12]
    if not keyed:
        yield _record(ModelSpec(id='qa-offline',model='mock',vendor='offline'), _State(), request_id=request_id,task=task,tier=tier,attempt=0,user_id=user_id,prompt_version=prompt_version,system=system,user=user,started=time.monotonic(),error='no_key',mock=True)
        return
    last_error = 'empty'
    for attempt, (spec,key) in enumerate(keyed):
        state, started, error = _State(), time.monotonic(), ''
        group = cfg.groups.get(spec.limit_group) or {}
        bucket = limiter.bucket(spec.group(),spec.max_concurrency if spec.max_concurrency is not None else group.get('max_concurrency'),spec.rpm if spec.rpm is not None else group.get('rpm'))
        event = None
        try:
            with bucket.slot(min(10.0, timeout)):
                with closing(_request(spec,key,system,user,tier,timeout,max_tokens,state)) as upstream:
                    for text in upstream:
                        yield {'delta':text}
        except GeneratorExit:
            error = 'cancelled'
            raise
        except StreamError as exc:
            error = exc.code
        except httpx.TimeoutException:
            error = 'timeout'
        except httpx.TransportError:
            error = 'connect'
        except limiter.Busy:
            error = 'busy'
        except Exception:
            error = 'protocol'
        finally:
            bucket.feedback(ok=not error,rate_limited=error == 'rate_limited')
            event = _record(spec,state,request_id=request_id,task=task,tier=tier,attempt=attempt,user_id=user_id,prompt_version=prompt_version,system=system,user=user,started=started,error=error)
        yield event
        if not error:
            return
        last_error = error
        if state.text:
            break
    raise StreamError(last_error) from None
