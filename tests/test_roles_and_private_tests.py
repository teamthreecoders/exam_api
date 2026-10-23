"""Admin/user split: admin-only routes, private-test generation, and who can
see/take which test."""
import pytest
from fastapi import HTTPException

from api.deps import require_admin
from api.routes.tests import (
    can_access_test,
    create_private_test_route,
    list_tests,
    publish_test,
    question_catalog,
)
from exam.test_generator import SectionSelection, create_test
from models.test import TestMode, TestVisibility
from models.user import User
from question_bank.importer import import_question_bank
from schemas.test import PrivateTestCreateRequest, PrivateTestSectionIn


def _bank(n_quant=6):
    return {
        "test_name": "Bank",
        "exam": "SSC CGL",
        "questions": [
            {
                "question_id": f"Q{i}",
                "section": "Quant",
                "topic": "Percentage" if i % 2 else "Algebra",
                "difficulty": "easy",
                "question": f"q{i}",
                "options": {"A": "1", "B": "2"},
                "correct_answer": "A",
            }
            for i in range(n_quant)
        ],
    }


@pytest.fixture()
def setup(db_session):
    db = db_session
    admin = User(user_id="A1", email="a@x.com", first_name="Admin", role="admin")
    u1 = User(user_id="U1", email="u1@x.com", first_name="One")
    u2 = User(user_id="U2", email="u2@x.com", first_name="Two")
    db.add_all([admin, u1, u2])
    db.commit()
    import_question_bank(db, payload=_bank(), source_filename=None)
    return db, admin, u1, u2


def test_require_admin_rejects_regular_user(setup):
    _, admin, u1, _ = setup
    assert require_admin(admin) is admin
    with pytest.raises(HTTPException) as exc:
        require_admin(u1)
    assert exc.value.status_code == 403


def test_bank_and_config_routes_are_admin_gated():
    from api.routes.exam_config import router as config_router
    from api.routes.question_bank import router as bank_router

    for router in (bank_router, config_router):
        for route in router.routes:
            assert require_admin in [d.call for d in route.dependant.dependencies], route.path


def test_private_test_is_random_scoped_to_topics_and_private(setup):
    db, _, u1, u2 = setup
    payload = PrivateTestCreateRequest(
        name="Mine",
        sections=[
            PrivateTestSectionIn(
                section="Quant", topics=["Percentage"], question_count=3, time_limit_seconds=600
            )
        ],
    )
    summary = create_private_test_route(payload, db=db, user=u1)
    assert summary.visibility == "private" and summary.is_mine
    assert summary.sections[0].question_count == 3

    assert [t.id for t in list_tests(db=db, user=u1)] == [summary.id]
    assert list_tests(db=db, user=u2) == []


def test_private_test_fails_when_not_enough_questions(setup):
    db, _, u1, _ = setup
    payload = PrivateTestCreateRequest(
        name="Too big",
        sections=[PrivateTestSectionIn(section="Quant", question_count=50, time_limit_seconds=600)],
    )
    with pytest.raises(HTTPException) as exc:
        create_private_test_route(payload, db=db, user=u1)
    assert exc.value.status_code == 422


def test_admin_draft_hidden_until_published(setup):
    db, admin, u1, _ = setup
    test = create_test(
        db,
        created_by_user_id=admin.user_id,
        name="Mock 1",
        exam="SSC CGL",
        mode=TestMode.custom,
        exam_config_id=None,
        sections=[SectionSelection("Quant", 2, 300)],
        randomize_questions=True,
        randomize_options=False,
    )
    assert test.visibility == TestVisibility.draft
    assert not can_access_test(test, u1)
    assert list_tests(db=db, user=u1) == []

    publish_test(test.id, db=db, user=admin)
    assert can_access_test(test, u1)
    assert [t.id for t in list_tests(db=db, user=u1)] == [test.id]


def test_catalog_has_counts_only(setup):
    db, _, u1, _ = setup
    cat = question_catalog(db=db, _=u1)
    assert cat[0].section == "Quant" and cat[0].question_count == 6
    assert {t.topic: t.question_count for t in cat[0].topics} == {"Percentage": 3, "Algebra": 3}


def test_test_names_must_be_unique(setup):
    db, admin, u1, u2 = setup

    def private(user, name):
        return create_private_test_route(
            PrivateTestCreateRequest(
                name=name,
                sections=[PrivateTestSectionIn(section="Quant", question_count=2, time_limit_seconds=300)],
            ),
            db=db,
            user=user,
        )

    private(u1, "Practice 1")
    # Same user, different case/spacing -> rejected.
    with pytest.raises(HTTPException) as exc:
        private(u1, "  practice 1 ")
    assert exc.value.status_code == 409
    # Another user's private test doesn't block, and isn't revealed.
    private(u2, "Practice 1")

    # Admin names: unique among non-private tests, unaffected by private ones.
    from api.routes.tests import create_test_route
    from schemas.test import TestCreateRequest, TestSectionSelectionIn

    def admin_test(name):
        return create_test_route(
            TestCreateRequest(
                name=name,
                mode="custom",
                sections=[TestSectionSelectionIn(section="Quant", question_count=2, time_limit_seconds=300)],
            ),
            db=db,
            user=admin,
        )

    admin_test("Practice 1")
    with pytest.raises(HTTPException) as exc:
        admin_test("PRACTICE 1")
    assert exc.value.status_code == 409
    # A user can no longer reuse a name that is now taken by a visible admin test.
    with pytest.raises(HTTPException):
        private(u1, "Practice 1 ")


def test_delete_only_unpublished_test(setup):
    from api.routes.tests import delete_test, unpublish_test

    db, admin, u1, _ = setup
    test = create_test(
        db, created_by_user_id=admin.user_id, name="T", exam="SSC CGL", mode=TestMode.custom,
        exam_config_id=None, sections=[SectionSelection("Quant", 2, 60)],
        randomize_questions=False, randomize_options=False, visibility=TestVisibility.draft,
    )
    publish_test(test.id, db=db, user=admin)
    with pytest.raises(HTTPException) as exc:
        delete_test(test.id, db=db, _=admin)
    assert exc.value.status_code == 409
    unpublish_test(test.id, db=db, user=admin)
    delete_test(test.id, db=db, _=admin)
    assert db.get(type(test), test.id) is None


def test_bank_page_filters(setup):
    from api.routes.question_bank import bank_filter_options, list_banks_page

    db, admin, *_ = setup
    pyq = _bank(2)
    pyq["test_name"] = "CGL PYQ 2025"
    pyq["exam"] = "SSC CHSL"
    import_question_bank(db, payload=pyq, source_filename=None)

    def page(**kw):
        args = dict(exam=None, section=None, pyq=None, q=None, limit=20, offset=0, db=db, _=admin)
        return list_banks_page(**{**args, **kw})

    assert page().total == 2
    assert [b.name for b in page(pyq=True).items] == ["CGL PYQ 2025"]
    assert page(pyq=False).total == 1
    assert page(exam="SSC CHSL").total == 1
    assert page(section="Quant").total == 2 and page(section="Nope").total == 0
    assert page(limit=1).has_more is True
    assert bank_filter_options(db=db, _=admin).exams == ["SSC CGL", "SSC CHSL"]
