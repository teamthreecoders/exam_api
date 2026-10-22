import time

import pytest

from exam.attempt_engine import (
    AttemptEngineError,
    apply_bulk_answers,
    start_attempt,
    submit_answer,
    submit_attempt,
    tick,
    toggle_mark_for_review,
    view_question,
)
from exam.test_generator import SectionSelection, TestGenerationError, create_test
from models.attempt import AttemptStatus, QuestionAttempt, QuestionAttemptStatus, SectionAttemptStatus
from models.exam_config import ExamConfig, ExamConfigSection
from models.section_topic import Section
from models.test import TestMode
from models.user import User
from question_bank.importer import import_question_bank
from schemas.attempt import BulkAnswerIn

MINI_BANK = {
    "test_name": "Mini Bank",
    "exam": "SSC CGL",
    "questions": [
        {
            "question_id": "R1",
            "section": "Reasoning",
            "topic": "Series",
            "difficulty": "easy",
            "question": "2, 4, 6, ?",
            "options": {"A": "7", "B": "8", "C": "9", "D": "10"},
            "correct_answer": "B",
        },
        {
            "question_id": "R2",
            "section": "Reasoning",
            "topic": "Series",
            "difficulty": "easy",
            "question": "1, 3, 5, ?",
            "options": {"A": "6", "B": "7", "C": "8", "D": "9"},
            "correct_answer": "B",
        },
        {
            "question_id": "Q1",
            "section": "Quant",
            "topic": "Percentage",
            "difficulty": "easy",
            "question": "10% of 100?",
            "options": {"A": "5", "B": "10", "C": "15", "D": "20"},
            "correct_answer": "B",
        },
        {
            "question_id": "Q2",
            "section": "Quant",
            "topic": "Percentage",
            "difficulty": "easy",
            "question": "50% of 200?",
            "options": {"A": "50", "B": "100", "C": "150", "D": "200"},
            "correct_answer": "B",
        },
    ],
}

SECTION_TIME_LIMIT = 1  # seconds -- short so tests run fast but expiry is real


@pytest.fixture()
def seeded(db_session):
    db = db_session
    user = User(user_id="U1", email="u1@example.com", first_name="Test")
    db.add(user)
    db.commit()

    import_question_bank(db, payload=MINI_BANK, source_filename=None)

    config = ExamConfig(exam="SSC CGL", name="Fast Config", marks_per_correct=2, negative_marks=0.5)
    db.add(config)
    db.flush()
    for name in ("Reasoning", "Quant"):
        section = db.query(Section).filter_by(name=name).one()
        db.add(
            ExamConfigSection(
                exam_config_id=config.id,
                section_id=section.id,
                question_count=2,
                time_limit_seconds=SECTION_TIME_LIMIT,
                order_index=0 if name == "Reasoning" else 1,
            )
        )
    db.commit()

    test = create_test(
        db,
        created_by_user_id=user.user_id,
        name="Engine Test",
        exam="SSC CGL",
        mode=TestMode.custom,
        exam_config_id=config.id,
        sections=[
            SectionSelection(section_name="Reasoning", question_count=2),
            SectionSelection(section_name="Quant", question_count=2),
        ],
        randomize_questions=False,
        randomize_options=False,
    )
    return db, user, test


def test_insufficient_questions_raises(seeded):
    db, user, test = seeded
    with pytest.raises(TestGenerationError, match="only 2 match"):
        create_test(
            db,
            created_by_user_id=user.user_id,
            name="Too Many",
            exam="SSC CGL",
            mode=TestMode.custom,
            exam_config_id=test.exam_config_id,
            sections=[SectionSelection(section_name="Reasoning", question_count=5)],
            randomize_questions=False,
            randomize_options=False,
        )


def test_start_attempt_initializes_first_section_only(seeded):
    db, user, test = seeded
    attempt = start_attempt(db, test=test, user_id=user.user_id)
    assert attempt.status == AttemptStatus.in_progress
    assert attempt.sections[0].status == SectionAttemptStatus.in_progress
    assert attempt.sections[1].status == SectionAttemptStatus.not_started


def test_answer_status_transitions(seeded):
    db, user, test = seeded
    attempt = start_attempt(db, test=test, user_id=user.user_id)
    q1 = test.test_sections[0].test_questions[0]

    qa = view_question(db, attempt, q1.id)
    assert qa.status == QuestionAttemptStatus.visited

    qa = submit_answer(db, attempt, q1.id, selected_option_key="B")
    assert qa.status == QuestionAttemptStatus.answered
    assert qa.selected_option_key == "B"

    qa = toggle_mark_for_review(db, attempt, q1.id, marked=True)
    assert qa.status == QuestionAttemptStatus.answered_marked_for_review

    qa = submit_answer(db, attempt, q1.id, selected_option_key=None)
    assert qa.status == QuestionAttemptStatus.marked_for_review
    assert qa.selected_option_key is None


def test_cannot_answer_question_outside_active_section(seeded):
    db, user, test = seeded
    attempt = start_attempt(db, test=test, user_id=user.user_id)
    section2_q = test.test_sections[1].test_questions[0]
    with pytest.raises(AttemptEngineError):
        submit_answer(db, attempt, section2_q.id, selected_option_key="A")


def test_section_expiry_auto_locks_and_advances(seeded):
    db, user, test = seeded
    attempt = start_attempt(db, test=test, user_id=user.user_id)
    q1, q2 = test.test_sections[0].test_questions

    submit_answer(db, attempt, q1.id, selected_option_key="B")  # correct
    submit_answer(db, attempt, q2.id, selected_option_key="A")  # incorrect

    time.sleep(SECTION_TIME_LIMIT + 0.5)
    attempt = tick(db, attempt)

    assert attempt.sections[0].status == SectionAttemptStatus.completed
    assert attempt.sections[0].attempted == 2
    assert attempt.sections[0].correct == 1
    assert attempt.sections[0].incorrect == 1
    assert attempt.sections[1].status == SectionAttemptStatus.in_progress
    assert attempt.status == AttemptStatus.in_progress


def test_full_test_auto_submits_after_last_section_expires(seeded):
    db, user, test = seeded
    attempt = start_attempt(db, test=test, user_id=user.user_id)

    time.sleep(SECTION_TIME_LIMIT + 0.5)
    attempt = tick(db, attempt)  # locks section 1, starts section 2
    time.sleep(SECTION_TIME_LIMIT + 0.5)
    attempt = tick(db, attempt)  # locks section 2, auto-submits

    assert attempt.status == AttemptStatus.auto_submitted
    assert attempt.total_questions == 4
    assert attempt.unattempted == 4
    assert attempt.score == 0.0


def test_manual_submit_mid_test(seeded):
    db, user, test = seeded
    attempt = start_attempt(db, test=test, user_id=user.user_id)
    q1 = test.test_sections[0].test_questions[0]
    submit_answer(db, attempt, q1.id, selected_option_key="B")

    attempt = submit_attempt(db, attempt)
    assert attempt.status == AttemptStatus.submitted
    assert attempt.sections[1].status == SectionAttemptStatus.not_started
    assert attempt.attempted == 1
    assert attempt.correct == 1
    assert attempt.score == 2.0


def test_double_submit_is_idempotent(seeded):
    db, user, test = seeded
    attempt = start_attempt(db, test=test, user_id=user.user_id)
    first = submit_attempt(db, attempt)
    second = submit_attempt(db, attempt)
    assert first.status == second.status == AttemptStatus.submitted
    assert first.score == second.score


def test_bulk_answers_applied_then_submitted_with_no_prior_calls(seeded):
    """The no-mid-exam-calls path: nothing (view/answer/mark) is called while
    the exam is in progress -- the client's whole local answer set arrives in
    one batch right before submit."""
    db, user, test = seeded
    attempt = start_attempt(db, test=test, user_id=user.user_id)
    q1, q2 = test.test_sections[0].test_questions

    apply_bulk_answers(
        db,
        attempt,
        [
            BulkAnswerIn(test_question_id=q1.id, selected_option_key="B", visited=True, time_spent_seconds=12),
            BulkAnswerIn(
                test_question_id=q2.id,
                selected_option_key=None,
                visited=True,
                marked_for_review=True,
                time_spent_seconds=5,
            ),
        ],
    )

    attempt = submit_attempt(db, attempt)
    assert attempt.status == AttemptStatus.submitted
    assert attempt.attempted == 1
    assert attempt.correct == 1
    assert attempt.score == 2.0

    qa2 = db.query(QuestionAttempt).filter_by(attempt_id=attempt.id, test_question_id=q2.id).one()
    assert qa2.status == QuestionAttemptStatus.marked_for_review
    assert qa2.time_spent_seconds == 5
