"""Covers api/routes/attempts.py's submit_attempt route directly. The
engine-level tests (test_attempt_engine.py) call apply_bulk_answers() and
submit_attempt() from exam/attempt_engine.py directly, which never exercises
the route's own ordering of tick() vs. applying the bulk payload -- a bug
where tick() cascades through already-expired sections on stale (pre-bulk-
answers) data, auto-finalizes the attempt, and then skips the bulk apply
entirely since status is no longer in_progress -- only shows up by calling
the actual route."""
import time

from api.routes.attempts import submit_attempt as route_submit_attempt
from exam.attempt_engine import start_attempt
from exam.test_generator import SectionSelection, create_test
from models.test import TestMode
from models.user import User
from question_bank.importer import import_question_bank
from schemas.attempt import BulkAnswerIn, BulkSubmitRequest

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
            "options": {"A": "7", "B": "8"},
            "correct_answer": "B",
        },
        {
            "question_id": "Q1",
            "section": "Quant",
            "topic": "Percentage",
            "difficulty": "easy",
            "question": "10% of 100?",
            "options": {"A": "5", "B": "10"},
            "correct_answer": "B",
        },
    ],
}

SECTION_TIME_LIMIT = 1  # seconds -- short so the test runs fast but expiry is real


def test_submit_route_applies_real_answers_even_after_sections_would_have_expired(db_session):
    """Simulates the actual no-mid-exam-calls flow: the client never touches
    the server between start and submit, so by the time a real multi-section
    exam is submitted, every section's wall-clock time has typically already
    passed. The route must still score the real answers the client sends --
    not silently discard them because tick() raced ahead first."""
    db = db_session
    user = User(user_id="U1", email="u1@example.com", first_name="Test")
    db.add(user)
    db.commit()

    import_question_bank(db, payload=MINI_BANK, source_filename=None)

    test = create_test(
        db,
        created_by_user_id=user.user_id,
        name="Route Test",
        exam="SSC CGL",
        mode=TestMode.custom,
        exam_config_id=None,
        sections=[
            SectionSelection(section_name="Reasoning", question_count=1, time_limit_seconds=SECTION_TIME_LIMIT),
            SectionSelection(section_name="Quant", question_count=1, time_limit_seconds=SECTION_TIME_LIMIT),
        ],
        randomize_questions=False,
        randomize_options=False,
    )

    attempt = start_attempt(db, test=test, user_id=user.user_id)
    q1 = test.test_sections[0].test_questions[0]  # Reasoning, correct answer is B
    q2 = test.test_sections[1].test_questions[0]  # Quant, correct answer is B

    # Nothing calls the server between start and submit -- let both sections'
    # wall-clock time pass before the single bulk submit, exactly like a real
    # no-mid-exam-calls attempt that simply took longer than section 1 alone.
    time.sleep(SECTION_TIME_LIMIT * 2 + 0.5)

    payload = BulkSubmitRequest(
        answers=[
            BulkAnswerIn(test_question_id=q1.id, selected_option_key="B", visited=True, time_spent_seconds=10),
            BulkAnswerIn(test_question_id=q2.id, selected_option_key="B", visited=True, time_spent_seconds=10),
        ]
    )

    result = route_submit_attempt(attempt_id=attempt.id, payload=payload, db=db, user=user)

    assert result.attempted == 2
    assert result.correct == 2
    assert result.score > 0
