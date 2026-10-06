from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps import get_current_user
from api.routes.tests import can_access_test
from database.session import get_db
from exam.attempt_engine import AttemptEngineError
from exam.attempt_engine import apply_bulk_answers as engine_apply_bulk_answers
from exam.attempt_engine import start_attempt as engine_start_attempt
from exam.attempt_engine import submit_answer as engine_submit_answer
from exam.attempt_engine import submit_attempt as engine_submit_attempt
from exam.attempt_engine import tick
from exam.attempt_engine import toggle_mark_for_review as engine_toggle_mark
from exam.attempt_engine import view_question as engine_view_question
from models.attempt import AttemptStatus, QuestionAttempt, TestAttempt
from models.question_bank import QuestionVersion
from models.section_topic import Section, Topic
from models.test import Test, TestQuestion
from models.user import User
from schemas.attempt import (
    AnswerRequest,
    AttemptFullStateOut,
    AttemptResultOut,
    AttemptStateOut,
    AttemptSummaryOut,
    BulkSubmitRequest,
    FullQuestionOut,
    FullSectionOut,
    MarkRequest,
    OptionOut,
    QuestionResultOut,
    QuestionStateOut,
    SectionResultOut,
    SectionStateOut,
)

router = APIRouter(prefix="/api/attempts", tags=["attempts"])


def _get_owned_attempt(db: Session, attempt_id: int, user: User) -> TestAttempt:
    attempt = db.get(TestAttempt, attempt_id)
    if attempt is None or attempt.user_id != user.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    return attempt


def _seconds_remaining(ends_at: datetime | None) -> int | None:
    if ends_at is None:
        return None
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=timezone.utc)
    return max(0, int((ends_at - datetime.now(timezone.utc)).total_seconds()))


def _build_state(db: Session, attempt: TestAttempt) -> AttemptStateOut:
    test_sections = {ts.id: ts for ts in attempt.test.test_sections}
    section_names = {sec.id: sec.name for sec in db.query(Section).all()}

    sections_out = []
    current_attempt_section = None
    current_section_out = None
    for a_sec in sorted(attempt.sections, key=lambda s: test_sections[s.test_section_id].order_index):
        ts = test_sections[a_sec.test_section_id]
        is_active = a_sec.status.value == "in_progress"
        out = SectionStateOut(
            test_section_id=ts.id,
            section=section_names[ts.section_id],
            order_index=ts.order_index,
            status=a_sec.status.value,
            started_at=a_sec.started_at,
            ends_at=a_sec.ends_at,
            seconds_remaining=_seconds_remaining(a_sec.ends_at) if is_active else None,
        )
        sections_out.append(out)
        if is_active:
            current_section_out = out
            current_attempt_section = a_sec

    questions_out: list[QuestionStateOut] = []
    if current_attempt_section is not None:
        current_ts = test_sections[current_attempt_section.test_section_id]
        rows = (
            db.query(QuestionAttempt, TestQuestion, QuestionVersion)
            .join(TestQuestion, TestQuestion.id == QuestionAttempt.test_question_id)
            .join(QuestionVersion, QuestionVersion.id == TestQuestion.question_version_id)
            .filter(
                QuestionAttempt.attempt_id == attempt.id, TestQuestion.test_section_id == current_ts.id
            )
            .order_by(TestQuestion.order_index)
            .all()
        )
        for qa, tq, version in rows:
            option_texts = {o.option_key: o.option_text for o in version.options}
            options = [OptionOut(key=k, text=option_texts[k]) for k in tq.option_order]
            questions_out.append(
                QuestionStateOut(
                    test_question_id=tq.id,
                    order_index=tq.order_index,
                    question_text=version.question_text,
                    options=options,
                    section=section_names[current_ts.section_id],
                    status=qa.status.value,
                    selected_option_key=qa.selected_option_key,
                    time_spent_seconds=qa.time_spent_seconds,
                )
            )

    return AttemptStateOut(
        attempt_id=attempt.id,
        status=attempt.status.value,
        current_section=current_section_out,
        sections=sections_out,
        questions=questions_out,
    )


def _build_full_state(db: Session, attempt: TestAttempt) -> AttemptFullStateOut:
    test_sections = sorted(attempt.test.test_sections, key=lambda ts: ts.order_index)
    section_names = {sec.id: sec.name for sec in db.query(Section).all()}

    sections_out = [
        FullSectionOut(
            test_section_id=ts.id,
            section=section_names[ts.section_id],
            order_index=ts.order_index,
            time_limit_seconds=ts.time_limit_seconds,
        )
        for ts in test_sections
    ]

    rows = (
        db.query(TestQuestion, QuestionVersion)
        .join(QuestionVersion, QuestionVersion.id == TestQuestion.question_version_id)
        .filter(TestQuestion.test_section_id.in_([ts.id for ts in test_sections]))
        .order_by(TestQuestion.test_section_id, TestQuestion.order_index)
        .all()
    )
    questions_out = []
    for tq, version in rows:
        option_texts = {o.option_key: o.option_text for o in version.options}
        options = [OptionOut(key=k, text=option_texts[k]) for k in tq.option_order]
        questions_out.append(
            FullQuestionOut(
                test_question_id=tq.id,
                test_section_id=tq.test_section_id,
                order_index=tq.order_index,
                question_text=version.question_text,
                options=options,
            )
        )

    return AttemptFullStateOut(
        attempt_id=attempt.id,
        status=attempt.status.value,
        started_at=attempt.started_at,
        sections=sections_out,
        questions=questions_out,
    )


def _build_result(db: Session, attempt: TestAttempt) -> AttemptResultOut:
    test_sections = {ts.id: ts for ts in attempt.test.test_sections}
    sections_by_id = {sec.id: sec for sec in db.query(Section).all()}
    topics_by_id = {t.id: t for t in db.query(Topic).all()}

    sections_out = [
        SectionResultOut(
            section=sections_by_id[test_sections[a_sec.test_section_id].section_id].name,
            attempted=a_sec.attempted or 0,
            correct=a_sec.correct or 0,
            incorrect=a_sec.incorrect or 0,
            accuracy=a_sec.accuracy or 0.0,
            avg_time_seconds=a_sec.avg_time_seconds or 0.0,
        )
        for a_sec in sorted(attempt.sections, key=lambda s: test_sections[s.test_section_id].order_index)
    ]

    rows = (
        db.query(QuestionAttempt, TestQuestion, QuestionVersion)
        .join(TestQuestion, TestQuestion.id == QuestionAttempt.test_question_id)
        .join(QuestionVersion, QuestionVersion.id == TestQuestion.question_version_id)
        .filter(QuestionAttempt.attempt_id == attempt.id)
        .order_by(TestQuestion.test_section_id, TestQuestion.order_index)
        .all()
    )
    questions_out = []
    for qa, tq, version in rows:
        option_texts = {o.option_key: o.option_text for o in version.options}
        options = [OptionOut(key=k, text=option_texts[k]) for k in tq.option_order]
        questions_out.append(
            QuestionResultOut(
                test_question_id=tq.id,
                section=sections_by_id[version.section_id].name,
                topic=topics_by_id[version.topic_id].name,
                difficulty=version.difficulty.value,
                question_text=version.question_text,
                options=options,
                selected_option_key=qa.selected_option_key,
                correct_option_key=version.correct_option_key,
                is_correct=qa.is_correct,
                status=qa.status.value,
                time_spent_seconds=qa.time_spent_seconds,
                explanation=version.explanation,
            )
        )

    return AttemptResultOut(
        attempt_id=attempt.id,
        status=attempt.status.value,
        total_questions=attempt.total_questions or 0,
        attempted=attempt.attempted or 0,
        correct=attempt.correct or 0,
        incorrect=attempt.incorrect or 0,
        unattempted=attempt.unattempted or 0,
        score=attempt.score or 0.0,
        accuracy=attempt.accuracy or 0.0,
        percentage=attempt.percentage or 0.0,
        total_time_seconds=attempt.total_time_seconds or 0,
        sections=sections_out,
        questions=questions_out,
    )


@router.get("", response_model=list[AttemptSummaryOut])
def list_attempts(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[AttemptSummaryOut]:
    rows = (
        db.query(TestAttempt, Test)
        .join(Test, Test.id == TestAttempt.test_id)
        .filter(TestAttempt.user_id == user.user_id)
        .order_by(TestAttempt.started_at.desc())
        .all()
    )
    return [
        AttemptSummaryOut(
            attempt_id=a.id,
            test_id=a.test_id,
            test_name=t.name,
            status=a.status.value,
            started_at=a.started_at,
            submitted_at=a.submitted_at,
            total_questions=a.total_questions,
            attempted=a.attempted,
            correct=a.correct,
            incorrect=a.incorrect,
            unattempted=a.unattempted,
            score=a.score,
            accuracy=a.accuracy,
            percentage=a.percentage,
            total_time_seconds=a.total_time_seconds,
        )
        for a, t in rows
    ]


@router.post("/start", response_model=AttemptStateOut, status_code=status.HTTP_201_CREATED)
def start_attempt(
    test_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> AttemptStateOut:
    test = db.get(Test, test_id)
    if test is None or not can_access_test(test, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Test not found")

    existing = (
        db.query(TestAttempt)
        .filter_by(test_id=test_id, user_id=user.user_id, status=AttemptStatus.in_progress)
        .one_or_none()
    )
    attempt = tick(db, existing) if existing else engine_start_attempt(db, test=test, user_id=user.user_id)
    return _build_state(db, attempt)


@router.get("/{attempt_id}", response_model=AttemptStateOut)
def get_attempt(
    attempt_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> AttemptStateOut:
    attempt = _get_owned_attempt(db, attempt_id, user)
    attempt = tick(db, attempt)
    return _build_state(db, attempt)


@router.get("/{attempt_id}/full", response_model=AttemptFullStateOut)
def get_attempt_full(
    attempt_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> AttemptFullStateOut:
    """One-shot download of every section and question for the whole test, so
    the frontend can run the entire exam (navigation, answering, section
    timing/locking) without any further server round trips until submit."""
    attempt = _get_owned_attempt(db, attempt_id, user)
    attempt = tick(db, attempt)
    return _build_full_state(db, attempt)


@router.post("/{attempt_id}/questions/{test_question_id}/view", response_model=AttemptStateOut)
def view_question(
    attempt_id: int,
    test_question_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AttemptStateOut:
    attempt = _get_owned_attempt(db, attempt_id, user)
    try:
        engine_view_question(db, attempt, test_question_id)
    except AttemptEngineError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _build_state(db, attempt)


@router.post("/{attempt_id}/questions/{test_question_id}/answer", response_model=AttemptStateOut)
def answer_question(
    attempt_id: int,
    test_question_id: int,
    payload: AnswerRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AttemptStateOut:
    attempt = _get_owned_attempt(db, attempt_id, user)
    try:
        engine_submit_answer(
            db, attempt, test_question_id, selected_option_key=payload.selected_option_key
        )
    except AttemptEngineError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _build_state(db, attempt)


@router.post("/{attempt_id}/questions/{test_question_id}/mark", response_model=AttemptStateOut)
def mark_question(
    attempt_id: int,
    test_question_id: int,
    payload: MarkRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AttemptStateOut:
    attempt = _get_owned_attempt(db, attempt_id, user)
    try:
        engine_toggle_mark(db, attempt, test_question_id, marked=payload.marked)
    except AttemptEngineError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _build_state(db, attempt)


@router.post("/{attempt_id}/questions/{test_question_id}/clear", response_model=AttemptStateOut)
def clear_question(
    attempt_id: int,
    test_question_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AttemptStateOut:
    attempt = _get_owned_attempt(db, attempt_id, user)
    try:
        engine_submit_answer(db, attempt, test_question_id, selected_option_key=None)
    except AttemptEngineError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _build_state(db, attempt)


@router.post("/{attempt_id}/submit", response_model=AttemptResultOut)
def submit_attempt(
    attempt_id: int,
    payload: BulkSubmitRequest = Body(default_factory=BulkSubmitRequest),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AttemptResultOut:
    """Accepts the client's full locally-tracked answer set (every
    selection/visit/mark/time-spent made during the exam with no prior server
    calls) and applies it before running the normal tick()/evaluate/finalize
    pipeline.

    Deliberately does NOT call tick() before checking status/applying the
    bulk answers: since the frontend never contacts the server mid-exam, by
    the time a real multi-section exam is submitted every section's
    wall-clock time has typically already elapsed. Ticking first would
    cascade through and auto-finalize the attempt using the still-empty
    QuestionAttempt rows (nothing has been written yet), scoring everything
    as unattempted and then skipping the bulk-answers apply entirely because
    status is no longer in_progress -- silently discarding every real answer
    the client sent. Nothing but this handler (and tick()/submit_attempt
    themselves) ever changes `attempt.status`, so reading it directly off the
    freshly-fetched attempt is exactly as current as calling tick() first
    would be, without the ordering hazard. `engine_submit_attempt` below
    still calls tick() itself, but now only after the real answers are
    already in place, so it evaluates against the truth rather than a blank
    slate. If the attempt already finished -- e.g. this is a duplicate
    submit -- the bulk answers are discarded and whatever was already
    finalized is returned unchanged."""
    attempt = _get_owned_attempt(db, attempt_id, user)
    if attempt.status == AttemptStatus.in_progress:
        engine_apply_bulk_answers(db, attempt, payload.answers)
        attempt = engine_submit_attempt(db, attempt)
    return _build_result(db, attempt)


@router.get("/{attempt_id}/result", response_model=AttemptResultOut)
def get_result(
    attempt_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> AttemptResultOut:
    attempt = _get_owned_attempt(db, attempt_id, user)
    attempt = tick(db, attempt)
    if attempt.status == AttemptStatus.in_progress:
        raise HTTPException(status.HTTP_409_CONFLICT, "Attempt is still in progress")
    return _build_result(db, attempt)
