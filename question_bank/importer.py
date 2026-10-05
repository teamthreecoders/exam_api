"""Persists a validated question-bank JSON payload. Always creates fresh
Question + QuestionVersion(version_number=1) rows -- editing an existing
question is a separate update flow (not yet built) that creates a new
version rather than mutating this one, per the immutability requirement.
"""
from sqlalchemy.orm import Session

from models.question_bank import Difficulty, Question, QuestionBank, QuestionOption, QuestionVersion
from models.section_topic import Section, Topic


def _get_or_create_section(db: Session, name: str) -> Section:
    section = db.query(Section).filter_by(name=name).one_or_none()
    if section is None:
        section = Section(name=name)
        db.add(section)
        db.flush()
    return section


def _get_or_create_topic(db: Session, section: Section, name: str) -> Topic:
    topic = db.query(Topic).filter_by(section_id=section.id, name=name).one_or_none()
    if topic is None:
        topic = Topic(section_id=section.id, name=name)
        db.add(topic)
        db.flush()
    return topic


def import_question_bank(db: Session, *, payload: dict, source_filename: str | None) -> QuestionBank:
    bank = QuestionBank(
        name=payload.get("test_name", "Imported Question Bank"),
        exam=payload.get("exam", "SSC CGL"),
        source_filename=source_filename,
    )
    db.add(bank)
    db.flush()

    for q in payload["questions"]:
        section = _get_or_create_section(db, q["section"])
        topic = _get_or_create_topic(db, section, q["topic"])

        question = Question(question_bank_id=bank.id, external_question_id=q["question_id"])
        db.add(question)
        db.flush()

        version = QuestionVersion(
            question_id=question.id,
            version_number=1,
            section_id=section.id,
            topic_id=topic.id,
            subtopic=q.get("subtopic"),
            difficulty=Difficulty(q["difficulty"]),
            question_text=q["question"],
            correct_option_key=q["correct_answer"],
            explanation=q.get("explanation"),
            source=q.get("source"),
            year=q.get("year"),
            shift=q.get("shift"),
        )
        db.add(version)
        db.flush()

        for order_index, (key, text) in enumerate(q["options"].items()):
            db.add(
                QuestionOption(
                    question_version_id=version.id,
                    option_key=key,
                    option_text=text,
                    order_index=order_index,
                )
            )

        question.current_version_id = version.id

    db.commit()
    db.refresh(bank)
    return bank
