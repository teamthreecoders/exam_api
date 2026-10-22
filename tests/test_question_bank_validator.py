from question_bank.validator import validate_question_bank


def _question(**overrides):
    base = {
        "question_id": "Q1",
        "section": "Quantitative Aptitude",
        "topic": "Percentage",
        "difficulty": "easy",
        "question": "What is 10% of 100?",
        "options": {"A": "5", "B": "10", "C": "15", "D": "20"},
        "correct_answer": "B",
    }
    base.update(overrides)
    return base


def test_valid_bank_passes():
    result = validate_question_bank({"questions": [_question()]})
    assert result.is_valid


def test_missing_question_id():
    q = _question()
    del q["question_id"]
    result = validate_question_bank({"questions": [q]})
    assert not result.is_valid
    assert any(e.field == "question_id" for e in result.errors)


def test_missing_question_text():
    q = _question()
    del q["question"]
    result = validate_question_bank({"questions": [q]})
    assert any(e.field == "question" for e in result.errors)


def test_missing_section():
    q = _question()
    del q["section"]
    result = validate_question_bank({"questions": [q]})
    assert any(e.field == "section" for e in result.errors)


def test_missing_options():
    q = _question()
    del q["options"]
    result = validate_question_bank({"questions": [q]})
    assert any(e.field == "options" for e in result.errors)


def test_correct_answer_not_in_options():
    q = _question(correct_answer="Z")
    result = validate_question_bank({"questions": [q]})
    assert any(e.field == "correct_answer" for e in result.errors)


def test_duplicate_question_ids():
    result = validate_question_bank(
        {"questions": [_question(question_id="Q1"), _question(question_id="Q1")]}
    )
    assert not result.is_valid
    assert any("duplicate" in e.message for e in result.errors)


def test_invalid_difficulty():
    q = _question(difficulty="impossible")
    result = validate_question_bank({"questions": [q]})
    assert any(e.field == "difficulty" for e in result.errors)


def test_empty_questions_list():
    result = validate_question_bank({"questions": []})
    assert not result.is_valid
