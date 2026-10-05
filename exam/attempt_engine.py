"""The exam engine's attempt lifecycle: starting an attempt, viewing/
answering/marking questions, and the server-authoritative timing tick that
locks sections and auto-submits the test when time runs out (spec sections
7, 8, 25, 26).

Design: every read or write against an in-progress attempt calls tick()
first. tick() advances section state purely from wall-clock time compared
against each AttemptSection.ends_at -- there is no background scheduler. If
nobody touches the attempt for hours (closed browser, crashed tab), the next
read correctly fast-forwards through however many sections have since
expired and auto-submits if the whole test has expired, with every lock/
submit timestamped at its official cutoff rather than whenever the tick
happened to run.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from evaluation.scoring import score_responses
from models.attempt import (
    AttemptSection,
    AttemptStatus,
    QuestionAttempt,
    QuestionAttemptStatus,
    QuestionViewEvent,
    SectionAttemptStatus,
    TestAttempt,
)
from models.exam_config import ExamConfig
from models.question_bank import QuestionVersion
from models.test import Test, TestQuestion, TestSection


class AttemptEngineError(Exception):
    """Raised for any attempt action that's invalid given current state --
    e.g. answering a question outside the active section. Routes map this to
    HTTP 409."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime) -> datetime:
    """Treats a naive datetime as UTC. Postgres round-trips DateTime(timezone=
    True) as tz-aware, but some backends (e.g. SQLite, used in local tests)
    hand back naive datetimes -- normalize at every DB-read boundary so
    comparisons against _now() never raise."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _marking_scheme(db: Session, test: Test) -> tuple[float, float]:
    if test.exam_config_id:
        config = db.get(ExamConfig, test.exam_config_id)
        if config:
            return config.marks_per_correct, config.negative_marks
    # Fallback for tests created without an exam config (e.g. ad-hoc custom
    # tests with no marking scheme specified): no negative marking.
    return 1.0, 0.0


def start_attempt(db: Session, *, test: Test, user_id: str) -> TestAttempt:
    started_at = _now()
    attempt = TestAttempt(
        test_id=test.id, user_id=user_id, status=AttemptStatus.in_progress, started_at=started_at
    )
    db.add(attempt)
    db.flush()

    first = True
    for test_section in sorted(test.test_sections, key=lambda ts: ts.order_index):
        attempt_section = AttemptSection(
            attempt_id=attempt.id,
            test_section_id=test_section.id,
            status=SectionAttemptStatus.not_started,
        )
        if first:
            attempt_section.status = SectionAttemptStatus.in_progress
            attempt_section.started_at = started_at
            attempt_section.ends_at = started_at + timedelta(seconds=test_section.time_limit_seconds)
            first = False
        db.add(attempt_section)

        for test_question in test_section.test_questions:
            db.add(
                QuestionAttempt(
                    attempt_id=attempt.id,
                    test_question_id=test_question.id,
                    status=QuestionAttemptStatus.not_visited,
                    time_spent_seconds=0,
                )
            )

    db.commit()
    db.refresh(attempt)
    return attempt


def _close_open_view_events(db: Session, attempt_id: int, *, cutoff: datetime) -> None:
    cutoff = _as_aware(cutoff)
    open_events = (
        db.query(QuestionViewEvent)
        .join(QuestionAttempt, QuestionAttempt.id == QuestionViewEvent.question_attempt_id)
        .filter(QuestionAttempt.attempt_id == attempt_id, QuestionViewEvent.ended_at.is_(None))
        .all()
    )
    for event in open_events:
        started_at = _as_aware(event.started_at)
        ended_at = min(_now(), cutoff)
        if ended_at < started_at:
            ended_at = started_at
        event.ended_at = ended_at
        delta = int((ended_at - started_at).total_seconds())
        qa = db.get(QuestionAttempt, event.question_attempt_id)
        qa.time_spent_seconds += max(delta, 0)


def _evaluate_section(
    db: Session,
    attempt_section: AttemptSection,
    test_section: TestSection,
    *,
    marks_per_correct: float,
    negative_marks: float,
) -> None:
    rows = (
        db.query(QuestionAttempt, QuestionVersion)
        .join(TestQuestion, TestQuestion.id == QuestionAttempt.test_question_id)
        .join(QuestionVersion, QuestionVersion.id == TestQuestion.question_version_id)
        .filter(
            QuestionAttempt.attempt_id == attempt_section.attempt_id,
            TestQuestion.test_section_id == test_section.id,
        )
        .all()
    )

    responses = []
    total_time = 0
    for qa, version in rows:
        qa.is_correct = (
            qa.selected_option_key == version.correct_option_key if qa.selected_option_key else None
        )
        responses.append((qa.selected_option_key, version.correct_option_key))
        total_time += qa.time_spent_seconds

    result = score_responses(responses, marks_per_correct=marks_per_correct, negative_marks=negative_marks)
    attempt_section.attempted = result.attempted
    attempt_section.correct = result.correct
    attempt_section.incorrect = result.incorrect
    attempt_section.accuracy = (result.correct / result.attempted * 100) if result.attempted else 0.0
    attempt_section.avg_time_seconds = (total_time / len(rows)) if rows else 0.0


def _finalize_attempt(
    db: Session, attempt: TestAttempt, *, status: AttemptStatus, submitted_at: datetime
) -> None:
    marks_per_correct, negative_marks = _marking_scheme(db, attempt.test)
    rows = (
        db.query(QuestionAttempt, QuestionVersion)
        .join(TestQuestion, TestQuestion.id == QuestionAttempt.test_question_id)
        .join(QuestionVersion, QuestionVersion.id == TestQuestion.question_version_id)
        .filter(QuestionAttempt.attempt_id == attempt.id)
        .all()
    )

    responses = []
    for qa, version in rows:
        # Sections locked by a prior tick() already have is_correct set
        # (including None for unanswered); only fill in rows never evaluated.
        if qa.is_correct is None and qa.selected_option_key is not None:
            qa.is_correct = qa.selected_option_key == version.correct_option_key
        responses.append((qa.selected_option_key, version.correct_option_key))

    result = score_responses(responses, marks_per_correct=marks_per_correct, negative_marks=negative_marks)
    total_marks_possible = len(responses) * marks_per_correct

    attempt.status = status
    attempt.submitted_at = submitted_at
    attempt.total_questions = len(responses)
    attempt.attempted = result.attempted
    attempt.correct = result.correct
    attempt.incorrect = result.incorrect
    attempt.unattempted = result.unattempted
    attempt.score = result.score
    attempt.accuracy = (result.correct / result.attempted * 100) if result.attempted else 0.0
    attempt.percentage = (result.score / total_marks_possible * 100) if total_marks_possible else 0.0
    attempt.total_time_seconds = int((submitted_at - _as_aware(attempt.started_at)).total_seconds())


def tick(db: Session, attempt: TestAttempt) -> TestAttempt:
    if attempt.status != AttemptStatus.in_progress:
        return attempt

    now = _now()
    marks_per_correct, negative_marks = _marking_scheme(db, attempt.test)
    test_sections = {ts.id: ts for ts in attempt.test.test_sections}
    changed = False

    while True:
        current = next(
            (s for s in attempt.sections if s.status == SectionAttemptStatus.in_progress), None
        )
        if current is None or now < _as_aware(current.ends_at):
            break

        changed = True
        cutoff = _as_aware(current.ends_at)
        _close_open_view_events(db, attempt.id, cutoff=cutoff)
        _evaluate_section(
            db,
            current,
            test_sections[current.test_section_id],
            marks_per_correct=marks_per_correct,
            negative_marks=negative_marks,
        )
        current.status = SectionAttemptStatus.completed
        current.submitted_at = cutoff

        current_order = test_sections[current.test_section_id].order_index
        next_section = next(
            (
                s
                for s in attempt.sections
                if test_sections[s.test_section_id].order_index == current_order + 1
            ),
            None,
        )
        if next_section is None:
            _finalize_attempt(db, attempt, status=AttemptStatus.auto_submitted, submitted_at=cutoff)
            break

        next_section.status = SectionAttemptStatus.in_progress
        next_section.started_at = cutoff
        next_section.ends_at = cutoff + timedelta(
            seconds=test_sections[next_section.test_section_id].time_limit_seconds
        )

    if changed:
        db.commit()
        db.refresh(attempt)
    return attempt


def _current_attempt_section(attempt: TestAttempt) -> AttemptSection | None:
    return next((s for s in attempt.sections if s.status == SectionAttemptStatus.in_progress), None)


def _get_question_attempt(db: Session, attempt: TestAttempt, test_question_id: int) -> QuestionAttempt:
    qa = (
        db.query(QuestionAttempt)
        .filter_by(attempt_id=attempt.id, test_question_id=test_question_id)
        .one_or_none()
    )
    if qa is None:
        raise AttemptEngineError("Question does not belong to this attempt")
    return qa


def _require_in_current_section(
    db: Session, attempt: TestAttempt, test_question_id: int
) -> tuple[QuestionAttempt, AttemptSection]:
    current_section = _current_attempt_section(attempt)
    if current_section is None:
        raise AttemptEngineError("Attempt is no longer in progress")

    qa = _get_question_attempt(db, attempt, test_question_id)
    test_question = db.get(TestQuestion, test_question_id)
    if test_question.test_section_id != current_section.test_section_id:
        raise AttemptEngineError("Question is not in the currently active section")
    return qa, current_section


def view_question(db: Session, attempt: TestAttempt, test_question_id: int) -> QuestionAttempt:
    attempt = tick(db, attempt)
    if attempt.status != AttemptStatus.in_progress:
        raise AttemptEngineError("Attempt is no longer in progress")

    qa, current_section = _require_in_current_section(db, attempt, test_question_id)

    now = _now()
    _close_open_view_events(db, attempt.id, cutoff=current_section.ends_at)

    if qa.first_viewed_at is None:
        qa.first_viewed_at = now
    if qa.status == QuestionAttemptStatus.not_visited:
        qa.status = QuestionAttemptStatus.visited

    db.add(QuestionViewEvent(question_attempt_id=qa.id, started_at=now))
    db.commit()
    db.refresh(qa)
    return qa


def submit_answer(
    db: Session, attempt: TestAttempt, test_question_id: int, *, selected_option_key: str | None
) -> QuestionAttempt:
    attempt = tick(db, attempt)
    if attempt.status != AttemptStatus.in_progress:
        raise AttemptEngineError("Attempt is no longer in progress")

    qa, _ = _require_in_current_section(db, attempt, test_question_id)

    now = _now()
    qa.selected_option_key = selected_option_key
    qa.answered_at = now if selected_option_key else None
    currently_marked = qa.status in (
        QuestionAttemptStatus.marked_for_review,
        QuestionAttemptStatus.answered_marked_for_review,
    )
    if selected_option_key:
        qa.status = (
            QuestionAttemptStatus.answered_marked_for_review
            if currently_marked
            else QuestionAttemptStatus.answered
        )
    else:
        qa.status = (
            QuestionAttemptStatus.marked_for_review if currently_marked else QuestionAttemptStatus.visited
        )

    db.commit()
    db.refresh(qa)
    return qa


def toggle_mark_for_review(
    db: Session, attempt: TestAttempt, test_question_id: int, *, marked: bool
) -> QuestionAttempt:
    attempt = tick(db, attempt)
    if attempt.status != AttemptStatus.in_progress:
        raise AttemptEngineError("Attempt is no longer in progress")

    qa, _ = _require_in_current_section(db, attempt, test_question_id)
    has_answer = qa.selected_option_key is not None
    if marked:
        qa.status = (
            QuestionAttemptStatus.answered_marked_for_review
            if has_answer
            else QuestionAttemptStatus.marked_for_review
        )
    else:
        qa.status = QuestionAttemptStatus.answered if has_answer else QuestionAttemptStatus.visited

    db.commit()
    db.refresh(qa)
    return qa


def apply_bulk_answers(db: Session, attempt: TestAttempt, answers: list) -> None:
    """Applies a batch of client-tracked answers in one shot. Used by the
    submit endpoint for the no-mid-exam-calls flow: the frontend holds every
    answer/visit/mark locally for the whole exam and only reaches the server
    here, right before the existing tick()/evaluate/finalize pipeline runs --
    so a huge wall-clock gap since start_attempt() is still handled exactly
    as before (section timestamps are derived server-side from durations,
    never trusted from the client)."""
    if attempt.status != AttemptStatus.in_progress:
        return

    question_attempts = {
        qa.test_question_id: qa
        for qa in db.query(QuestionAttempt).filter_by(attempt_id=attempt.id).all()
    }
    now = _now()
    for ans in answers:
        qa = question_attempts.get(ans.test_question_id)
        if qa is None:
            continue
        qa.selected_option_key = ans.selected_option_key
        qa.time_spent_seconds = max(0, ans.time_spent_seconds)
        if ans.selected_option_key:
            qa.answered_at = now
            qa.status = (
                QuestionAttemptStatus.answered_marked_for_review
                if ans.marked_for_review
                else QuestionAttemptStatus.answered
            )
        else:
            qa.answered_at = None
            qa.status = (
                QuestionAttemptStatus.marked_for_review
                if ans.marked_for_review
                else (QuestionAttemptStatus.visited if ans.visited else QuestionAttemptStatus.not_visited)
            )
        if ans.visited and qa.first_viewed_at is None:
            qa.first_viewed_at = now

    db.commit()


def submit_attempt(db: Session, attempt: TestAttempt) -> TestAttempt:
    attempt = tick(db, attempt)
    if attempt.status != AttemptStatus.in_progress:
        return attempt

    now = _now()
    marks_per_correct, negative_marks = _marking_scheme(db, attempt.test)
    test_sections = {ts.id: ts for ts in attempt.test.test_sections}
    current_section = _current_attempt_section(attempt)

    _close_open_view_events(db, attempt.id, cutoff=now)
    if current_section is not None:
        _evaluate_section(
            db,
            current_section,
            test_sections[current_section.test_section_id],
            marks_per_correct=marks_per_correct,
            negative_marks=negative_marks,
        )
        current_section.status = SectionAttemptStatus.completed
        current_section.submitted_at = now

    for s in attempt.sections:
        if s.status == SectionAttemptStatus.not_started:
            s.attempted = 0
            s.correct = 0
            s.incorrect = 0
            s.accuracy = 0.0
            s.avg_time_seconds = 0.0

    _finalize_attempt(db, attempt, status=AttemptStatus.submitted, submitted_at=now)
    db.commit()
    db.refresh(attempt)
    return attempt
