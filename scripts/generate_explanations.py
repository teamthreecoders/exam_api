"""Bulk-generate AI explanations for question versions that lack one.

Usage (from backend/):
    python -m scripts.generate_explanations [--bank-id N] [--limit N]
                                            [--workers 2] [--regenerate]

Resumable: only versions with a NULL ai_explanation are processed (unless
--regenerate), and each result is committed as soon as it arrives, so an
interrupted run loses nothing. Only each question's current version is
processed. Keep --workers low for a self-hosted GPU.
"""
import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy.orm import joinedload

from database.session import SessionLocal
from models.question_bank import Question, QuestionVersion
from services.explanation_service import ExplanationError, generate_explanation, is_enabled


def _target_ids(bank_id: int | None, limit: int | None, regenerate: bool) -> list[int]:
    with SessionLocal() as db:
        q = (
            db.query(QuestionVersion.id)
            .join(Question, Question.current_version_id == QuestionVersion.id)
            .filter(Question.is_deleted.is_(False))
        )
        if bank_id is not None:
            q = q.filter(Question.question_bank_id == bank_id)
        if not regenerate:
            q = q.filter(QuestionVersion.ai_explanation.is_(None))
        q = q.order_by(QuestionVersion.id)
        if limit:
            q = q.limit(limit)
        return [row[0] for row in q.all()]


def _process(version_id: int) -> tuple[int, str | None, str | None]:
    """Returns (id, text, error). Own session per task -- sessions aren't thread-safe."""
    with SessionLocal() as db:
        version = (
            db.query(QuestionVersion)
            .options(
                joinedload(QuestionVersion.options),
                joinedload(QuestionVersion.section),
                joinedload(QuestionVersion.topic),
            )
            .filter(QuestionVersion.id == version_id)
            .one()
        )
        try:
            version.ai_explanation = generate_explanation(version)
        except ExplanationError as exc:
            return version_id, None, str(exc)
        db.commit()
        return version_id, version.ai_explanation, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bank-id", type=int, help="only this question bank")
    parser.add_argument("--limit", type=int, help="stop after N questions (try 5 first)")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--regenerate", action="store_true", help="overwrite existing AI explanations")
    args = parser.parse_args()

    if not is_enabled():
        print("Set LLM_BASE_URL and LLM_MODEL in .env first.", file=sys.stderr)
        return 1

    ids = _target_ids(args.bank_id, args.limit, args.regenerate)
    print(f"{len(ids)} question(s) to process with {args.workers} worker(s)")

    done = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_process, i) for i in ids]
        for fut in as_completed(futures):
            version_id, _, error = fut.result()
            if error:
                failed += 1
                print(f"[{done + failed}/{len(ids)}] version {version_id} FAILED: {error}")
            else:
                done += 1
                print(f"[{done + failed}/{len(ids)}] version {version_id} ok")

    print(f"Done. {done} generated, {failed} failed (re-run to retry failures).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
