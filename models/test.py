import enum

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from models.mixins import TimestampMixin


class TestMode(str, enum.Enum):
    full_mock = "full_mock"
    section_test = "section_test"
    topic_test = "topic_test"
    custom = "custom"


class Test(Base, TimestampMixin):
    """A generated test instance: its question set and section/timing rules
    are fixed at creation time (copied from the exam config and the question
    bank), so later edits to either never change a test that already exists."""

    __tablename__ = "tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    exam: Mapped[str] = mapped_column(String(100), nullable=False)
    mode: Mapped[TestMode] = mapped_column(SAEnum(TestMode, name="test_mode"), nullable=False)
    exam_config_id: Mapped[int | None] = mapped_column(
        ForeignKey("exam_config.exam_configs.id"), nullable=True
    )
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    randomize_questions: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    randomize_options: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    exam_config: Mapped["ExamConfig | None"] = relationship()
    test_sections: Mapped[list["TestSection"]] = relationship(
        back_populates="test", order_by="TestSection.order_index"
    )


class TestSection(Base, TimestampMixin):
    """Snapshot of one section's question-count/time-limit rule for this
    specific test, copied from the exam config at creation time."""

    __tablename__ = "test_sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id"), nullable=False)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    time_limit_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    test: Mapped["Test"] = relationship(back_populates="test_sections")
    section: Mapped["Section"] = relationship()
    test_questions: Mapped[list["TestQuestion"]] = relationship(
        back_populates="test_section", order_by="TestQuestion.order_index"
    )


class TestQuestion(Base, TimestampMixin):
    """Fixed question set for a test, locked at creation time by pointing at
    a specific QuestionVersion. option_order records the per-test display
    order of option keys (used when randomize_options was selected)."""

    __tablename__ = "test_questions"
    __table_args__ = (
        UniqueConstraint("test_section_id", "order_index", name="uq_test_question_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id"), nullable=False)
    test_section_id: Mapped[int] = mapped_column(ForeignKey("test_sections.id"), nullable=False)
    question_version_id: Mapped[int] = mapped_column(
        ForeignKey("question_versions.id"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    option_order: Mapped[list] = mapped_column(JSON, nullable=False)

    test: Mapped["Test"] = relationship()
    test_section: Mapped["TestSection"] = relationship(back_populates="test_questions")
    question_version: Mapped["QuestionVersion"] = relationship()
