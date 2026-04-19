from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlmodel import and_, Session, select
from typing import List
from uuid import UUID
from app.models.Income import IncomeFixed, Income
from app.helpers import get_entry_or_404, update_entry, handle_installments_split, find_entry_in_both_tables
from app.utils.pydantic_income import IncomeCreate, IncomeRead
from app.connection_db import get_session

router = APIRouter()


@router.post("/", response_model=IncomeRead, status_code=201)
def create_income(
    entry: IncomeCreate,
    is_fixed: bool = Query(False),
    installments: int | None = Query(None),
    session: Session = Depends(get_session)):
    model_class = IncomeFixed if is_fixed else Income
    db_entry = model_class.model_validate(entry)
    
    db_entries = handle_installments_split(db_entry, installments) if installments else [db_entry]
    
    session.add_all(db_entries)
    session.commit()
    session.refresh(db_entries[0])

    return db_entries[0]


@router.get("/", response_model=List[IncomeRead])
def read_incomes_by_period(
    is_fixed: bool = Query(False),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None), 
    session: Session = Depends(get_session)
):
    model_class = IncomeFixed if is_fixed else Income
    query = select(model_class)
    
    if start_date and end_date:
        query = query.where(and_(model_class.created_at >= start_date, model_class.created_at <= end_date))
    elif start_date:
        query = query.where(model_class.created_at >= start_date)
    elif end_date:
        query = query.where(model_class.created_at <= end_date)
    
    incomes = session.exec(query).all()

    return incomes


@router.get("/{entry_id}", response_model=IncomeRead)
def get_income(entry_id: UUID, is_fixed: bool = Query(False), session: Session = Depends(get_session)):
    model_class = IncomeFixed if is_fixed else Income
    return get_entry_or_404(session, model_class, entry_id, "Income not found")


@router.put("/{entry_id}", response_model=IncomeRead)
def update_income(
    entry_id: UUID,
    entry: IncomeCreate,
    is_fixed: bool = Query(False),
    installments: int | None = Query(None),
    session: Session = Depends(get_session)):
    
    # Find the entry in either table and check if it needs migration
    db_entry, needs_migration = find_entry_in_both_tables(
        session, IncomeFixed, Income, entry_id, is_fixed, "Income not found"
    )
    
    if needs_migration:
        # Entry is in wrong table - we need to migrate it
        target_model = IncomeFixed if is_fixed else Income
        
        # If it's an installment series, find all related entries in the old table
        if db_entry.installment and "/" in db_entry.installment:
            from app.helpers.entry_crud import find_related_installments
            old_model = type(db_entry)
            related_entries = find_related_installments(session, old_model, db_entry)
            
            # Delete all old entries from the wrong table
            for old_entry in related_entries:
                session.delete(old_entry)
        else:
            # Just delete the single entry
            session.delete(db_entry)
        
        # Create new entry in the correct table with updated data
        new_entry = target_model.model_validate(entry)
        
        # Handle installments if provided
        if installments and installments > 1:
            db_entries = handle_installments_split(new_entry, installments)
            session.add_all(db_entries)
            session.commit()
            session.refresh(db_entries[0])
            return db_entries[0]
        else:
            session.add(new_entry)
            session.commit()
            session.refresh(new_entry)
            return new_entry
    else:
        # Entry is in correct table - do normal update
        target_model = IncomeFixed if is_fixed else Income
        return update_entry(session, target_model, entry_id, entry, installments, "Income not found")


@router.delete("/{entry_id}")
def delete_income(entry_id: UUID, is_fixed: bool = Query(False), session: Session = Depends(get_session)):
    model_class = IncomeFixed if is_fixed else Income
    db_entry = get_entry_or_404(session, model_class, entry_id, "Income not found")
    session.delete(db_entry)
    session.commit()
    return db_entry