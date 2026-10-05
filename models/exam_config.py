from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from models.mixins import TimestampMixin


class ExamConfig(Base, TimestampMixin):
    """Config-driven exam definition: section layout, per-section timing, and
    the marking scheme. Nothing about timing or scoring is hardcoded in the
    exam/evaluation engines — they read it from here (see spec section 4, 9).

    Lives in its own `exam_config` Postgres schema (see alembic/versions and
    database/sql/) separate from the rest of the app's tables."""

    __tablename__ = "exam_configs"
    __table_args__ = {"schema": "exam_config"}

    id: Mapped[int] = mapped_column(primary_key=True)
    exam: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    marks_per_correct: Mapped[float] = mapped_column(Float, nullable=False)
    # Stored as a positive magnitude subtracted per wrong answer (e.g. 0.5),
    # not a negative number. score = correct*marks_per_correct - incorrect*negative_marks.
    negative_marks: Mapped[float] = mapped_column(Float, nullable=False)

    sections: Mapped[list["ExamConfigSection"]] = relationship(
        back_populates="exam_config", order_by="ExamConfigSection.order_index"
    )


class ExamConfigSection(Base, TimestampMixin):
    __tablename__ = "exam_config_sections"
    __table_args__ = (
        UniqueConstraint("exam_config_id", "section_id", name="uq_exam_config_section"),
        {"schema": "exam_config"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_config_id: Mapped[int] = mapped_column(
        ForeignKey("exam_config.exam_configs.id"), nullable=False
    )
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    time_limit_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    exam_config: Mapped["ExamConfig"] = relationship(back_populates="sections")
    section: Mapped["Section"] = relationship()
