"""Covers api/routes/question_bank.py's list_banks and bank_section_breakdown
queries -- the two places in this file with non-trivial joins/aggregates, so
worth a direct check rather than trusting they compile."""
from fastapi import HTTPException
import pytest

from api.routes.question_bank import bank_section_breakdown, get_question_detail, list_banks
from models.question_bank import Question
from models.user import User
from question_bank.importer import import_question_bank

MINI_BANK = {
    "test_name": "Demo",
    "exam": "SSC CGL",
    "questions": [
        {
            "question_id": "Q1",
            "section": "Reasoning",
            "topic": "Series",
            "difficulty": "easy",
            "question": "2, 4, 6, ?",
            "options": {"A": "7", "B": "8"},
            "correct_answer": "B",
        },
        {
            "question_id": "Q2",
            "section": "Reasoning",
            "topic": "Series",
            "difficulty": "easy",
            "question": "1, 3, 5, ?",
            "options": {"A": "6", "B": "7"},
            "correct_answer": "B",
        },
    ],
}

TWO_SECTION_BANK = {
    "test_name": "PYQ Paper",
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
        {
            "question_id": "Q2",
            "section": "Quant",
            "topic": "Percentage",
            "difficulty": "easy",
            "question": "50% of 200?",
            "options": {"A": "50", "B": "100"},
            "correct_answer": "B",
        },
    ],
}


def test_list_banks_counts_questions_per_bank(db_session):
    db = db_session
    user = User(user_id="U1", email="u1@example.com", first_name="Test")
    db.add(user)
    db.commit()

    bank_a = import_question_bank(db, payload=MINI_BANK, source_filename="a.json")
    bank_b = import_question_bank(
        db,
        payload={**MINI_BANK, "questions": MINI_BANK["questions"][:1]},
        source_filename="b.json",
    )

    result = list_banks(db=db, _=user)
    counts = {b.id: b.question_count for b in result}

    assert counts[bank_a.id] == 2
    assert counts[bank_b.id] == 1
    # Most recent import first.
    assert result[0].id == bank_b.id


def test_bank_section_breakdown_scoped_to_one_upload(db_session):
    db = db_session
    user = User(user_id="U1", email="u1@example.com", first_name="Test")
    db.add(user)
    db.commit()

    paper = import_question_bank(db, payload=TWO_SECTION_BANK, source_filename="paper.json")
    # A second, unrelated upload that happens to share the "Reasoning" section
    # name -- the breakdown for `paper` must not pick up its questions too.
    import_question_bank(db, payload=MINI_BANK, source_filename="other.json")

    result = bank_section_breakdown(bank_id=paper.id, db=db, _=user)
    counts = {row.section: row.question_count for row in result}

    assert counts == {"Reasoning": 1, "Quant": 2}


def test_bank_section_breakdown_404_for_unknown_bank(db_session):
    db = db_session
    user = User(user_id="U1", email="u1@example.com", first_name="Test")
    db.add(user)
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        bank_section_breakdown(bank_id=999, db=db, _=user)
    assert exc_info.value.status_code == 404


def test_get_question_detail_includes_options_and_correct_answer(db_session):
    db = db_session
    user = User(user_id="U1", email="u1@example.com", first_name="Test")
    db.add(user)
    db.commit()

    import_question_bank(db, payload=MINI_BANK, source_filename="a.json")
    question = db.query(Question).filter_by(external_question_id="Q1").one()

    detail = get_question_detail(question_id=question.id, db=db, _=user)

    assert detail.external_question_id == "Q1"
    assert detail.correct_option_key == "B"
    assert {o.key: o.text for o in detail.options} == {"A": "7", "B": "8"}


def test_get_question_detail_404_for_unknown_question(db_session):
    db = db_session
    user = User(user_id="U1", email="u1@example.com", first_name="Test")
    db.add(user)
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        get_question_detail(question_id=999, db=db, _=user)
    assert exc_info.value.status_code == 404
