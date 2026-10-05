from pydantic import BaseModel, Field


class ExamConfigSectionIn(BaseModel):
    name: str
    question_count: int = Field(gt=0)
    time_limit_seconds: int = Field(gt=0)


class ExamConfigCreate(BaseModel):
    exam: str
    name: str
    marks_per_correct: float
    negative_marks: float = Field(ge=0, description="Positive magnitude subtracted per wrong answer")
    sections: list[ExamConfigSectionIn]


class ExamConfigSectionOut(BaseModel):
    name: str
    question_count: int
    time_limit_seconds: int


class ExamConfigOut(BaseModel):
    id: int
    exam: str
    name: str
    marks_per_correct: float
    negative_marks: float
    sections: list[ExamConfigSectionOut]
