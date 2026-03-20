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
def create_income(entry: IncomeCreate, session: Session = Depends(get_session)):
    db_entry = Income.model_validate(entry)
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)
    return db_entry


@router.post("/fixed", response_model=IncomeRead, status_code=201)
def create_income_fixed(entry: IncomeCreate, session: Session = Depends(get_session)):
    db_entry = IncomeFixed.model_validate(entry)
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)
    return db_entry


@router.get("/", response_model=List[IncomeRead])
def read_incomes_by_period(start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None), session: Session = Depends(get_session)):
    query_income = select(Income)
    query_income_fixed = select(IncomeFixed)
    
    if start_date and end_date:
        query_income = query_income.where(and_(Income.created_at >= start_date, Income.created_at <= end_date))
        query_income_fixed = query_income_fixed.where(and_(IncomeFixed.created_at >= start_date, IncomeFixed.created_at <= end_date))
    elif start_date:
        query_income = query_income.where(Income.created_at >= start_date)
        query_income_fixed = query_income_fixed.where(IncomeFixed.created_at >= start_date)
    elif end_date:
        query_income = query_income.where(Income.created_at <= end_date)
        query_income_fixed = query_income_fixed.where(IncomeFixed.created_at <= end_date)
    
    incomes = session.exec(query_income).all()
    incomes_fixed = session.exec(query_income_fixed).all()
    
    all_incomes = incomes + incomes_fixed

    return all_incomes


@router.get("/{entry_id}", response_model=IncomeRead)
def get_income(entry_id: UUID, session: Session = Depends(get_session)):
    entry = session.get(Income, entry_id)
    if entry:
        return entry
    return get_entry_or_404(session, IncomeFixed, entry_id, "Income not found")


@router.get("/fixed/{entry_id}", response_model=IncomeRead)
def get_income_fixed(entry_id: UUID, session: Session = Depends(get_session)):
    return get_entry_or_404(session, IncomeFixed, entry_id, "Income not found")


@router.put("/{entry_id}", response_model=IncomeRead)
def update_income(entry_id: UUID, entry: IncomeCreate, session: Session = Depends(get_session)):
    return update_entry(session, Income, entry_id, entry, "Income not found")


@router.put("/fixed/{entry_id}", response_model=IncomeRead)
def update_income_fixed(entry_id: UUID, entry: IncomeCreate, session: Session = Depends(get_session)):
    return update_entry(session, IncomeFixed, entry_id, entry, "Fixed Income not found")


@router.delete("/{entry_id}")
def delete_income(entry_id: UUID, session: Session = Depends(get_session)):
    return delete_entry(session, Income, entry_id, "Income not found")


@router.delete("/fixed/{entry_id}")
def delete_income_fixed(entry_id: UUID, session: Session = Depends(get_session)):
    return delete_entry(session, IncomeFixed, entry_id, "Income not found")