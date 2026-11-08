"""出题答案位置：模型偏爱 A，落库前按题干哈希重排，整体在 A–D 上均匀，且同一道题结果固定。"""
from collections import Counter

from app.study.practice.capabilities import balance_answer
from app.study.practice.schemas import GeneratedQuestion


def make(stem, answer="A"):
    return GeneratedQuestion.model_validate({
        "stem": stem, "answer": answer, "analysis": "资料写明了这一点。", "knowledge_point": "kp",
        "difficulty": "easy", "source": {"page": 1, "quote": "原文一句"},
        "options": [{"id": "A", "text": "正确项"}, {"id": "B", "text": "干扰一"}, {"id": "C", "text": "干扰二"}, {"id": "D", "text": "干扰三"}],
    })


def test_correct_text_kept_and_answer_points_to_it():
    q = balance_answer(make("项目的关键路径是什么？"))
    assert {o.text for o in q.options} == {"正确项", "干扰一", "干扰二", "干扰三"}
    assert next(o.text for o in q.options if o.id == q.answer) == "正确项"
    assert [o.id for o in q.options] == ["A", "B", "C", "D"]
    assert [o.text for o in q.options if o.text != "正确项"] == ["干扰一", "干扰二", "干扰三"]  # 干扰项相对顺序不变


def test_same_question_same_result():
    assert balance_answer(make("同一道题")).answer == balance_answer(make("同一道题")).answer


def test_spreads_over_all_positions():
    counts = Counter(balance_answer(make(f"第 {i} 道题的题干")).answer for i in range(200))
    assert set(counts) == {"A", "B", "C", "D"}
    assert max(counts.values()) < 80  # 不再集中在一个位置（均匀约 50）
