"""Covers the question_bank_id scoping feature: a test can be generated from
only one imported JSON file instead of the whole shared bank, even when two
uploads share overlapping section/topic names."""
import pytest

from exam.test_generator import SectionSelection, TestGenerationError, create_test
from models.test import TestMode
from models.user import User
from question_bank.importer import import_question_bank


def _bank_payload(name: str, question_ids: list[str]) -> dict:
    return {
        "test_name": name,
        "exam": "SSC CGL",
        "questions": [
            {
                "question_id": qid,
                "section": "Reasoning",
                "topic": "Series",
                "difficulty": "easy",
                "question": f"{qid}: 2, 4, 6, ?",
                "options": {"A": "7", "B": "8", "C": "9", "D": "10"},
                "correct_answer": "B",
            }
            for qid in question_ids
        ],
    }


def test_create_test_scoped_to_one_question_bank(db_session):
    db = db_session
    user = User(user_id="U1", email="u1@example.com", first_name="Test")
    db.add(user)
    db.commit()

    bank_a = import_question_bank(db, payload=_bank_payload("Set A", ["A1", "A2", "A3"]), source_filename="a.json")
    import_question_bank(db, payload=_bank_payload("Set B", ["B1", "B2", "B3"]), source_filename="b.json")

    test = create_test(
        db,
        created_by_user_id=user.user_id,
        name="Scoped Test",
        exam="SSC CGL",
        mode=TestMode.custom,
        exam_config_id=None,
        sections=[SectionSelection(section_name="Reasoning", question_count=3, time_limit_seconds=60)],
        randomize_questions=False,
        randomize_options=False,
        question_bank_id=bank_a.id,
    )

    external_ids = {
        tq.question_version.question.external_question_id for tq in test.test_sections[0].test_questions
    }
    assert external_ids == {"A1", "A2", "A3"}


def test_create_test_scoped_to_bank_fails_when_not_enough_questions_there(db_session):
    db = db_session
    user = User(user_id="U1", email="u1@example.com", first_name="Test")
    db.add(user)
    db.commit()

    bank_a = import_question_bank(db, payload=_bank_payload("Set A", ["A1"]), source_filename="a.json")
    import_question_bank(db, payload=_bank_payload("Set B", ["B1", "B2", "B3"]), source_filename="b.json")

    with pytest.raises(TestGenerationError, match="only 1 match"):
        create_test(
            db,
            created_by_user_id=user.user_id,
            name="Scoped Test",
            exam="SSC CGL",
            mode=TestMode.custom,
            exam_config_id=None,
            sections=[SectionSelection(section_name="Reasoning", question_count=3, time_limit_seconds=60)],
            randomize_questions=False,
            randomize_options=False,
            question_bank_id=bank_a.id,
        )
