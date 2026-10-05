from datetime import datetime

from pydantic import BaseModel


class OptionOut(BaseModel):
    key: str
    text: str


class AttemptSummaryOut(BaseModel):
    attempt_id: int
    test_id: int
    test_name: str
    status: str
    started_at: datetime
    submitted_at: datetime | None
    total_questions: int | None
    attempted: int | None
    correct: int | None
    incorrect: int | None
    unattempted: int | None
    score: float | None
    accuracy: float | None
    percentage: float | None
    total_time_seconds: int | None


class QuestionStateOut(BaseModel):
    test_question_id: int
    order_index: int
    question_text: str
    options: list[OptionOut]
    section: str
    status: str
    selected_option_key: str | None
    time_spent_seconds: int


class SectionStateOut(BaseModel):
    test_section_id: int
    section: str
    order_index: int
    status: str
    started_at: datetime | None
    ends_at: datetime | None
    seconds_remaining: int | None


class AttemptStateOut(BaseModel):
    attempt_id: int
    status: str
    current_section: SectionStateOut | None
    sections: list[SectionStateOut]
    questions: list[QuestionStateOut]


class AnswerRequest(BaseModel):
    selected_option_key: str | None = None


class MarkRequest(BaseModel):
    marked: bool


class FullQuestionOut(BaseModel):
    test_question_id: int
    test_section_id: int
    order_index: int
    question_text: str
    options: list[OptionOut]


class FullSectionOut(BaseModel):
    test_section_id: int
    section: str
    order_index: int
    time_limit_seconds: int


class AttemptFullStateOut(BaseModel):
    """Everything needed to run the exam entirely client-side after this one
    fetch: all sections (with their fixed duration) and all questions across
    every section, with no correct answers included. The frontend derives
    each section's cutoff itself (`started_at` + cumulative `time_limit_seconds`)
    and only talks to the server again at submit."""

    attempt_id: int
    status: str
    started_at: datetime
    sections: list[FullSectionOut]
    questions: list[FullQuestionOut]


class BulkAnswerIn(BaseModel):
    test_question_id: int
    selected_option_key: str | None = None
    visited: bool = False
    marked_for_review: bool = False
    time_spent_seconds: int = 0


class BulkSubmitRequest(BaseModel):
    answers: list[BulkAnswerIn] = []


class QuestionResultOut(BaseModel):
    test_question_id: int
    section: str
    topic: str
    difficulty: str
    question_text: str
    options: list[OptionOut]
    selected_option_key: str | None
    correct_option_key: str
    is_correct: bool | None
    status: str
    time_spent_seconds: int
    explanation: str | None


class SectionResultOut(BaseModel):
    section: str
    attempted: int
    correct: int
    incorrect: int
    accuracy: float
    avg_time_seconds: float


class AttemptResultOut(BaseModel):
    attempt_id: int
    status: str
    total_questions: int
    attempted: int
    correct: int
    incorrect: int
    unattempted: int
    score: float
    accuracy: float
    percentage: float
    total_time_seconds: int
    sections: list[SectionResultOut]
    questions: list[QuestionResultOut]
