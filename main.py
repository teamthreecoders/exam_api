from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import attempts, auth, exam_config, question_bank, tests
from core.config import settings

app = FastAPI(title="SSC CGL Mock Test & Analytics Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(question_bank.router)
app.include_router(exam_config.router)
app.include_router(tests.router)
app.include_router(attempts.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
