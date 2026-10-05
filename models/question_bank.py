import enum

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from models.mixins import TimestampMixin


class Difficulty(str, enum.Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class QuestionBank(Base, TimestampMixin):
    """One imported JSON file. Grouping questions by the import they came
    from lets the question bank keep growing over time without colliding
    external_question_id values across unrelated uploads."""

    __tablename__ = "question_banks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    exam: Mapped[str] = mapped_column(String(100), nullable=False)
    source_filename: Mapped[str | None] = mapped_column(String(255))

    questions: Mapped[list["Question"]] = relationship(back_populates="question_bank")


class Question(Base, TimestampMixin):
    """Identity row for a question. Content that historical attempts depend on
    (text, options, correct answer, metadata) is never stored here directly —
    it lives in immutable QuestionVersion snapshots so that editing a question
    later cannot alter already-taken tests (see spec section 23)."""

    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint(
            "question_bank_id", "external_question_id", name="uq_question_bank_external_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    question_bank_id: Mapped[int] = mapped_column(
        ForeignKey("question_banks.id"), nullable=False
    )
    external_question_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # Points at the QuestionVersion currently shown in the Question Bank UI /
    # used for new tests. Intentionally not a real FK constraint: it would
    # create a circular dependency with question_versions.question_id, and
    # this pointer is a "latest" convenience, not something anything else
    # needs referential integrity against.
    current_version_id: Mapped[int | None] = mapped_column(Integer)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    question_bank: Mapped["QuestionBank"] = relationship(back_populates="questions")
    versions: Mapped[list["QuestionVersion"]] = relationship(back_populates="question")


class QuestionVersion(Base, TimestampMixin):
    """Immutable snapshot of a question's full content at a point in time.
    TestQuestion rows reference a specific version_id, so a test's content
    is frozen at creation time regardless of later edits to the question."""

    __tablename__ = "question_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=False)
    subtopic: Mapped[str | None] = mapped_column(String(255))
    difficulty: Mapped[Difficulty] = mapped_column(
        SAEnum(Difficulty, name="difficulty"), nullable=False
    )

    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    # The option_key (e.g. "B") as originally authored. Display order for a
    # given test is a separate concern — see TestQuestion.option_order.
    correct_option_key: Mapped[str] = mapped_column(String(10), nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text)

    source: Mapped[str | None] = mapped_column(String(255))
    year: Mapped[int | None] = mapped_column(Integer)
    shift: Mapped[str | None] = mapped_column(String(50))

    question: Mapped["Question"] = relationship(back_populates="versions")
    options: Mapped[list["QuestionOption"]] = relationship(
        back_populates="question_version", order_by="QuestionOption.order_index"
    )
    section: Mapped["Section"] = relationship()
    topic: Mapped["Topic"] = relationship()


class QuestionOption(Base):
    __tablename__ = "question_options"
    __table_args__ = (
        UniqueConstraint("question_version_id", "option_key", name="uq_option_version_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    question_version_id: Mapped[int] = mapped_column(
        ForeignKey("question_versions.id"), nullable=False
    )
    option_key: Mapped[str] = mapped_column(String(10), nullable=False)
    option_text: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    question_version: Mapped["QuestionVersion"] = relationship(back_populates="options")
