"""讲解生成失败时网关返回的 fallback 不能被当成讲解存进缓存（否则用户再点也只看到占位）。"""
from app.study.v2 import lecture


def test_gateway_fallback_is_not_a_lecture():
    base = {"title": "t", "sections": [{"heading": "h", "content": lecture.PLACEHOLDER, "example": ""}]}
    assert lecture._is_fallback({**base, "_mode": "mock_fallback", "_model_error": "timeout"})
    assert lecture._is_fallback({**base, "_mode": "mock"})
    assert lecture._is_fallback({**base, "_parse": "empty_content"})
    assert lecture._is_fallback("not a dict")


def test_real_model_output_passes():
    out = {"title": "关键路径", "sections": [{"heading": "是什么", "content": "最长的那条路", "example": ""}],
           "_model": "deepseek-reasoner", "_tier": "strong"}
    assert not lecture._is_fallback(out)
