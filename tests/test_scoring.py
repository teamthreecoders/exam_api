from evaluation.scoring import score_responses


def test_mixed_responses_apply_negative_marking():
    responses = [("A", "A"), ("B", "A"), (None, "C"), ("D", "D"), ("A", "B")]
    result = score_responses(responses, marks_per_correct=2, negative_marks=0.5)
    assert result.attempted == 4
    assert result.correct == 2
    assert result.incorrect == 2
    assert result.unattempted == 1
    assert result.score == 3.0


def test_all_correct():
    result = score_responses([("A", "A")] * 5, marks_per_correct=2, negative_marks=0.5)
    assert result.score == 10.0
    assert result.incorrect == 0
    assert result.unattempted == 0


def test_all_incorrect():
    result = score_responses([("A", "B")] * 5, marks_per_correct=2, negative_marks=0.5)
    assert result.score == -2.5
    assert result.correct == 0


def test_all_unattempted():
    result = score_responses([(None, "A")] * 5, marks_per_correct=2, negative_marks=0.5)
    assert result.score == 0.0
    assert result.attempted == 0
    assert result.unattempted == 5


def test_zero_questions():
    result = score_responses([], marks_per_correct=2, negative_marks=0.5)
    assert result.score == 0.0
    assert result.unattempted == 0


def test_no_negative_marking_scheme():
    result = score_responses([("A", "B"), (None, "C")], marks_per_correct=1, negative_marks=0)
    assert result.score == 0.0
