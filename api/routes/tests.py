from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps import get_current_user
from database.session import get_db
from exam.test_generator import SectionSelection, TestGenerationError
from exam.test_generator import create_test as engine_create_test
from models.section_topic import Section
from models.test import Test, TestMode, TestSection
from models.user import User
from schemas.test import TestCreateRequest, TestSectionSummary, TestSummary

router = APIRouter(prefix="/api/tests", tags=["tests"])


def _to_summary(db: Session, test: Test) -> TestSummary:
    rows = (
        db.query(TestSection, Section)
        .join(Section, Section.id == TestSection.section_id)
        .filter(TestSection.test_id == test.id)
        .order_by(TestSection.order_index)
        .all()
    )
    return TestSummary(
        id=test.id,
        name=test.name,
        exam=test.exam,
        mode=test.mode.value,
        randomize_questions=test.randomize_questions,
        randomize_options=test.randomize_options,
        sections=[
            TestSectionSummary(
                section=sec.name,
                question_count=ts.question_count,
                time_limit_seconds=ts.time_limit_seconds,
            )
            for ts, sec in rows
        ],
    )


@router.post("", response_model=TestSummary, status_code=status.HTTP_201_CREATED)
def create_test_route(
    payload: TestCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TestSummary:
    try:
        mode = TestMode(payload.mode)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"mode must be one of {[m.value for m in TestMode]}",
        ) from exc

    try:
        test = engine_create_test(
            db,
            created_by_user_id=user.user_id,
            name=payload.name,
            exam=payload.exam,
            mode=mode,
            exam_config_id=payload.exam_config_id,
            sections=[
                SectionSelection(
                    section_name=s.section,
                    question_count=s.question_count,
                    time_limit_seconds=s.time_limit_seconds,
                    topics=s.topics,
                    difficulties=s.difficulties,
                    year=s.year,
                    source=s.source,
                )
                for s in payload.sections
            ],
            randomize_questions=payload.randomize_questions,
            randomize_options=payload.randomize_options,
            question_bank_id=payload.question_bank_id,
        )
    except TestGenerationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return _to_summary(db, test)


@router.get("", response_model=list[TestSummary])
def list_tests(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[TestSummary]:
    tests = db.query(Test).filter_by(created_by_user_id=user.user_id).all()
    return [_to_summary(db, t) for t in tests]


@router.get("/{test_id}", response_model=TestSummary)
def get_test(
    test_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> TestSummary:
    test = db.get(Test, test_id)
    if test is None or test.created_by_user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Test not found")
    return _to_summary(db, test)
