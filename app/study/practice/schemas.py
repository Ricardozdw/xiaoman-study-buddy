"""练习线自己的输入输出约定，不修改共用类型。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Option(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: Literal["A", "B", "C", "D"]
    text: str = Field(min_length=1, max_length=1000)


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    page: int = Field(ge=1)
    quote: str = Field(min_length=2, max_length=2000)


class GeneratedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    stem: str = Field(min_length=3, max_length=2000)
    options: list[Option] = Field(min_length=2, max_length=4)
    answer: Literal["A", "B", "C", "D"]
    analysis: str = Field(min_length=1, max_length=3000)
    source: Source
    difficulty: Literal["easy", "medium", "hard"]
    knowledge_point: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def choices(self):
        ids = [o.id for o in self.options]
        texts = [o.text for o in self.options]
        if len(set(ids)) != len(ids) or len(set(texts)) != len(texts) or self.answer not in ids:
            raise ValueError("选项必须各不相同，答案必须在选项中")
        return self


class GeneratedQuiz(BaseModel):
    questions: list[GeneratedQuestion] = Field(min_length=1, max_length=5)


class CheckAnswer(BaseModel):
    index: int = Field(ge=0)
    answer: Literal["A", "B", "C", "D", "uncertain"]


class CheckedQuiz(BaseModel):
    answers: list[CheckAnswer] = Field(min_length=1, max_length=5)


class QuizBody(BaseModel):
    lecture_id: str = ""
    count: int = Field(default=5, ge=1, le=15)
    difficulty: Literal["easy", "medium", "hard"] = "easy"
    mode: Literal["practice", "review"] = "practice"
    question_ids: list[str] = Field(default_factory=list, max_length=15)
    task_id: str = ""


class AttemptBody(BaseModel):
    question_id: str
    answer: Literal["A", "B", "C", "D"]
    quiz_id: str = ""
    seconds: int = Field(default=0, ge=0, le=86400)


class ReportBody(BaseModel):
    question_id: str
    reason: str = Field(default="", max_length=1000)
    category: Literal["answer", "ambiguous", "source", "other"] | None = None
    quiz_id: str = ""
    attempt_id: str = ""


class ProgressBody(BaseModel):
    question_id: str
    answer: Literal["", "A", "B", "C", "D"] = ""
    paused: bool = False
    seconds: int = Field(default=0, ge=0, le=86400)
