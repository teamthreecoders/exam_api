"""AI explanations for question versions, via any OpenAI-compatible server.

The correct answer is always passed to the model: it explains rather than
solves, which keeps small open-source models from "explaining" a wrong
answer. Output is requested as JSON, validated, and flattened to plain text
(stored in QuestionVersion.ai_explanation).
"""
import json
import re

from openai import OpenAI
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from core.config import settings
from models.question_bank import QuestionVersion


class ExplanationError(Exception):
    pass


class _Explanation(BaseModel):
    summary: str
    steps: list[str] = []
    why_others_wrong: dict[str, str] = {}
    shortcut_tip: str | None = None


SYSTEM_PROMPT = (
    "You are an SSC CGL exam tutor. The correct answer is provided -- never "
    "contradict it; explain why it is correct. Be concise and exam-focused. "
    "Reply with ONLY a JSON object of this shape: "
    '{"summary": "1-2 sentence reason", "steps": ["step 1", "..."], '
    '"why_others_wrong": {"A": "short reason"}, "shortcut_tip": "optional string or null"}. '
    "Do not include the correct option in why_others_wrong."
)

_client: OpenAI | None = None


def is_enabled() -> bool:
    return bool(settings.LLM_BASE_URL and settings.LLM_MODEL)


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=settings.LLM_MAX_RETRIES,
        )
    return _client


def _build_user_prompt(version: QuestionVersion) -> str:
    options = "\n".join(f"{o.option_key}. {o.option_text}" for o in version.options)
    return (
        f"Section: {version.section.name} / {version.topic.name}\n"
        f"Question: {version.question_text}\n"
        f"Options:\n{options}\n"
        f"Correct answer: {version.correct_option_key}"
    )


def _extract_json(raw: str) -> dict:
    # Reasoning models emit <think>...</think>; others wrap JSON in code fences.
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in LLM output")
    return json.loads(raw[start : end + 1])


def _format(exp: _Explanation, correct_key: str) -> str:
    parts = [exp.summary.strip()]
    if exp.steps:
        parts.append("\n".join(f"{i}. {s.strip()}" for i, s in enumerate(exp.steps, 1)))
    wrong = {k: v for k, v in exp.why_others_wrong.items() if k != correct_key}
    if wrong:
        parts.append("Why the others are wrong:\n" + "\n".join(f"{k}: {v.strip()}" for k, v in wrong.items()))
    if exp.shortcut_tip:
        parts.append(f"Tip: {exp.shortcut_tip.strip()}")
    return "\n\n".join(parts)


def generate_explanation(version: QuestionVersion) -> str:
    """Calls the LLM and returns plain-text explanation; does not persist."""
    if not is_enabled():
        raise ExplanationError("AI explanations are not configured")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(version)},
    ]
    last_error: Exception | None = None
    for _ in range(2):  # one retry on malformed output
        try:
            resp = _get_client().chat.completions.create(
                model=settings.LLM_MODEL,
                messages=messages,
                temperature=0.2,
                **({"extra_body": {"reasoning": {"enabled": True}}} if settings.LLM_REASONING else {}),
            )
            parsed = _Explanation.model_validate(_extract_json(resp.choices[0].message.content or ""))
            return _format(parsed, version.correct_option_key)
        except (ValueError, ValidationError) as exc:  # includes JSONDecodeError
            last_error = exc
        except Exception as exc:  # network / server errors from the SDK
            raise ExplanationError(f"LLM request failed: {exc}") from exc
    raise ExplanationError(f"LLM returned invalid explanation: {last_error}")


def ensure_explanation(db: Session, version: QuestionVersion) -> str:
    """Returns the cached AI explanation, generating and saving it if missing."""
    if version.ai_explanation:
        return version.ai_explanation
    version.ai_explanation = generate_explanation(version)
    db.commit()
    return version.ai_explanation
