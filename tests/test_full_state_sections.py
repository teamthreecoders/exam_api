"""Reproduces a reported bug: a multi-section test only showing one section
during the exam, with the timer not advancing to the next section and
instead immediately offering Submit. Confirms (or rules out) that the
backend's /full state -- which the frontend's client-side exam runtime
schedules itself from -- actually carries every section."""
from api.routes.attempts import _build_full_state
from exam.attempt_engine import start_attempt
from exam.test_generator import SectionSelection, create_test
from models.test import TestMode
from models.user import User
from question_bank.importer import import_question_bank


def _mk_questions(prefix: str, n: int, section: str, topic: str) -> list[dict]:
    return [
        {
            "question_id": f"{prefix}{i}",
            "section": section,
            "topic": topic,
            "difficulty": "easy",
            "question": f"{prefix}{i}?",
            "options": {"A": "1", "B": "2"},
            "correct_answer": "B",
        }
        for i in range(n)
    ]


def test_full_state_includes_every_section_of_a_multi_section_test(db_session):
    db = db_session
    user = User(user_id="U1", email="u1@example.com", first_name="Test")
    db.add(user)
    db.commit()

    payload = {
        "test_name": "Multi",
        "exam": "SSC CGL",
        "questions": (
            _mk_questions("R", 25, "Reasoning", "Series")
            + _mk_questions("Q", 25, "Quant", "Perc")
            + _mk_questions("G", 25, "GA", "Misc")
            + _mk_questions("E", 25, "English", "Grammar")
        ),
    }
    import_question_bank(db, payload=payload, source_filename="x.json")

    test = create_test(
        db,
        created_by_user_id=user.user_id,
        name="4-section test",
        exam="SSC CGL",
        mode=TestMode.custom,
        exam_config_id=None,
        sections=[
            SectionSelection(section_name="Reasoning", question_count=25, time_limit_seconds=1500),
            SectionSelection(section_name="Quant", question_count=25, time_limit_seconds=1500),
            SectionSelection(section_name="GA", question_count=25, time_limit_seconds=1500),
            SectionSelection(section_name="English", question_count=25, time_limit_seconds=1500),
        ],
        randomize_questions=False,
        randomize_options=False,
    )
    assert len(test.test_sections) == 4

    attempt = start_attempt(db, test=test, user_id=user.user_id)
    full = _build_full_state(db, attempt)

    assert len(full.sections) == 4
    assert [s.order_index for s in full.sections] == [0, 1, 2, 3]
    assert len(full.questions) == 100
    for section_id in {s.test_section_id for s in full.sections}:
        assert sum(1 for q in full.questions if q.test_section_id == section_id) == 25
