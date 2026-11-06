"""规则回复池：每次新作答随机取句，同一次作答刷新后保持一致。"""
import random

CORRECT_OPENINGS = (
    "答对了，这个点你抓住了。",
    "对，就是这个意思。",
    "这次判断很准。",
    "答得不错，思路是对的。",
    "这道题你答对了。",
    "选对了，继续往下看。",
    "没错，你理解到了关键。",
    "这个答案对啦。",
    "判断正确，给自己一点肯定。",
    "不错，这道题做对了。",
)
INCORRECT_OPENINGS = (
    "这题没选对，我们一起看看。",
    "这次没答对，也没关系。",
    "这个地方容易混淆，再理一理就好。",
    "这次选偏了，看看关键条件。",
    "先别急，我们换个角度看这道题。",
    "答案和你的选择不一样，看看原因。",
    "这一题先记下来，之后再练一遍。",
    "这里还需要巩固一下，没关系。",
    "先看看解析，再理一下思路。",
    "我们看看这道题的解题思路。",
)


def answer_feedback(correct: bool, confidence: str, attempt_id: str) -> str:
    # attempt_id 本身含随机性；用它作为种子，重传、刷新都不会改变同次反馈。
    opening = random.Random(attempt_id).choice(CORRECT_OPENINGS if correct else INCORRECT_OPENINGS)
    # 旧参数只作调用兼容，不再生成任何基于把握度的反馈。
    return opening
