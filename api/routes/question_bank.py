import json

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.deps import get_current_user
from database.session import get_db
from models.question_bank import Question, QuestionBank, QuestionVersion
from models.section_topic import Section, Topic
from models.user import User
from question_bank.importer import import_question_bank
from question_bank.validator import validate_question_bank
from schemas.question_bank import (
    ImportValidationErrorResponse,
    QuestionBankListItem,
    QuestionBankSectionBreakdown,
    QuestionBankSummary,
    QuestionDetailOut,
    QuestionListItem,
    QuestionListPage,
    QuestionOptionOut,
    ValidationErrorItem,
)

router = APIRouter(prefix="/api/question-bank", tags=["question-bank"])


@router.post("/import", response_model=QuestionBankSummary, status_code=status.HTTP_201_CREATED)
def import_bank(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> QuestionBankSummary:
    try:
        payload = json.loads(file.file.read())
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid JSON: {exc}") from exc

    result = validate_question_bank(payload)
    if not result.is_valid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ImportValidationErrorResponse(
                errors=[ValidationErrorItem(**vars(e)) for e in result.errors]
            ).model_dump(),
        )

    bank = import_question_bank(db, payload=payload, source_filename=file.filename)
    return QuestionBankSummary(
        id=bank.id, name=bank.name, exam=bank.exam, question_count=len(payload["questions"])
    )


@router.get("/banks", response_model=list[QuestionBankListItem])
def list_banks(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[QuestionBankListItem]:
    """Every imported JSON file, most recent first -- lets a test be scoped to
    exactly one upload (e.g. 'only questions from the set I just imported')
    instead of the whole shared bank."""
    rows = (
        db.query(QuestionBank, func.count(Question.id))
        .outerjoin(
            Question, (Question.question_bank_id == QuestionBank.id) & Question.is_deleted.is_(False)
        )
        .group_by(QuestionBank.id)
        .order_by(QuestionBank.created_at.desc(), QuestionBank.id.desc())
        .all()
    )
    return [
        QuestionBankListItem(
            id=bank.id,
            name=bank.name,
            exam=bank.exam,
            source_filename=bank.source_filename,
            question_count=count,
            created_at=bank.created_at,
        )
        for bank, count in rows
    ]


@router.get("/banks/{bank_id}/sections", response_model=list[QuestionBankSectionBreakdown])
def bank_section_breakdown(
    bank_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[QuestionBankSectionBreakdown]:
    """How many questions this one upload has per section -- lets the
    frontend auto-fill a test's sections/counts straight from a specific
    question paper (e.g. launching a PYQ test) instead of the user re-typing
    counts that are already implied by the upload."""
    if db.get(QuestionBank, bank_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question bank not found")

    rows = (
        db.query(Section.name, func.count(Question.id))
        .join(QuestionVersion, QuestionVersion.section_id == Section.id)
        .join(Question, Question.current_version_id == QuestionVersion.id)
        .filter(Question.is_deleted.is_(False), Question.question_bank_id == bank_id)
        .group_by(Section.name)
        .order_by(Section.name)
        .all()
    )
    return [QuestionBankSectionBreakdown(section=name, question_count=count) for name, count in rows]


@router.get("/sections", response_model=list[str])
def list_sections(
    question_bank_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[str]:
    """Distinct section names actually present in the bank -- used by
    CreateTestPage's section picker, which needs every section regardless of
    the 50-at-a-time pagination on /questions. Pass question_bank_id to scope
    this to a single upload instead of the whole shared bank."""
    query = (
        db.query(Section.name)
        .join(QuestionVersion, QuestionVersion.section_id == Section.id)
        .join(Question, Question.current_version_id == QuestionVersion.id)
        .filter(Question.is_deleted.is_(False))
    )
    if question_bank_id is not None:
        query = query.filter(Question.question_bank_id == question_bank_id)
    rows = query.distinct().order_by(Section.name).all()
    return [name for (name,) in rows]


@router.get("/questions", response_model=QuestionListPage)
def list_questions(
    section: str | None = None,
    topic: str | None = None,
    difficulty: str | None = None,
    source: str | None = None,
    year: int | None = None,
    question_bank_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> QuestionListPage:
    query = (
        db.query(Question, QuestionVersion, Section, Topic)
        .join(QuestionVersion, QuestionVersion.id == Question.current_version_id)
        .join(Section, Section.id == QuestionVersion.section_id)
        .join(Topic, Topic.id == QuestionVersion.topic_id)
        .filter(Question.is_deleted.is_(False))
    )
    if section:
        query = query.filter(Section.name == section)
    if topic:
        query = query.filter(Topic.name == topic)
    if difficulty:
        query = query.filter(QuestionVersion.difficulty == difficulty)
    if source:
        query = query.filter(QuestionVersion.source == source)
    if year:
        query = query.filter(QuestionVersion.year == year)
    if question_bank_id is not None:
        query = query.filter(Question.question_bank_id == question_bank_id)

    total = query.count()
    # Explicit, stable ordering is required for LIMIT/OFFSET to page through a
    # consistent sequence -- without it Postgres is free to return rows in a
    # different order across calls, which would duplicate or skip questions
    # between pages.
    rows = query.order_by(Question.id).offset(offset).limit(limit).all()

    items = [
        QuestionListItem(
            id=question.id,
            external_question_id=question.external_question_id,
            section=sec.name,
            topic=top.name,
            subtopic=version.subtopic,
            difficulty=version.difficulty.value,
            question_text=version.question_text,
            source=version.source,
            year=version.year,
            shift=version.shift,
        )
        for question, version, sec, top in rows
    ]
    return QuestionListPage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(items) < total,
    )


@router.get("/questions/{question_id}", response_model=QuestionDetailOut)
def get_question_detail(
    question_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> QuestionDetailOut:
    """Full detail for one question -- options and the correct answer --
    fetched on demand when a row is expanded in the browse UI, rather than
    inflating the paginated list response for every question up front."""
    row = (
        db.query(Question, QuestionVersion, Section, Topic)
        .join(QuestionVersion, QuestionVersion.id == Question.current_version_id)
        .join(Section, Section.id == QuestionVersion.section_id)
        .join(Topic, Topic.id == QuestionVersion.topic_id)
        .filter(Question.id == question_id, Question.is_deleted.is_(False))
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")

    question, version, sec, top = row
    return QuestionDetailOut(
        id=question.id,
        external_question_id=question.external_question_id,
        section=sec.name,
        topic=top.name,
        subtopic=version.subtopic,
        difficulty=version.difficulty.value,
        question_text=version.question_text,
        options=[QuestionOptionOut(key=o.option_key, text=o.option_text) for o in version.options],
        correct_option_key=version.correct_option_key,
        explanation=version.explanation,
        source=version.source,
        year=version.year,
        shift=version.shift,
    )
