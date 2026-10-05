"""Deterministic scoring formula (spec section 9): score = correct *
marks_per_correct - incorrect * negative_marks. negative_marks is a positive
magnitude, subtracted (never add a negative number in here -- that's the
sign-convention bug this module exists to prevent).
"""
from dataclasses import dataclass


@dataclass
class ScoreResult:
    attempted: int
    correct: int
    incorrect: int
    unattempted: int
    score: float


def score_responses(
    responses: list[tuple[str | None, str]],
    *,
    marks_per_correct: float,
    negative_marks: float,
) -> ScoreResult:
    """responses: list of (selected_option_key, correct_option_key). A
    response with selected_option_key=None is unattempted."""
    attempted = correct = incorrect = 0
    for selected, correct_key in responses:
        if selected is None:
            continue
        attempted += 1
        if selected == correct_key:
            correct += 1
        else:
            incorrect += 1
    unattempted = len(responses) - attempted
    score = correct * marks_per_correct - incorrect * negative_marks
    return ScoreResult(
        attempted=attempted,
        correct=correct,
        incorrect=incorrect,
        unattempted=unattempted,
        score=score,
    )
