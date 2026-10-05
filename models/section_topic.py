from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from models.mixins import TimestampMixin


class Section(Base, TimestampMixin):
    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    topics: Mapped[list["Topic"]] = relationship(back_populates="section")


class Topic(Base, TimestampMixin):
    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint("section_id", "name", name="uq_topic_section_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    section: Mapped["Section"] = relationship(back_populates="topics")
