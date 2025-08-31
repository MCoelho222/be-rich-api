from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from typing import List
from uuid import UUID
from app.models.models import Entry
from app.utils.pydantic_models import EntryCreate, EntryRead
from app.connection_db import get_session

router = APIRouter()


# Create Entry
@router.post("/", response_model=EntryRead, status_code=201)
def create_entry(entry: EntryCreate, session: Session = Depends(get_session)):
    db_entry = Entry.model_validate(entry)
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)

    return db_entry

# Read Entries
@router.get("/", response_model=List[EntryRead])
def read_entries(session: Session = Depends(get_session)):
    entries = session.exec(select(Entry)).all()

    return entries


@router.get("/{entry_id}", response_model=EntryRead)
def get_entry(entry_id: UUID, session: Session = Depends(get_session)):
    entry = session.get(Entry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


# Update Entry
@router.put("/{entry_id}", response_model=EntryRead)
def update_entry(entry_id: UUID, entry: EntryCreate, session: Session = Depends(get_session)):
    db_entry = session.get(Entry, entry_id)

    if not db_entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    entry_data = entry.model_dump(exclude_unset=True)

    for key, value in entry_data.items():
        setattr(db_entry, key, value)

    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)

    return db_entry

# Delete Entry
@router.delete("/{entry_id}")
def delete_entry(entry_id: UUID, session: Session = Depends(get_session)):
    db_entry = session.get(Entry, entry_id)

    if not db_entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    session.delete(db_entry)
    session.commit()

    return db_entry