"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    difficulty_enum = sa.Enum("easy", "medium", "hard", name="difficulty")
    test_mode_enum = sa.Enum(
        "full_mock", "section_test", "topic_test", "custom", name="test_mode"
    )
    attempt_status_enum = sa.Enum(
        "in_progress", "submitted", "auto_submitted", name="attempt_status"
    )
    section_attempt_status_enum = sa.Enum(
        "not_started", "in_progress", "locked", "completed", name="section_attempt_status"
    )
    question_attempt_status_enum = sa.Enum(
        "not_visited",
        "visited",
        "answered",
        "marked_for_review",
        "answered_marked_for_review",
        name="question_attempt_status",
    )

    bind = op.get_bind()
    difficulty_enum.create(bind, checkfirst=True)
    test_mode_enum.create(bind, checkfirst=True)
    attempt_status_enum.create(bind, checkfirst=True)
    section_attempt_status_enum.create(bind, checkfirst=True)
    question_attempt_status_enum.create(bind, checkfirst=True)

    # exam_configs/exam_config_sections live in their own schema, as do the
    # test_attempts/attempt_sections/question_attempts/question_view_events
    # tables -- everything else (users, question bank, tests, test_sections,
    # test_questions) stays in the default `public` schema. See
    # database/sql/ for a plain-SQL mirror of this same layout.
    op.execute("CREATE SCHEMA IF NOT EXISTS exam_config")
    op.execute("CREATE SCHEMA IF NOT EXISTS attempts")

    op.create_table(
        "users",
        sa.Column("user_id", sa.String(50), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("first_name", sa.String(255), nullable=False),
        sa.Column("last_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "sections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "topics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("section_id", sa.Integer, sa.ForeignKey("sections.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("section_id", "name", name="uq_topic_section_name"),
    )

    op.create_table(
        "question_banks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("exam", sa.String(100), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "questions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("question_bank_id", sa.Integer, sa.ForeignKey("question_banks.id"), nullable=False),
        sa.Column("external_question_id", sa.String(100), nullable=False),
        sa.Column("current_version_id", sa.Integer, nullable=True),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "question_bank_id", "external_question_id", name="uq_question_bank_external_id"
        ),
    )

    op.create_table(
        "question_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("question_id", sa.Integer, sa.ForeignKey("questions.id"), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("section_id", sa.Integer, sa.ForeignKey("sections.id"), nullable=False),
        sa.Column("topic_id", sa.Integer, sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("subtopic", sa.String(255), nullable=True),
        sa.Column("difficulty", difficulty_enum, nullable=False),
        sa.Column("question_text", sa.Text, nullable=False),
        sa.Column("correct_option_key", sa.String(10), nullable=False),
        sa.Column("explanation", sa.Text, nullable=True),
        sa.Column("source", sa.String(255), nullable=True),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column("shift", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "question_options",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "question_version_id", sa.Integer, sa.ForeignKey("question_versions.id"), nullable=False
        ),
        sa.Column("option_key", sa.String(10), nullable=False),
        sa.Column("option_text", sa.Text, nullable=False),
        sa.Column("order_index", sa.Integer, nullable=False),
        sa.UniqueConstraint("question_version_id", "option_key", name="uq_option_version_key"),
    )

    op.create_table(
        "exam_configs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("exam", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("marks_per_correct", sa.Float, nullable=False),
        sa.Column("negative_marks", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="exam_config",
    )

    op.create_table(
        "exam_config_sections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "exam_config_id",
            sa.Integer,
            sa.ForeignKey("exam_config.exam_configs.id"),
            nullable=False,
        ),
        sa.Column("section_id", sa.Integer, sa.ForeignKey("sections.id"), nullable=False),
        sa.Column("question_count", sa.Integer, nullable=False),
        sa.Column("time_limit_seconds", sa.Integer, nullable=False),
        sa.Column("order_index", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("exam_config_id", "section_id", name="uq_exam_config_section"),
        schema="exam_config",
    )

    op.create_table(
        "tests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("exam", sa.String(100), nullable=False),
        sa.Column("mode", test_mode_enum, nullable=False),
        sa.Column(
            "exam_config_id", sa.Integer, sa.ForeignKey("exam_config.exam_configs.id"), nullable=True
        ),
        sa.Column("created_by_user_id", sa.String(50), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("randomize_questions", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("randomize_options", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "test_sections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("test_id", sa.Integer, sa.ForeignKey("tests.id"), nullable=False),
        sa.Column("section_id", sa.Integer, sa.ForeignKey("sections.id"), nullable=False),
        sa.Column("question_count", sa.Integer, nullable=False),
        sa.Column("time_limit_seconds", sa.Integer, nullable=False),
        sa.Column("order_index", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "test_questions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("test_id", sa.Integer, sa.ForeignKey("tests.id"), nullable=False),
        sa.Column("test_section_id", sa.Integer, sa.ForeignKey("test_sections.id"), nullable=False),
        sa.Column(
            "question_version_id", sa.Integer, sa.ForeignKey("question_versions.id"), nullable=False
        ),
        sa.Column("order_index", sa.Integer, nullable=False),
        sa.Column("option_order", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("test_section_id", "order_index", name="uq_test_question_order"),
    )

    op.create_table(
        "test_attempts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("test_id", sa.Integer, sa.ForeignKey("tests.id"), nullable=False),
        sa.Column("user_id", sa.String(50), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column(
            "status", attempt_status_enum, nullable=False, server_default="in_progress"
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_questions", sa.Integer, nullable=True),
        sa.Column("attempted", sa.Integer, nullable=True),
        sa.Column("correct", sa.Integer, nullable=True),
        sa.Column("incorrect", sa.Integer, nullable=True),
        sa.Column("unattempted", sa.Integer, nullable=True),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("accuracy", sa.Float, nullable=True),
        sa.Column("percentage", sa.Float, nullable=True),
        sa.Column("total_time_seconds", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="attempts",
    )

    op.create_table(
        "attempt_sections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "attempt_id", sa.Integer, sa.ForeignKey("attempts.test_attempts.id"), nullable=False
        ),
        sa.Column("test_section_id", sa.Integer, sa.ForeignKey("test_sections.id"), nullable=False),
        sa.Column(
            "status",
            section_attempt_status_enum,
            nullable=False,
            server_default="not_started",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempted", sa.Integer, nullable=True),
        sa.Column("correct", sa.Integer, nullable=True),
        sa.Column("incorrect", sa.Integer, nullable=True),
        sa.Column("accuracy", sa.Float, nullable=True),
        sa.Column("avg_time_seconds", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("attempt_id", "test_section_id", name="uq_attempt_section"),
        schema="attempts",
    )

    op.create_table(
        "question_attempts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "attempt_id", sa.Integer, sa.ForeignKey("attempts.test_attempts.id"), nullable=False
        ),
        sa.Column(
            "test_question_id", sa.Integer, sa.ForeignKey("test_questions.id"), nullable=False
        ),
        sa.Column("selected_option_key", sa.String(10), nullable=True),
        sa.Column("is_correct", sa.Boolean, nullable=True),
        sa.Column(
            "status",
            question_attempt_status_enum,
            nullable=False,
            server_default="not_visited",
        ),
        sa.Column("first_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_spent_seconds", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("attempt_id", "test_question_id", name="uq_question_attempt"),
        schema="attempts",
    )

    op.create_table(
        "question_view_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "question_attempt_id",
            sa.Integer,
            sa.ForeignKey("attempts.question_attempts.id"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        schema="attempts",
    )

    op.create_index("ix_topics_section_id", "topics", ["section_id"])
    op.create_index("ix_questions_question_bank_id", "questions", ["question_bank_id"])
    op.create_index("ix_question_versions_question_id", "question_versions", ["question_id"])
    op.create_index("ix_question_versions_section_id", "question_versions", ["section_id"])
    op.create_index("ix_question_versions_topic_id", "question_versions", ["topic_id"])
    op.create_index("ix_question_options_question_version_id", "question_options", ["question_version_id"])
    op.create_index("ix_tests_created_by_user_id", "tests", ["created_by_user_id"])
    op.create_index("ix_test_sections_test_id", "test_sections", ["test_id"])
    op.create_index("ix_test_questions_test_id", "test_questions", ["test_id"])
    op.create_index("ix_test_questions_test_section_id", "test_questions", ["test_section_id"])
    op.create_index(
        "ix_test_attempts_test_id", "test_attempts", ["test_id"], schema="attempts"
    )
    op.create_index(
        "ix_test_attempts_user_id", "test_attempts", ["user_id"], schema="attempts"
    )
    op.create_index(
        "ix_attempt_sections_attempt_id", "attempt_sections", ["attempt_id"], schema="attempts"
    )
    op.create_index(
        "ix_question_attempts_attempt_id", "question_attempts", ["attempt_id"], schema="attempts"
    )
    op.create_index(
        "ix_question_view_events_question_attempt_id",
        "question_view_events",
        ["question_attempt_id"],
        schema="attempts",
    )


def downgrade() -> None:
    op.drop_table("question_view_events", schema="attempts")
    op.drop_table("question_attempts", schema="attempts")
    op.drop_table("attempt_sections", schema="attempts")
    op.drop_table("test_attempts", schema="attempts")
    op.drop_table("test_questions")
    op.drop_table("test_sections")
    op.drop_table("tests")
    op.drop_table("exam_config_sections", schema="exam_config")
    op.drop_table("exam_configs", schema="exam_config")
    op.drop_table("question_options")
    op.drop_table("question_versions")
    op.drop_table("questions")
    op.drop_table("question_banks")
    op.drop_table("topics")
    op.drop_table("sections")
    op.drop_table("users")

    op.execute("DROP SCHEMA IF EXISTS attempts CASCADE")
    op.execute("DROP SCHEMA IF EXISTS exam_config CASCADE")

    bind = op.get_bind()
    sa.Enum(name="question_attempt_status").drop(bind, checkfirst=True)
    sa.Enum(name="section_attempt_status").drop(bind, checkfirst=True)
    sa.Enum(name="attempt_status").drop(bind, checkfirst=True)
    sa.Enum(name="test_mode").drop(bind, checkfirst=True)
    sa.Enum(name="difficulty").drop(bind, checkfirst=True)
