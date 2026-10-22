import os
import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# Force the test DB URL unconditionally (not setdefault): this process's
# environment may already have a real DATABASE_URL exported (e.g. a shell
# auto-loading backend/.env), and tests must never touch that real database
# regardless of what's ambient in the environment.
os.environ["DATABASE_URL"] = f"sqlite:///{BACKEND_DIR / 'tests' / '.test.db'}"

from database.base import Base  # noqa: E402
from database.session import engine as _raw_engine  # noqa: E402

import models  # noqa: E402,F401  (registers every model on Base.metadata)

# The real app puts exam_config/attempts tables in dedicated Postgres schemas
# (see alembic/versions/0001_initial_schema.py and database/sql/). SQLite has
# no equivalent, so tests translate both schema names back to the default
# schema -- this changes nothing about the ORM/business-logic behavior under
# test, only where the tables physically live.
SCHEMA_TRANSLATE_MAP = {"exam_config": None, "attempts": None}
engine = _raw_engine.execution_options(schema_translate_map=SCHEMA_TRANSLATE_MAP)
TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture()
def db_session():
    """Fresh schema per test. SQLite stands in for Postgres here -- fast and
    dependency-free, but Postgres-specific behavior (native enums, real
    multi-schema, etc.) is not exercised by these tests; see README's
    testing caveat."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
