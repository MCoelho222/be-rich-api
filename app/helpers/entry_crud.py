from typing import Any, Protocol, TypeVar
from uuid import UUID
from fastapi import HTTPException
from sqlmodel import Session


ModelT = TypeVar("ModelT")


class SupportsModelDump(Protocol):
    def model_dump(self, *, exclude_unset: bool = False) -> dict[str, Any]:
        ...


def get_entry_or_404(session: Session, model: type[ModelT], entry_id: UUID, detail: str) -> ModelT:
    entry = session.get(model, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=detail)
    return entry


def update_entry(session: Session, model: type[ModelT], entry_id: UUID,
    entry: SupportsModelDump, detail: str) -> ModelT:
    db_entry = get_entry_or_404(session, model, entry_id, detail)
    entry_data = entry.model_dump(exclude_unset=True)

    for key, value in entry_data.items():
        setattr(db_entry, key, value)

    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)

    return db_entry


def delete_entry(session: Session, model: type[ModelT], entry_id: UUID, detail: str) -> ModelT:
    db_entry = get_entry_or_404(session, model, entry_id, detail)
    session.delete(db_entry)
    session.commit()
    return db_entry
