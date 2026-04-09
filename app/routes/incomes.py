from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlmodel import and_, Session, select
from typing import List
from uuid import UUID
from app.models.Income import IncomeFixed, Income
from app.helpers import get_entry_or_404, update_entry, delete_entry
from app.utils.pydantic_income import IncomeCreate, IncomeRead
from app.connection_db import get_session

router = APIRouter()


@router.post("/", response_model=IncomeRead, status_code=201)
def create_income(entry: IncomeCreate, is_fixed: bool = Query(False), session: Session = Depends(get_session)):
    model_class = IncomeFixed if is_fixed else Income
    db_entry = model_class.model_validate(entry)
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)

    return db_entry


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
def update_income(entry_id: UUID, entry: IncomeCreate, is_fixed: bool = Query(False), session: Session = Depends(get_session)):
    model_class = IncomeFixed if is_fixed else Income
    return update_entry(session, model_class, entry_id, entry, "Income not found")


@router.delete("/{entry_id}")
def delete_income(entry_id: UUID, is_fixed: bool = Query(False), session: Session = Depends(get_session)):
    model_class = IncomeFixed if is_fixed else Income
    return delete_entry(session, model_class, entry_id, "Income not found")