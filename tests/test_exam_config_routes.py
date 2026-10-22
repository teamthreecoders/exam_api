from fastapi import Response

from api.routes.exam_config import create_exam_config, list_exam_configs
from models.exam_config import ExamConfig, ExamConfigSection
from models.section_topic import Section
from schemas.exam_config import ExamConfigCreate, ExamConfigSectionIn


def _payload(**overrides):
    base = dict(
        exam="SSC CGL",
        name="SSC CGL Tier 1",
        marks_per_correct=2,
        negative_marks=0.5,
        sections=[
            ExamConfigSectionIn(name="Reasoning", question_count=25, time_limit_seconds=900),
            ExamConfigSectionIn(name="Quant", question_count=25, time_limit_seconds=900),
        ],
    )
    base.update(overrides)
    return ExamConfigCreate(**base)


def _create(db, payload):
    # FastAPI hands routes a Response whose status_code starts as None (the
    # route's declared 201 applies unless the handler overrides it); mimic that.
    response = Response()
    response.status_code = None
    out = create_exam_config(payload, response, db, None)
    return out, response.status_code


def test_first_create_inserts_and_keeps_declared_201(db_session):
    out, status_code = _create(db_session, _payload())
    assert out.id is not None
    assert status_code is None  # not overridden -> FastAPI applies the declared 201
    assert db_session.query(ExamConfig).count() == 1


def test_posting_identical_config_again_returns_existing_without_duplicating(db_session):
    first, _ = _create(db_session, _payload())
    second, status_code = _create(db_session, _payload())

    assert second.id == first.id
    assert status_code == 200
    assert db_session.query(ExamConfig).count() == 1
    assert db_session.query(ExamConfigSection).count() == 2


def test_changed_timing_is_a_different_config(db_session):
    first, _ = _create(db_session, _payload())
    other, _ = _create(
        db_session,
        _payload(
            sections=[
                ExamConfigSectionIn(name="Reasoning", question_count=25, time_limit_seconds=600),
                ExamConfigSectionIn(name="Quant", question_count=25, time_limit_seconds=900),
            ]
        ),
    )
    assert other.id != first.id
    assert db_session.query(ExamConfig).count() == 2


def test_list_collapses_duplicates_that_already_exist(db_session):
    # Simulate rows left behind by the old non-idempotent endpoint.
    for _ in range(3):
        config = ExamConfig(exam="SSC CGL", name="SSC CGL Tier 1", marks_per_correct=2, negative_marks=0.5)
        db_session.add(config)
        db_session.flush()
        section = db_session.query(Section).filter_by(name="Reasoning").one_or_none()
        if section is None:
            section = Section(name="Reasoning")
            db_session.add(section)
            db_session.flush()
        db_session.add(
            ExamConfigSection(
                exam_config_id=config.id,
                section_id=section.id,
                question_count=25,
                time_limit_seconds=900,
                order_index=0,
            )
        )
    db_session.commit()
    assert db_session.query(ExamConfig).count() == 3

    listed = list_exam_configs(db_session, None)

    assert len(listed) == 1
    assert listed[0].id == min(c.id for c in db_session.query(ExamConfig).all())
