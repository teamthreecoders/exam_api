from pydantic import BaseModel, Field


class TestSectionSelectionIn(BaseModel):
    section: str
    question_count: int = Field(gt=0)
    time_limit_seconds: int | None = Field(default=None, gt=0)
    topics: list[str] | None = None
    difficulties: list[str] | None = None
    year: int | None = None
    source: str | None = None


class TestCreateRequest(BaseModel):
    name: str
    exam: str = "SSC CGL"
    mode: str
    exam_config_id: int | None = None
    randomize_questions: bool = False
    randomize_options: bool = False
    sections: list[TestSectionSelectionIn]
    # When set, every section's questions are pulled only from this one
    # imported JSON file instead of the whole shared question bank.
    question_bank_id: int | None = None


class PrivateTestSectionIn(BaseModel):
    section: str
    # Empty/None = any topic in the section.
    topics: list[str] | None = None
    question_count: int = Field(gt=0, le=100)
    time_limit_seconds: int = Field(gt=0, le=3 * 60 * 60)


class PrivateTestCreateRequest(BaseModel):
    """What a regular user may specify. Everything else (exam config,
    difficulty/year/source filters, bank scoping, ordering) is fixed:
    questions are always drawn at random from the whole question bank."""

    name: str = Field(min_length=1, max_length=255)
    sections: list[PrivateTestSectionIn] = Field(min_length=1, max_length=10)


class CatalogTopic(BaseModel):
    topic: str
    question_count: int


class CatalogSection(BaseModel):
    section: str
    question_count: int
    topics: list[CatalogTopic]


class TestSectionSummary(BaseModel):
    section: str
    question_count: int
    time_limit_seconds: int


class TestSummary(BaseModel):
    id: int
    name: str
    exam: str
    mode: str
    randomize_questions: bool
    randomize_options: bool
    visibility: str
    is_mine: bool
    sections: list[TestSectionSummary]
