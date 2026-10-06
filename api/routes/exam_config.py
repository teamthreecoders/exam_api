from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from api.deps import require_admin
from database.session import get_db
from models.exam_config import ExamConfig, ExamConfigSection
from models.section_topic import Section
from models.user import User
from schemas.exam_config import ExamConfigCreate, ExamConfigOut, ExamConfigSectionOut

router = APIRouter(prefix="/api/exam-configs", tags=["exam-configs"])


def _get_or_create_section(db: Session, name: str) -> Section:
    section = db.query(Section).filter_by(name=name).one_or_none()
    if section is None:
        section = Section(name=name)
        db.add(section)
        db.flush()
    return section


def _to_out(db: Session, config: ExamConfig) -> ExamConfigOut:
    rows = (
        db.query(ExamConfigSection, Section)
        .join(Section, Section.id == ExamConfigSection.section_id)
        .filter(ExamConfigSection.exam_config_id == config.id)
        .order_by(ExamConfigSection.order_index)
        .all()
    )
    return ExamConfigOut(
        id=config.id,
        exam=config.exam,
        name=config.name,
        marks_per_correct=config.marks_per_correct,
        negative_marks=config.negative_marks,
        sections=[
            ExamConfigSectionOut(
                name=sec.name,
                question_count=ecs.question_count,
                time_limit_seconds=ecs.time_limit_seconds,
            )
            for ecs, sec in rows
        ],
    )


def _signature(
    exam: str,
    name: str,
    marks_per_correct: float,
    negative_marks: float,
    sections: list[tuple[str, int, int]],
) -> tuple:
    """Everything that makes two exam configs interchangeable. Two configs
    with the same signature behave identically for timing and scoring, so
    there is never a reason to keep (or show) both."""
    return (exam, name, marks_per_correct, negative_marks, tuple(sections))


def _out_signature(out: ExamConfigOut) -> tuple:
    return _signature(
        out.exam,
        out.name,
        out.marks_per_correct,
        out.negative_marks,
        [(s.name, s.question_count, s.time_limit_seconds) for s in out.sections],
    )


@router.post("", response_model=ExamConfigOut, status_code=status.HTTP_201_CREATED)
def create_exam_config(
    payload: ExamConfigCreate,
    response: Response,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> ExamConfigOut:
    """Idempotent: posting a config identical to an existing one returns that
    existing config (200) instead of inserting a duplicate (201)."""
    wanted = _signature(
        payload.exam,
        payload.name,
        payload.marks_per_correct,
        payload.negative_marks,
        [(s.name, s.question_count, s.time_limit_seconds) for s in payload.sections],
    )
    candidates = (
        db.query(ExamConfig)
        .filter_by(
            exam=payload.exam,
            name=payload.name,
            marks_per_correct=payload.marks_per_correct,
            negative_marks=payload.negative_marks,
        )
        .order_by(ExamConfig.id)
        .all()
    )
    for candidate in candidates:
        existing = _to_out(db, candidate)
        if _out_signature(existing) == wanted:
            response.status_code = status.HTTP_200_OK
            return existing

    config = ExamConfig(
        exam=payload.exam,
        name=payload.name,
        marks_per_correct=payload.marks_per_correct,
        negative_marks=payload.negative_marks,
    )
    db.add(config)
    db.flush()

    for order_index, section_in in enumerate(payload.sections):
        section = _get_or_create_section(db, section_in.name)
        db.add(
            ExamConfigSection(
                exam_config_id=config.id,
                section_id=section.id,
                question_count=section_in.question_count,
                time_limit_seconds=section_in.time_limit_seconds,
                order_index=order_index,
            )
        )
    db.commit()
    db.refresh(config)
    return _to_out(db, config)


@router.get("", response_model=list[ExamConfigOut])
def list_exam_configs(
    db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> list[ExamConfigOut]:
    """Oldest config first; configs identical to an earlier one are left out,
    so duplicates that already exist in the database don't clutter pickers."""
    seen: set[tuple] = set()
    result: list[ExamConfigOut] = []
    for config in db.query(ExamConfig).order_by(ExamConfig.id).all():
        out = _to_out(db, config)
        signature = _out_signature(out)
        if signature in seen:
            continue
        seen.add(signature)
        result.append(out)
    return result
