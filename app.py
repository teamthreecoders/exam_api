"""Vercel entrypoint. Kept separate from main.py (the local-dev entrypoint,
run via `uvicorn main:app --reload`) so vercel.json's expected `app.py`
module path doesn't dictate the local dev command, and vice versa."""
from main import app

__all__ = ["app"]
