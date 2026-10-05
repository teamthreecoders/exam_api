"""Generates a Test instance from the question bank (spec section 5): the
question set and per-section timing are resolved and locked in at creation
time, so later edits to the exam config or question bank never retroactively
change a test that already exists.
"""
import random
from dataclasses import dataclass

from sqlalchemy.orm import Session

from models.exam_config import ExamConfig, ExamConfigSection
from models.question_bank import Question, QuestionBank, QuestionVersion
from models.section_topic import Section, Topic
from models.test import Test, TestMode, TestQuestion, TestSection


class TestGenerationError(Exception):
    """Raised for any condition that should surface as a clear 422 to the
    caller -- e.g. not enough matching questions. We deliberately fail hard
    here rather than silently generating a shorter test."""


@dataclass
class SectionSelection:
    section_name: str
    question_count: int
    time_limit_seconds: int | None = None
    topics: list[str] | None = None
    difficulties: list[str] | None = None
    year: int | None = None
    source: str | None = None


def _resolve_time_limit(
    db: Session, exam_config_id: int | None, section: Section, explicit: int | None
) -> int:
    if explicit:
        return explicit
    if exam_config_id:
        ecs = (
            db.query(ExamConfigSection)
            .filter_by(exam_config_id=exam_config_id, section_id=section.id)
            .one_or_none()
        )
        if ecs:
            return ecs.time_limit_seconds
    raise TestGenerationError(
        f"No time limit for section '{section.name}': the selected exam config has no section "
        "with this exact name (section names must match exactly). Either fix the exam config, "
        "or pass an explicit time_limit_seconds for this section to override it."
    )


def _select_question_versions(
    db: Session, section: Section, sel: SectionSelection, randomize: bool, question_bank_id: int | None
) -> list[QuestionVersion]:
    query = (
        db.query(QuestionVersion)
        .join(Question, Question.current_version_id == QuestionVersion.id)
        .filter(Question.is_deleted.is_(False))
        .filter(QuestionVersion.section_id == section.id)
    )
    if question_bank_id is not None:
        query = query.filter(Question.question_bank_id == question_bank_id)
    if sel.topics:
        query = query.join(Topic, Topic.id == QuestionVersion.topic_id).filter(
            Topic.name.in_(sel.topics)
        )
    if sel.difficulties:
        query = query.filter(QuestionVersion.difficulty.in_(sel.difficulties))
    if sel.year:
        query = query.filter(QuestionVersion.year == sel.year)
    if sel.source:
        query = query.filter(QuestionVersion.source == sel.source)

    candidates = query.order_by(QuestionVersion.id).all()
    if len(candidates) < sel.question_count:
        scope = " in the selected question bank" if question_bank_id is not None else ""
        raise TestGenerationError(
            f"Section '{section.name}' needs {sel.question_count} questions but only "
            f"{len(candidates)} match the selected filters{scope}"
        )
    if randomize:
        return random.sample(candidates, sel.question_count)
    return candidates[: sel.question_count]


def create_test(
    db: Session,
    *,
    created_by_user_id: str,
    name: str,
    exam: str,
    mode: TestMode,
    exam_config_id: int | None,
    sections: list[SectionSelection],
    randomize_questions: bool,
    randomize_options: bool,
    question_bank_id: int | None = None,
) -> Test:
    if not sections:
        raise TestGenerationError("At least one section must be selected")

    if exam_config_id is not None and db.get(ExamConfig, exam_config_id) is None:
        raise TestGenerationError(f"Exam config {exam_config_id} does not exist")

    if question_bank_id is not None and db.get(QuestionBank, question_bank_id) is None:
        raise TestGenerationError(f"Question bank {question_bank_id} does not exist")

    test = Test(
        name=name,
        exam=exam,
        mode=mode,
        exam_config_id=exam_config_id,
        created_by_user_id=created_by_user_id,
        randomize_questions=randomize_questions,
        randomize_options=randomize_options,
    )
    db.add(test)
    db.flush()

    for order_index, sel in enumerate(sections):
        section = db.query(Section).filter_by(name=sel.section_name).one_or_none()
        if section is None:
            raise TestGenerationError(f"Unknown section '{sel.section_name}'")

        time_limit_seconds = _resolve_time_limit(db, exam_config_id, section, sel.time_limit_seconds)
        versions = _select_question_versions(db, section, sel, randomize_questions, question_bank_id)

        test_section = TestSection(
            test_id=test.id,
            section_id=section.id,
            question_count=sel.question_count,
            time_limit_seconds=time_limit_seconds,
            order_index=order_index,
        )
        db.add(test_section)
        db.flush()

        for q_order, version in enumerate(versions):
            option_keys = [o.option_key for o in sorted(version.options, key=lambda o: o.order_index)]
            if randomize_options:
                random.shuffle(option_keys)
            db.add(
                TestQuestion(
                    test_id=test.id,
                    test_section_id=test_section.id,
                    question_version_id=version.id,
                    order_index=q_order,
                    option_order=option_keys,
                )
            )

    db.commit()
    db.refresh(test)
    return test
