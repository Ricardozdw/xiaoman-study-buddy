"""Apply the base privacy rules to every QA capability and stored context."""
from fastapi import HTTPException

from app.agent.harness import leak
from app.agent.harness.redact import redact_text
from app.privacy import redact_sensitive
from app.prompts import load_prompt
from app.tools.prompt_data import UNTRUSTED_DATA_RULE


def clean_text(user_id: str, text: str, max_len: int = 8000) -> str:
    try:
        hidden = leak.sandbox_values(user_id, strict=True)
    except Exception as exc:
        raise HTTPException(503, detail={"code": "privacy_unavailable", "message": "安全检查暂时不可用，请稍后重试。"}) from exc
    return redact_text(redact_sensitive(text)[0], extra_values=hidden, max_len=max_len)


def clean_payload(user_id: str, value):
    if isinstance(value, str):
        return clean_text(user_id, value)
    if isinstance(value, list):
        return [clean_payload(user_id, item) for item in value]
    if isinstance(value, dict):
        return {key: clean_payload(user_id, item) for key, item in value.items()}
    return value


def prompt(name: str) -> str:
    text = load_prompt(name, "v1", untrusted_data_rule=UNTRUSTED_DATA_RULE)
    leak.register_system_prompt(name + "@v1", text)
    return text
