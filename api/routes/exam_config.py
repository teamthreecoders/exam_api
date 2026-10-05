from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from api.deps import get_current_user
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


@router.post("", response_model=ExamConfigOut, status_code=status.HTTP_201_CREATED)
def create_exam_config(
    payload: ExamConfigCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ExamConfigOut:
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
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[ExamConfigOut]:
    return [_to_out(db, c) for c in db.query(ExamConfig).all()]
