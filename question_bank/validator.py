"""Validation for an imported question-bank JSON payload (spec section 3).

Pure-Python / no DB access, so a bank can be validated before touching the
database, and every problem is surfaced at once rather than failing on the
first bad row.
"""
from dataclasses import dataclass, field

VALID_DIFFICULTIES = {"easy", "medium", "hard"}


@dataclass
class QuestionBankValidationError:
    question_id: str | None
    index: int
    field: str
    message: str


@dataclass
class QuestionBankValidationResult:
    errors: list[QuestionBankValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def validate_question_bank(payload: dict) -> QuestionBankValidationResult:
    result = QuestionBankValidationResult()

    questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(questions, list) or not questions:
        result.errors.append(
            QuestionBankValidationError(None, -1, "questions", "'questions' must be a non-empty list")
        )
        return result

    seen_ids: dict[str, int] = {}

    for index, q in enumerate(questions):
        if not isinstance(q, dict):
            result.errors.append(
                QuestionBankValidationError(None, index, "question", "question entry must be an object")
            )
            continue

        qid = q.get("question_id")
        if not qid:
            result.errors.append(
                QuestionBankValidationError(None, index, "question_id", "question_id is missing")
            )
        elif qid in seen_ids:
            result.errors.append(
                QuestionBankValidationError(
                    qid,
                    index,
                    "question_id",
                    f"duplicate question_id '{qid}' (first seen at index {seen_ids[qid]})",
                )
            )
        else:
            seen_ids[qid] = index

        if not q.get("question"):
            result.errors.append(
                QuestionBankValidationError(qid, index, "question", "question text is missing")
            )

        if not q.get("section"):
            result.errors.append(
                QuestionBankValidationError(qid, index, "section", "section is missing")
            )

        if not q.get("topic"):
            result.errors.append(
                QuestionBankValidationError(qid, index, "topic", "topic is missing")
            )

        difficulty = q.get("difficulty")
        if not difficulty:
            result.errors.append(
                QuestionBankValidationError(qid, index, "difficulty", "difficulty is missing")
            )
        elif difficulty not in VALID_DIFFICULTIES:
            result.errors.append(
                QuestionBankValidationError(
                    qid,
                    index,
                    "difficulty",
                    f"difficulty '{difficulty}' must be one of {sorted(VALID_DIFFICULTIES)}",
                )
            )

        options = q.get("options")
        if not isinstance(options, dict) or len(options) < 2:
            result.errors.append(
                QuestionBankValidationError(
                    qid, index, "options", "options are missing or incomplete (need at least 2)"
                )
            )
            continue

        correct_answer = q.get("correct_answer")
        if not correct_answer:
            result.errors.append(
                QuestionBankValidationError(qid, index, "correct_answer", "correct_answer is missing")
            )
        elif correct_answer not in options:
            result.errors.append(
                QuestionBankValidationError(
                    qid,
                    index,
                    "correct_answer",
                    f"correct_answer '{correct_answer}' does not match any option key {sorted(options)}",
                )
            )

    return result
