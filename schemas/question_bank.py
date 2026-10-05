from datetime import datetime

from pydantic import BaseModel


class ValidationErrorItem(BaseModel):
    question_id: str | None
    index: int
    field: str
    message: str


class ImportValidationErrorResponse(BaseModel):
    detail: str = "Question bank validation failed"
    errors: list[ValidationErrorItem]


class QuestionBankSummary(BaseModel):
    id: int
    name: str
    exam: str
    question_count: int


class QuestionListItem(BaseModel):
    id: int
    external_question_id: str
    section: str
    topic: str
    subtopic: str | None
    difficulty: str
    question_text: str
    source: str | None
    year: int | None
    shift: str | None


class QuestionListPage(BaseModel):
    items: list[QuestionListItem]
    total: int
    limit: int
    offset: int
    has_more: bool


class QuestionBankListItem(BaseModel):
    id: int
    name: str
    exam: str
    source_filename: str | None
    question_count: int
    created_at: datetime


class QuestionBankSectionBreakdown(BaseModel):
    section: str
    question_count: int


class QuestionOptionOut(BaseModel):
    key: str
    text: str


class QuestionDetailOut(BaseModel):
    id: int
    external_question_id: str
    section: str
    topic: str
    subtopic: str | None
    difficulty: str
    question_text: str
    options: list[QuestionOptionOut]
    correct_option_key: str
    explanation: str | None
    source: str | None
    year: int | None
    shift: str | None
