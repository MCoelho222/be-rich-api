"""ASGI entry point: `uvicorn main:app` / `gunicorn -k uvicorn.workers.UvicornWorker main:app`."""

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.errors import install_error_handlers
from app.api.routes import auth, cron, entries, household, investments, recurrences, reference, reports, transfers
from app.db.session import get_db

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Be Rich API",
        version="0.2.0",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    install_error_handlers(app)

    @app.get(f"{API_PREFIX}/health", tags=["system"])
    def health(db: Session = Depends(get_db)) -> dict[str, str]:
        """Liveness and database connectivity (specs/operations.md §1.3)."""
        db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok"}

    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(household.router, prefix=API_PREFIX)
    # Before reference, so /cards/bills wins if a GET /cards/{card_id} is ever added
    app.include_router(reports.router, prefix=API_PREFIX)
    app.include_router(reference.router, prefix=API_PREFIX)
    app.include_router(entries.expenses_router, prefix=API_PREFIX)
    app.include_router(entries.incomes_router, prefix=API_PREFIX)
    app.include_router(recurrences.router, prefix=API_PREFIX)
    app.include_router(investments.router, prefix=API_PREFIX)
    app.include_router(transfers.router, prefix=API_PREFIX)
    app.include_router(cron.router, prefix=API_PREFIX)
    return app


app = create_app()
