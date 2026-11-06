"""Offline corpus checks and explicitly enabled HTTP evaluation. Standard library only."""
from __future__ import annotations

import argparse
import codecs
import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


def load_corpus(path=None):
    return json.loads(Path(path or Path(__file__).with_name('corpus.json')).read_text(encoding='utf-8'))


def validate_corpus(corpus):
    errors = []
    if not isinstance(corpus, dict): return ['corpus must be an object']
    lecture = corpus.get('lecture', {})
    if not isinstance(lecture, dict): return ['lecture must be an object']
    if lecture.get('synthetic') is not True or not isinstance(lecture.get('disclaimer'), str) or '不是正式PMP' not in lecture['disclaimer']:
        errors.append('synthetic provenance/disclaimer required')
    pages = lecture.get('pages', [])
    if not isinstance(pages, list): return errors + ['pages must be a list']
    valid_pages = {}
    for page in pages:
        if not isinstance(page, dict) or type(page.get('page')) is not int or not isinstance(page.get('text'), str) or not page['text'].strip():
            errors.append('invalid page'); continue
        if page['page'] in valid_pages: errors.append('duplicate page')
        valid_pages[page['page']] = page['text']
    if set(valid_pages) != set(range(1, 9)): errors.append('exactly pages 1..8 required')
    cases = corpus.get('cases', [])
    if not isinstance(cases, list): return errors + ['cases must be a list']
    ids = set()
    inside = outside = 0
    for case in cases:
        if not isinstance(case, dict): errors.append('invalid case'); continue
        cid = case.get('id')
        if not isinstance(cid, str) or not cid or cid in ids: errors.append('invalid/duplicate case id')
        if isinstance(cid, str): ids.add(cid)
        if not isinstance(case.get('question'), str) or not case['question'].strip(): errors.append(f'{cid}: empty question')
        expected, words = case.get('expected'), case.get('answer_keywords')
        if case.get('in_material') is True:
            inside += 1
            if not isinstance(expected, list) or not expected: errors.append(f'{cid}: evidence required')
            if not isinstance(words, list) or not words or any(not isinstance(w, str) or not w.strip() for w in words): errors.append(f'{cid}: keywords required')
        elif case.get('in_material') is False:
            outside += 1
            if expected != [] or words != []: errors.append(f'{cid}: external case must not invent evidence')
        else: errors.append(f'{cid}: boolean scope required')
        for ref in expected if isinstance(expected, list) else []:
            if not isinstance(ref, dict) or type(ref.get('page')) is not int or not isinstance(ref.get('quote'), str) or not ref['quote'].strip() or ref['quote'] not in valid_pages.get(ref['page'], ''):
                errors.append(f'{cid}: invalid expected quote/page')
    if (inside, outside) != (30, 20): errors.append('30 in-material and 20 out-of-material cases required')
    return errors


def parse_sse(chunks):
    """Consume timestamped raw bytes; timestamp first nonblank decoded delta, not meta."""
    decoder = codecs.getincrementaldecoder('utf-8')()
    buffer, frames, data = '', [], []
    first = None
    done = False

    def dispatch(ms):
        nonlocal first, done
        if not data: return
        payload = '\n'.join(data)
        data.clear()
        if done: raise ValueError('data after DONE')
        if payload == '[DONE]': done = True; return
        try: frame = json.loads(payload)
        except (ValueError, TypeError) as exc: raise ValueError('malformed SSE JSON') from exc
        if not isinstance(frame, dict): raise ValueError('SSE payload must be object')
        frames.append(frame)
        delta = frame.get('delta')
        if isinstance(delta, str) and delta.strip() and first is None: first = ms

    try:
        for ms, raw in chunks:
            buffer += decoder.decode(raw)
            # CRLF may split between network reads. Only consume complete LF lines.
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                line = line.removesuffix('\r')
                if line == '': dispatch(ms)
                elif line.startswith('data:'): data.append(line[5:].removeprefix(' '))
        buffer += decoder.decode(b'', final=True)
    except UnicodeDecodeError as exc: raise ValueError('malformed UTF-8') from exc
    if buffer.strip() or data: raise ValueError('truncated SSE event')
    return {'frames': frames, 'first_text_ms': first, 'done': done}


def score_case(case, pages, frames, *, lecture_id, first_text_ms, done):
    failures = []
    meta = [f for f in frames if f.get('type') == 'meta']
    complete = [f for f in frames if f.get('type') == 'complete']
    refs_frames = [f for f in frames if f.get('type') == 'references']
    text = ''.join(f['delta'] for f in frames if isinstance(f.get('delta'), str))
    refs = []
    for frame in refs_frames:
        if not isinstance(frame.get('references'), list): failures.append('malformed_references')
        else: refs.extend(frame['references'])
    if not done: failures.append('missing_DONE')
    if len(meta) != 1 or len(complete) != 1: failures.append('missing_or_duplicate_contract_frames')
    m, c = (meta[0] if meta else {}), (complete[0] if complete else {})
    if m.get('mock') is not False or c.get('mock') is not False: failures.append('mock_or_unknown_provenance')
    if c.get('ok') is not True: failures.append('incomplete_or_failed')
    if not m.get('message_id') or m.get('message_id') != c.get('message_id'): failures.append('message_id_mismatch')
    if not m.get('thread_id') or m.get('intent') != 'qa' or m.get('lecture_id') != lecture_id: failures.append('wrong_context')
    if c.get('in_material') is not case['in_material']: failures.append('wrong_scope')
    removed = c.get('citation_failures')
    if type(removed) is not int or removed < 0: failures.append('missing_citation_failure_count'); removed = 0
    if removed: failures.append('server_removed_invalid_citations')
    if any(f.get('type') in ('error', 'handoff') for f in frames): failures.append('error_or_handoff')
    if not text.strip() or first_text_ms is None: failures.append('no_actual_text')
    if not refs_frames: failures.append('missing_references_frame')
    page_text = {p['page']: p['text'] for p in pages}
    invalid = 0
    for ref in refs:
        if not isinstance(ref, dict) or ref.get('lecture_id') != lecture_id or type(ref.get('page')) is not int or not isinstance(ref.get('quote'), str) or not ref['quote'].strip() or ref['quote'] not in page_text.get(ref['page'], ''):
            invalid += 1
    if invalid: failures.append('invalid_citations')
    if case['in_material']:
        if not refs: failures.append('no_citations')
        for expected in case['expected']:
            if not any(isinstance(r, dict) and r.get('page') == expected['page'] and isinstance(r.get('quote'), str) and expected['quote'] in r['quote'] for r in refs):
                failures.append('missing_expected_evidence'); break
        if not all(word in text for word in case['answer_keywords']): failures.append('missing_answer_keywords')
    else:
        if refs or re.search(r'(?:【|\[)?第\s*\d+\s*页', text): failures.append('out_of_material_citation')
        if not re.search(r'(?:资料|讲义|材料|原文).{0,24}(?:没有|未提供|未包含|未涉及|不包含|不涵盖|未找到|没提到|未提到|没找到|未涵盖|无依据|不足)', text):
            failures.append('missing_explicit_scope_notice')
    citation_errors = {'no_citations', 'invalid_citations', 'missing_expected_evidence', 'server_removed_invalid_citations', 'missing_references_frame', 'malformed_references', 'missing_citation_failure_count'}
    citation_passed = bool(refs) and not any(f in citation_errors for f in failures) and m.get('mock') is False and c.get('mock') is False and c.get('ok') is True and c.get('in_material') is True and done and bool(text.strip()) and len(meta) == len(complete) == 1
    return {'citation_passed': citation_passed, 'case_id': case['id'], 'in_material': case['in_material'], 'passed': not failures,
            'failures': list(dict.fromkeys(failures)), 'answer': text, 'references': refs,
            'citation_failures': invalid + removed, 'first_text_ms': first_text_ms,
            'meta': {k: m.get(k) for k in ('mock', 'intent', 'lecture_id')},
            'complete': {k: c.get(k) for k in ('ok', 'mock', 'in_material', 'citation_failures')}}


def summarize(results):
    inside = [r for r in results if r['in_material']]
    outside = [r for r in results if not r['in_material']]
    latency = sorted(r['first_text_ms'] for r in results if r.get('first_text_ms') is not None)
    timely = bool(results) and len(latency) == len(results) and max(latency) <= 5000
    citation_rate = sum(r.get('citation_passed', False) for r in inside) / len(inside) if inside else None
    return {'thresholds': {'citation_pass_rate_min': 0.95, 'external_honesty_rate_min': 1.0, 'first_text_ms_max': 5000},
            'in_material_citation_pass_rate': citation_rate, 'first_text_within_5s': timely,
            'mode': 'live', 'total': len(results), 'passed_cases': sum(r['passed'] for r in results),
            'passed': len(results) == 50 and all(r['passed'] for r in results) and timely,
            'in_material_pass_rate': sum(r['passed'] for r in inside) / len(inside) if inside else None,
            'out_of_material_pass_rate': sum(r['passed'] for r in outside) / len(outside) if outside else None,
            'citation_failures_including_removed': sum(r.get('citation_failures', 0) for r in results),
            'first_actual_delta_p50_ms': latency[(len(latency)-1)//2] if latency else None,
            'first_actual_delta_p95_ms': latency[max(0, (95*len(latency)+99)//100-1)] if latency else None,
            'latency_sample_count': len(latency),
            'note': '关键词和原句是自动代理指标；语义质量仍需人工复核。HTTP 时间含网络，非 complete.first_text_ms。'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirect refused: protect session cookie')


def evaluate_http(base_url, cookie, lecture_id, case, pages, timeout):
    request = Request(base_url.rstrip('/') + '/api/chat/stream',
                      data=json.dumps({'message': case['question'], 'lecture_id': lecture_id}).encode(),
                      headers={'Content-Type': 'application/json', 'Accept': 'text/event-stream', 'Cookie': cookie}, method='POST')
    started = time.perf_counter()
    with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
        if 'text/event-stream' not in response.headers.get('Content-Type', ''): raise ValueError('not SSE')
        def chunks():
            total = 0
            while True:
                if time.perf_counter() - started > timeout: raise ValueError('stream deadline exceeded')
                block = response.read1(4096)
                if not block: break
                total += len(block)
                if total > 2_000_000: raise ValueError('stream exceeds size limit')
                yield round((time.perf_counter()-started)*1000, 3), block
        parsed = parse_sse(chunks())
    return score_case(case, pages, **parsed, lecture_id=lecture_id)


def main(argv=None):
    parser = argparse.ArgumentParser(description='自编公开讲义 QA：默认离线检查；--live 才会请求服务和模型。')
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--base-url')
    parser.add_argument('--cookie-file', type=Path, help='UTF-8 JSON {"cookie":"session=..."}，不写入结果')
    parser.add_argument('--lecture-id', help='用户已经通过资料线导入同一讲义后的真实 ID')
    parser.add_argument('--output', type=Path, default=Path('work/qa-eval-results.json'))
    parser.add_argument('--export-lecture', type=Path, help='只输出讲义 JSON，供资料线显式导入；不写数据库')
    parser.add_argument('--timeout', type=float, default=60)
    args = parser.parse_args(argv)
    corpus = load_corpus(args.corpus)
    errors = validate_corpus(corpus)
    if errors: parser.error('; '.join(errors))
    if args.export_lecture:
        args.export_lecture.parent.mkdir(parents=True, exist_ok=True)
        args.export_lecture.write_text(json.dumps(corpus['lecture'], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if not args.live:
        print(json.dumps({'mode': 'offline', 'corpus_valid': True, 'pages': 8, 'in_material': 30, 'out_of_material': 20,
                          'live_evaluated': False, 'note': '离线校验不代表模型质量、引用率或延迟达标。'}, ensure_ascii=False))
        return 0
    if not args.base_url or not args.cookie_file or not args.lecture_id: parser.error('--live requires --base-url, --cookie-file and --lecture-id')
    url = urlsplit(args.base_url)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
        parser.error('--base-url must be an origin without credentials/path/query')
    if url.scheme != 'https' and url.hostname not in ('localhost', '127.0.0.1', '::1'): parser.error('remote cookies require HTTPS')
    if args.timeout <= 0: parser.error('timeout must be positive')
    try:
        cookie = json.loads(args.cookie_file.read_text(encoding='utf-8'))['cookie']
        if not isinstance(cookie, str) or not cookie.strip() or '\r' in cookie or '\n' in cookie: raise ValueError()
    except (ValueError, KeyError, OSError, TypeError): parser.error('invalid cookie file (expected JSON cookie string)')
    # Preflight validates the uploaded lecture before spending 50 model requests.
    req = Request(args.base_url.rstrip('/') + '/api/lectures/' + quote(args.lecture_id, safe='') + '/pages', headers={'Cookie': cookie})
    try:
        with build_opener(NoRedirect()).open(req, timeout=args.timeout) as response:
            actual = json.loads(response.read(2_000_000))
        if isinstance(actual, dict) and isinstance(actual.get('data'), dict): actual = actual['data']
        actual_pages = actual.get('pages') if isinstance(actual, dict) else None
        expected_pages = corpus['lecture']['pages']
        if not isinstance(actual_pages, list) or len(actual_pages) != len(expected_pages): raise ValueError('page count')
        # Permit metadata/line ending differences, never unrelated or partial material.
        if any(str(got.get('text', '')).replace('\r\n', '\n').strip() != want['text'].strip() or got.get('page') != want['page'] for got, want in zip(actual_pages, expected_pages)): raise ValueError('page contents')
    except Exception as exc:
        parser.error('lecture preflight failed: import the exact exported 8-page lecture first (' + type(exc).__name__ + ')')
    results = []
    for case in corpus['cases']:
        try: result = evaluate_http(args.base_url, cookie, args.lecture_id, case, expected_pages, args.timeout)
        except Exception as exc:
            # Exception messages may contain headers/URLs; persist only error class.
            result = {'case_id': case['id'], 'in_material': case['in_material'], 'passed': False,
                      'failures': ['transport_or_protocol_' + type(exc).__name__], 'citation_failures': 0, 'first_text_ms': None}
        results.append(result)
        payload = {'summary': summarize(results), 'results': results}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(case['id'] + ': ' + ('PASS' if result['passed'] else 'FAIL'))
    print(json.dumps(payload['summary'], ensure_ascii=False))
    return 0 if payload['summary']['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
