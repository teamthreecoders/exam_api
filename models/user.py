from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from models.mixins import TimestampMixin


class User(Base, TimestampMixin):
    """Local cache of a user profile from the external auth service.

    This platform never stores credentials. A row here is upserted the first
    time a validated session is seen for a given user_id, purely so other
    tables (tests, attempts) have a real local foreign key to point at.
    user_id is the auth service's own identifier (e.g. "AY12345678"), not a
    locally-generated id.
    """

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
