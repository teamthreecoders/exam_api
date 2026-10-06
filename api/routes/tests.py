from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from api.deps import get_current_user, require_admin
from database.session import get_db
from exam.test_generator import SectionSelection, TestGenerationError
from exam.test_generator import create_test as engine_create_test
from models.question_bank import Question, QuestionVersion
from models.section_topic import Section, Topic
from models.test import Test, TestMode, TestSection, TestVisibility
from models.user import User
from schemas.test import (
    CatalogSection,
    CatalogTopic,
    PrivateTestCreateRequest,
    TestCreateRequest,
    TestSectionSummary,
    TestSummary,
)

router = APIRouter(prefix="/api/tests", tags=["tests"])


def can_access_test(test: Test, user: User) -> bool:
    """Published tests are open to every user; anything else (admin drafts,
    user-generated private tests) only to the user who created it."""
    return test.visibility == TestVisibility.published or test.created_by_user_id == user.user_id


def _to_summary(db: Session, test: Test, user: User) -> TestSummary:
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
        visibility=test.visibility,
        is_mine=test.created_by_user_id == user.user_id,
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
    user: User = Depends(require_admin),
) -> TestSummary:
    """Admin-only. The test starts as a draft; publish it to make it
    available to every user."""
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
            visibility=TestVisibility.draft,
        )
    except TestGenerationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return _to_summary(db, test, user)


@router.post("/private", response_model=TestSummary, status_code=status.HTTP_201_CREATED)
def create_private_test_route(
    payload: PrivateTestCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TestSummary:
    """Any user: pick sections/topics, question count per section, time per
    section and a name. Questions are drawn at random from the whole bank;
    the resulting test is visible only to its creator."""
    try:
        test = engine_create_test(
            db,
            created_by_user_id=user.user_id,
            name=payload.name.strip(),
            exam="SSC CGL",
            mode=TestMode.custom,
            exam_config_id=None,
            sections=[
                SectionSelection(
                    section_name=s.section,
                    question_count=s.question_count,
                    time_limit_seconds=s.time_limit_seconds,
                    topics=s.topics or None,
                )
                for s in payload.sections
            ],
            randomize_questions=True,
            randomize_options=True,
            visibility=TestVisibility.private,
        )
    except TestGenerationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return _to_summary(db, test, user)


@router.get("/catalog", response_model=list[CatalogSection])
def question_catalog(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[CatalogSection]:
    """Sections and topics with how many questions are available, for the
    private-test form. Counts only -- no question content or answers."""
    rows = (
        db.query(Section.name, Topic.name, func.count(Question.id))
        .select_from(QuestionVersion)
        .join(Question, Question.current_version_id == QuestionVersion.id)
        .join(Section, Section.id == QuestionVersion.section_id)
        .join(Topic, Topic.id == QuestionVersion.topic_id)
        .filter(Question.is_deleted.is_(False))
        .group_by(Section.name, Topic.name)
        .order_by(Section.name, Topic.name)
        .all()
    )
    sections: dict[str, CatalogSection] = {}
    for section, topic, count in rows:
        entry = sections.setdefault(section, CatalogSection(section=section, question_count=0, topics=[]))
        entry.question_count += count
        entry.topics.append(CatalogTopic(topic=topic, question_count=count))
    return list(sections.values())


@router.get("", response_model=list[TestSummary])
def list_tests(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[TestSummary]:
    """Published tests plus the caller's own tests (private ones, or an
    admin's drafts). Admins additionally see every other admin's drafts."""
    query = db.query(Test)
    if user.role == "admin":
        query = query.filter(
            or_(Test.visibility != TestVisibility.private, Test.created_by_user_id == user.user_id)
        )
    else:
        query = query.filter(
            or_(Test.visibility == TestVisibility.published, Test.created_by_user_id == user.user_id)
        )
    return [_to_summary(db, t, user) for t in query.order_by(Test.id.desc()).all()]


@router.get("/{test_id}", response_model=TestSummary)
def get_test(
    test_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> TestSummary:
    test = db.get(Test, test_id)
    if test is None or not can_access_test(test, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Test not found")
    return _to_summary(db, test, user)


def _set_visibility(db: Session, test_id: int, visibility: str, user: User) -> TestSummary:
    test = db.get(Test, test_id)
    if test is None or test.visibility == TestVisibility.private:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Test not found")
    test.visibility = visibility
    db.commit()
    db.refresh(test)
    return _to_summary(db, test, user)


@router.post("/{test_id}/publish", response_model=TestSummary)
def publish_test(
    test_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)
) -> TestSummary:
    return _set_visibility(db, test_id, TestVisibility.published, user)


@router.post("/{test_id}/unpublish", response_model=TestSummary)
def unpublish_test(
    test_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)
) -> TestSummary:
    return _set_visibility(db, test_id, TestVisibility.draft, user)
