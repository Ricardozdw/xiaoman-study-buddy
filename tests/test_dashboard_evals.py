import json
from types import SimpleNamespace

import pytest

from evals.compare import compare
from evals.export_bad_cases import export_rows
from evals.run import build_report, grade, load_cases


def test_grader_does_not_turn_expected_into_actual():
    assert grade({"answer":"wrong"}, {"answer":"correct"})[0] is False
    assert grade({"nested":[{"value":2}]}, {"nested.0.value":2})[0] is True
    assert grade({}, {"answer":"correct"})[0] is False


def test_gate_requires_missing_lines_and_detects_dataset_changes():
    cases=[{"id":"x", "kind":"dashboard", "capability":"dashboard", "checks":{"value":1}}]
    results=[{"id":"x", "kind":"dashboard", "capability":"dashboard", "state":"completed", "passed":True}]
    report=build_report(cases, results, "offline", None)
    assert report["score"] == 1 and not report["release_ready"]
    assert not report["coverage"]["qa_absent"]["ready"]
    changed=build_report(cases+[{"id":"new"}], results, "offline", None, report)
    assert changed["regressions"]
    failed=build_report(cases, [{**results[0],"passed":False}], "offline", None, report)
    assert failed["regressions"] == ["x"]
    revised=build_report([{**cases[0], "prompt":{"name":"qa.answer", "version":"v2"}}], results, "offline", None, report)
    assert not revised["regressions"]


def test_no_model_recommendation_from_offline_scores():
    report={"dataset_sha256":"same", "mode":"offline", "model":"deepseek-flash", "release_ready":False,"results":[]}
    outcome=compare(report, {**report,"model":"deepseek-v4-pro"})
    assert not outcome["ready"] and "暂不确定" in outcome["recommendation"]
    with pytest.raises(ValueError):
        compare(report, {**report,"dataset_sha256":"changed","model":"deepseek-v4-pro"})


def test_fixed_cases_without_public_evidence_are_not_silently_skipped():
    row=SimpleNamespace(id="one",status="已修复",input_json='{}')
    assert export_rows([row]) == ([], ["one"])
    row.input_json=json.dumps({"public_sample":True,"evaluation":{"capability":"qa_absent","prompt":{"name":"qa.answer","version":"v2"},"payload":{"question":"公开问题"},"checks":{"absent":True}}})
    cases, blocked=export_rows([row])
    assert not blocked and cases[0]["prompt"]["version"] == "v2"
    assert "expected_output" not in cases[0]


@pytest.mark.parametrize("actual,expected", [(True,1),(False,0),({"answer":True},{"answer":1}),([True],[1])])
def test_boolean_is_not_a_numeric_answer(actual,expected):
    assert grade({"result":actual},{"result":expected})[0] is False


def test_offline_cases_cannot_stand_in_for_ai_quality(tmp_path):
    (tmp_path/"fake.json").write_text(json.dumps([{"id":"fake-qa","kind":"dashboard","capability":"qa_citation","payload":{},"checks":{"answer":True}}]))
    with pytest.raises(ValueError,match="不能用看板"):
        load_cases(tmp_path)


def _complete_samples():
    from evals.run import ROOT
    requirements=json.loads((ROOT/"evals/manifest.json").read_text())["required"]
    cases,results=[],[]
    for capability,requirement in requirements.items():
        for index in range(requirement["minimum_cases"]+1):
            case={"id":f"{capability}-{index}","kind":"dashboard" if capability=="dashboard" else "ai","capability":capability,"payload":{},"checks":{"answer":True}}
            cases.append(case)
            results.append({"id":case["id"],"kind":case["kind"],"capability":capability,"state":"completed","passed":True,"model":"candidate"})
    return cases,results


def test_fixed_case_failure_is_never_averaged_away():
    cases,results=_complete_samples()
    assert build_report(cases,results,"live","candidate")["release_ready"]
    position=next(i for i,c in enumerate(cases) if c["capability"]=="qa_citation")
    cases[position]["regression"]=True
    results[position]["passed"]=False
    report=build_report(cases,results,"live","candidate")
    assert report["coverage"]["qa_citation"]["ready"]
    assert report["fixed_case_failures"] == [cases[position]["id"]]
    assert not report["release_ready"]


def test_missing_or_misattributed_results_block_release():
    cases,results=_complete_samples()
    assert not build_report(cases,results[1:],"live","candidate")["release_ready"]
    results[0]["passed"]="yes"
    report=build_report(cases,results,"live","candidate")
    assert report["data_errors"] and not report["release_ready"]


def test_model_comparison_requires_the_same_prompt_versions():
    report={"dataset_sha256":"same","mode":"live","model":"deepseek-flash","release_ready":True,"results":[],"prompts":{"x":{"name":"qa.answer","version":"v1"}}}
    with pytest.raises(ValueError,match="相同提示词版本"):
        compare(report,{**report,"model":"deepseek-v4-pro","prompts":{"x":{"name":"qa.answer","version":"v2"}}})
