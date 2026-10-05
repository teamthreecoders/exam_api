import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from models.mixins import TimestampMixin


class AttemptStatus(str, enum.Enum):
    in_progress = "in_progress"
    submitted = "submitted"
    auto_submitted = "auto_submitted"


class SectionAttemptStatus(str, enum.Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    locked = "locked"
    completed = "completed"


class QuestionAttemptStatus(str, enum.Enum):
    not_visited = "not_visited"
    visited = "visited"
    answered = "answered"
    marked_for_review = "marked_for_review"
    answered_marked_for_review = "answered_marked_for_review"


class TestAttempt(Base, TimestampMixin):
    """One attempt at a Test. All timing is backend-authoritative: started_at
    and each AttemptSection's ends_at are the source of truth for expiry and
    auto-submission; the frontend timer only displays a countdown to them.

    Lives in its own `attempts` Postgres schema (see alembic/versions and
    database/sql/) separate from the rest of the app's tables."""

    __tablename__ = "test_attempts"
    __table_args__ = {"schema": "attempts"}

    id: Mapped[int] = mapped_column(primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    status: Mapped[AttemptStatus] = mapped_column(
        SAEnum(AttemptStatus, name="attempt_status"),
        nullable=False,
        default=AttemptStatus.in_progress,
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Denormalized result summary, populated by the evaluation engine on
    # submit so dashboard/history queries don't need to re-aggregate
    # question_attempts every time.
    total_questions: Mapped[int | None] = mapped_column(Integer)
    attempted: Mapped[int | None] = mapped_column(Integer)
    correct: Mapped[int | None] = mapped_column(Integer)
    incorrect: Mapped[int | None] = mapped_column(Integer)
    unattempted: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Float)
    accuracy: Mapped[float | None] = mapped_column(Float)
    percentage: Mapped[float | None] = mapped_column(Float)
    total_time_seconds: Mapped[int | None] = mapped_column(Integer)

    test: Mapped["Test"] = relationship()
    sections: Mapped[list["AttemptSection"]] = relationship(back_populates="attempt")
    question_attempts: Mapped[list["QuestionAttempt"]] = relationship(back_populates="attempt")


class AttemptSection(Base, TimestampMixin):
    __tablename__ = "attempt_sections"
    __table_args__ = (
        UniqueConstraint("attempt_id", "test_section_id", name="uq_attempt_section"),
        {"schema": "attempts"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("attempts.test_attempts.id"), nullable=False
    )
    test_section_id: Mapped[int] = mapped_column(ForeignKey("test_sections.id"), nullable=False)
    status: Mapped[SectionAttemptStatus] = mapped_column(
        SAEnum(SectionAttemptStatus, name="section_attempt_status"),
        nullable=False,
        default=SectionAttemptStatus.not_started,
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # started_at + test_section.time_limit_seconds, computed once when the
    # section starts. The exam engine locks the section the moment now() >=
    # ends_at, regardless of what the client reports.
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    attempted: Mapped[int | None] = mapped_column(Integer)
    correct: Mapped[int | None] = mapped_column(Integer)
    incorrect: Mapped[int | None] = mapped_column(Integer)
    accuracy: Mapped[float | None] = mapped_column(Float)
    avg_time_seconds: Mapped[float | None] = mapped_column(Float)

    attempt: Mapped["TestAttempt"] = relationship(back_populates="sections")
    test_section: Mapped["TestSection"] = relationship()


class QuestionAttempt(Base, TimestampMixin):
    __tablename__ = "question_attempts"
    __table_args__ = (
        UniqueConstraint("attempt_id", "test_question_id", name="uq_question_attempt"),
        {"schema": "attempts"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("attempts.test_attempts.id"), nullable=False
    )
    test_question_id: Mapped[int] = mapped_column(ForeignKey("test_questions.id"), nullable=False)

    # The canonical option_key from the QuestionVersion (not the on-screen
    # position), so grading never depends on how options were shuffled.
    selected_option_key: Mapped[str | None] = mapped_column(String(10))
    # Null until the attempt is evaluated — correct_answer must never be
    # derivable from this row while the test is still in_progress.
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[QuestionAttemptStatus] = mapped_column(
        SAEnum(QuestionAttemptStatus, name="question_attempt_status"),
        nullable=False,
        default=QuestionAttemptStatus.not_visited,
    )

    first_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Accumulated from view_events so revisits (Previous/Next) add up correctly.
    time_spent_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    attempt: Mapped["TestAttempt"] = relationship(back_populates="question_attempts")
    test_question: Mapped["TestQuestion"] = relationship()
    view_events: Mapped[list["QuestionViewEvent"]] = relationship(
        back_populates="question_attempt"
    )


class QuestionViewEvent(Base):
    """One row per continuous viewing interval of a question. time_spent_seconds
    on QuestionAttempt is the sum of (ended_at - started_at) across these,
    so navigating away and back still accumulates time correctly."""

    __tablename__ = "question_view_events"
    __table_args__ = {"schema": "attempts"}

    id: Mapped[int] = mapped_column(primary_key=True)
    question_attempt_id: Mapped[int] = mapped_column(
        ForeignKey("attempts.question_attempts.id"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    question_attempt: Mapped["QuestionAttempt"] = relationship(back_populates="view_events")
