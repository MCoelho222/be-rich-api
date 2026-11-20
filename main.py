"""ASGI entry point: `uvicorn main:app` / `gunicorn -k uvicorn.workers.UvicornWorker main:app`."""

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

API_PREFIX = "/api/v1"

app = FastAPI(title="Be Rich API", version="0.2.0", openapi_url=f"{API_PREFIX}/openapi.json")


@app.get(f"{API_PREFIX}/health", tags=["system"])
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    """Liveness and database connectivity (specs/operations.md §1.3)."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "ok"}
