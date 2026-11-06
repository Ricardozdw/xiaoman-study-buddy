"""Offline fixtures test the evaluator, never claim actual model quality."""
import copy
import json
import pytest

from app.study.qa.evals.runner import load_corpus, validate_corpus, score_case, parse_sse, summarize


def case_and_pages():
    return ({'id': 'q1', 'in_material': True, 'question': '甲多少天？',
             'expected': [{'page': 1, 'quote': '甲工期为3天。'}], 'answer_keywords': ['3天']},
            [{'page': 1, 'text': '示例：甲工期为3天。'}])


def frames():
    return [
        {'type': 'meta', 'mock': False, 'intent': 'qa', 'lecture_id': 'uploaded', 'message_id': 'm', 'thread_id': 't'},
        {'delta': '甲工期为3天。【第1页】'},
        {'type': 'references', 'references': [{'lecture_id': 'uploaded', 'page': 1, 'quote': '甲工期为3天。'}]},
        {'type': 'complete', 'ok': True, 'mock': False, 'in_material': True, 'citation_failures': 0, 'message_id': 'm'},
    ]


def test_real_answer_requires_correct_evidence_and_keywords():
    case, pages = case_and_pages()
    result = score_case(case, pages, frames(), lecture_id='uploaded', first_text_ms=25, done=True)
    assert result['passed'] and result['first_text_ms'] == 25
    for mutation in ('empty_refs', 'wrong_page', 'wrong_quote', 'wrong_lecture', 'missing_keywords', 'removed_citation', 'mock', 'failed', 'missing_delta', 'disconnect'):
        data = copy.deepcopy(frames())
        if mutation == 'empty_refs': data[2]['references'] = []
        if mutation == 'wrong_page': data[2]['references'][0]['page'] = 7
        if mutation == 'wrong_quote': data[2]['references'][0]['quote'] = '不存在的原句'
        if mutation == 'wrong_lecture': data[2]['references'][0]['lecture_id'] = 'other'
        if mutation == 'missing_keywords': data[1]['delta'] = '甲很快完成。'
        if mutation == 'removed_citation': data[3]['citation_failures'] = 1
        if mutation == 'mock': data[3]['mock'] = True
        if mutation == 'failed': data[3]['ok'] = False
        if mutation == 'missing_delta': data[1] = {'type': 'heartbeat'}
        result = score_case(case, pages, data, lecture_id='uploaded', first_text_ms=25,
                            done=mutation != 'disconnect')
        assert not result['passed'], mutation


def test_out_of_material_requires_explicit_scope_and_no_fabricated_citations():
    case, pages = case_and_pages()
    case.update(in_material=False, expected=[], answer_keywords=[])
    data = frames()
    data[1]['delta'] = '这份资料没有提供这个信息。'
    data[2]['references'] = []
    data[3]['in_material'] = False
    assert score_case(case, pages, data, lecture_id='uploaded', first_text_ms=5, done=True)['passed']
    data[1]['delta'] = '答案是42。'
    assert not score_case(case, pages, data, lecture_id='uploaded', first_text_ms=5, done=True)['passed']
    data[1]['delta'] = '资料没有。请看【第99页】。'
    assert not score_case(case, pages, data, lecture_id='uploaded', first_text_ms=5, done=True)['passed']


def test_partial_sse_unicode_comments_and_first_actual_delta():
    payload = ': heartbeat\r\n\r\ndata: {"type":"meta"}\r\n\r\ndata: {"delta":""}\n\ndata: {"delta":"甲"}\n\ndata: [DONE]\n\n'.encode()
    cut = payload.index('甲'.encode()) + 1
    parsed = parse_sse([(10, payload[:cut]), (85, payload[cut:])])
    assert parsed['first_text_ms'] == 85
    assert parsed['done'] is True
    assert parsed['frames'][-1] == {'delta': '甲'}
    with pytest.raises(ValueError): parse_sse([(1, b'data: garbage\n\n')])
    with pytest.raises(ValueError): parse_sse([(1, b'data: {"delta":"x"}')])


def test_corpus_has_30_grounded_and_20_external_cases_and_rejects_malformed():
    corpus = load_corpus()
    assert validate_corpus(corpus) == []
    assert len(corpus['lecture']['pages']) == 8
    assert sum(c['in_material'] for c in corpus['cases']) == 30
    assert sum(not c['in_material'] for c in corpus['cases']) == 20
    for edit in ('empty_expected', 'bad_quote', 'duplicate_id', 'blank_keyword', 'missing_disclaimer', 'external_evidence'):
        data = copy.deepcopy(corpus)
        if edit == 'empty_expected': data['cases'][0]['expected'] = []
        if edit == 'bad_quote': data['cases'][0]['expected'][0]['quote'] = '假原句'
        if edit == 'duplicate_id': data['cases'][1]['id'] = data['cases'][0]['id']
        if edit == 'blank_keyword': data['cases'][0]['answer_keywords'] = ['']
        if edit == 'missing_disclaimer': data['lecture']['synthetic'] = False
        if edit == 'external_evidence': data['cases'][-1]['expected'] = [{'page': 1, 'quote': 'x'}]
        assert validate_corpus(data), edit


def test_summary_empty_and_missing_evidence_cannot_vacuously_pass():
    result = summarize([])
    assert result['passed'] is False and result['total'] == 0
    case, pages = case_and_pages()
    score = score_case(case, pages, [], lecture_id='uploaded', first_text_ms=None, done=True)
    assert not score['passed']
    assert summarize([score])['passed'] is False


def test_summary_tracks_required_thresholds_and_slow_first_text():
    case, pages = case_and_pages()
    good = score_case(case, pages, frames(), lecture_id='uploaded', first_text_ms=5001, done=True)
    summary = summarize([good])
    assert summary['first_text_within_5s'] is False
    assert summary['in_material_citation_pass_rate'] == 1.0
    assert summary['thresholds'] == {'citation_pass_rate_min': 0.95, 'external_honesty_rate_min': 1.0, 'first_text_ms_max': 5000}


def test_default_cli_never_uses_network_and_live_needs_explicit_inputs(monkeypatch, capsys, tmp_path):
    from app.study.qa.evals import runner
    def forbidden(*args, **kwargs): raise AssertionError('offline must not access network')
    monkeypatch.setattr(runner, 'build_opener', forbidden)
    assert runner.main(['--export-lecture', str(tmp_path / 'lecture.json')]) == 0
    assert json.loads(capsys.readouterr().out)['live_evaluated'] is False
    assert len(json.loads((tmp_path / 'lecture.json').read_text())['pages']) == 8
    with pytest.raises(SystemExit) as exc: runner.main(['--live'])
    assert exc.value.code == 2


def test_http_reader_handles_transport_bytes_fixture_only(monkeypatch):
    from io import BytesIO
    from app.study.qa.evals import runner
    case, pages = case_and_pages()
    payload = ''.join('data: ' + json.dumps(f, ensure_ascii=False) + '\n\n' for f in frames()).encode() + b'data: [DONE]\n\n'
    class Response(BytesIO):
        headers = {'Content-Type': 'text/event-stream'}
        def read1(self, count): return self.read(7)  # Force Unicode and frame splits.
    class Opener:
        def open(self, request, timeout):
            assert json.loads(request.data)['lecture_id'] == 'uploaded'
            assert request.get_header('Cookie') == 'session=offline-test'
            return Response(payload)
    monkeypatch.setattr(runner, 'build_opener', lambda *args: Opener())
    result = runner.evaluate_http('http://127.0.0.1', 'session=offline-test', 'uploaded', case, pages, 2)
    assert result['passed']
    assert result['first_text_ms'] >= 0


def test_mock_and_failed_streams_never_raise_citation_quality_score():
    case, pages = case_and_pages()
    for field, value in [('mock', True), ('ok', False)]:
        data = frames()
        data[-1][field] = value
        result = score_case(case, pages, data, lecture_id='uploaded', first_text_ms=15, done=True)
        assert summarize([result])['in_material_citation_pass_rate'] == 0


def test_invalid_disclaimer_type_is_reported_not_crashed():
    corpus = load_corpus()
    corpus['lecture']['disclaimer'] = None
    assert validate_corpus(corpus)
