"""AI explanation service + route. The LLM is stubbed -- nothing here
touches the network."""
import pytest
from fastapi import HTTPException

from api.routes.attempts import get_ai_explanation, get_result
from core.config import settings
from exam.attempt_engine import start_attempt
from exam.attempt_engine import submit_attempt as engine_submit
from exam.test_generator import SectionSelection, create_test
from models.question_bank import QuestionVersion
from models.test import TestMode
from models.user import User
from question_bank.importer import import_question_bank
from services import explanation_service
from services.explanation_service import ExplanationError, _extract_json, _Explanation, _format

BANK = {
    "test_name": "B",
    "exam": "SSC CGL",
    "questions": [
        {
            "question_id": "Q1",
            "section": "Quant",
            "topic": "Percentage",
            "difficulty": "easy",
            "question": "10% of 100?",
            "options": {"A": "5", "B": "10"},
            "correct_answer": "B",
        }
    ],
}

GOOD_JSON = '{"summary": "10/100 x 100 = 10.", "steps": ["Multiply"], "why_others_wrong": {"A": "Too low", "B": "dup"}}'


class _FakeResp:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]


def _stub_llm(monkeypatch, *contents):
    calls = []
    outputs = list(contents)

    class _Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return _FakeResp(outputs.pop(0))

    client = type("Cl", (), {"chat": type("Ch", (), {"completions": _Completions()})()})()
    monkeypatch.setattr(explanation_service, "_get_client", lambda: client)
    monkeypatch.setattr(settings, "LLM_BASE_URL", "http://x/v1")
    monkeypatch.setattr(settings, "LLM_MODEL", "m")
    return calls


@pytest.fixture()
def finished_attempt(db_session):
    db = db_session
    user = User(user_id="U1", email="u1@example.com", first_name="T")
    db.add(user)
    db.commit()
    import_question_bank(db, payload=BANK, source_filename=None)
    test = create_test(
        db, created_by_user_id="U1", name="T", exam="SSC CGL", mode=TestMode.custom,
        exam_config_id=None,
        sections=[SectionSelection(section_name="Quant", question_count=1, time_limit_seconds=600)],
        randomize_questions=False, randomize_options=False,
    )
    attempt = engine_submit(db, start_attempt(db, test=test, user_id="U1"))
    return db, user, attempt, test.test_sections[0].test_questions[0]


def test_extract_json_handles_fences_and_think_blocks():
    raw = '<think>hmm {not json}</think>\n```json\n{"summary": "ok"}\n```'
    assert _extract_json(raw) == {"summary": "ok"}


def test_format_drops_correct_option_from_wrong_list():
    exp = _Explanation.model_validate_json(GOOD_JSON)
    text = _format(exp, "B")
    assert "A: Too low" in text and "B: dup" not in text


def test_route_generates_once_then_serves_cache(finished_attempt, monkeypatch):
    db, user, attempt, tq = finished_attempt
    calls = _stub_llm(monkeypatch, GOOD_JSON)

    first = get_ai_explanation(attempt.id, tq.id, db=db, user=user)
    second = get_ai_explanation(attempt.id, tq.id, db=db, user=user)

    assert first.ai_explanation == second.ai_explanation
    assert len(calls) == 1
    assert "Correct answer: B" in calls[0]["messages"][1]["content"]
    result = get_result(attempt.id, db=db, user=user)
    assert result.questions[0].ai_explanation == first.ai_explanation


def test_retries_once_on_malformed_json(finished_attempt, monkeypatch):
    db, user, attempt, tq = finished_attempt
    calls = _stub_llm(monkeypatch, "sorry, no json", GOOD_JSON)
    get_ai_explanation(attempt.id, tq.id, db=db, user=user)
    assert len(calls) == 2


def test_route_502_when_llm_keeps_failing(finished_attempt, monkeypatch):
    db, user, attempt, tq = finished_attempt
    _stub_llm(monkeypatch, "nope", "still nope")
    with pytest.raises(HTTPException) as exc:
        get_ai_explanation(attempt.id, tq.id, db=db, user=user)
    assert exc.value.status_code == 502
    assert db.query(QuestionVersion).one().ai_explanation is None


def test_route_503_when_not_configured(finished_attempt, monkeypatch):
    db, user, attempt, tq = finished_attempt
    monkeypatch.setattr(settings, "LLM_BASE_URL", "")
    with pytest.raises(HTTPException) as exc:
        get_ai_explanation(attempt.id, tq.id, db=db, user=user)
    assert exc.value.status_code == 503


def test_route_rejects_other_users_attempt(finished_attempt):
    db, _, attempt, tq = finished_attempt
    other = User(user_id="U2", email="u2@example.com", first_name="O")
    with pytest.raises(HTTPException) as exc:
        get_ai_explanation(attempt.id, tq.id, db=db, user=other)
    assert exc.value.status_code == 404


def test_generate_raises_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "LLM_BASE_URL", "")
    with pytest.raises(ExplanationError):
        explanation_service.generate_explanation(None)
