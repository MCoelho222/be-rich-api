from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlmodel import and_, Session, select
from typing import List
from uuid import UUID
from app.models.Expense import ExpenseFixed, Expense
from app.helpers import get_entry_or_404, update_entry, delete_entry
from app.utils.pydantic_expense import ExpenseCreate, ExpenseRead
from app.connection_db import get_session

router = APIRouter()


@router.post("/", response_model=ExpenseRead, status_code=201)
def create_expense(entry: ExpenseCreate, session: Session = Depends(get_session)):
    db_entry = Expense.model_validate(entry)
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)
    return db_entry


@router.post("/fixed", response_model=ExpenseRead, status_code=201)
def create_expense_fixed(entry: ExpenseCreate, session: Session = Depends(get_session)):
    db_entry = ExpenseFixed.model_validate(entry)
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)
    return db_entry


@router.get("/", response_model=List[ExpenseRead])
def get_expenses_by_period(start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None), session: Session = Depends(get_session)):
    query_expense = select(Expense)
    query_expense_fixed = select(ExpenseFixed)
    
    if start_date and end_date:
        query_expense = query_expense.where(and_(Expense.created_at >= start_date, Expense.created_at <= end_date))
        query_expense_fixed = query_expense_fixed.where(and_(ExpenseFixed.created_at >= start_date, ExpenseFixed.created_at <= end_date))
    elif start_date:
        query_expense = query_expense.where(Expense.created_at >= start_date)
        query_expense_fixed = query_expense_fixed.where(ExpenseFixed.created_at >= start_date)
    elif end_date:
        query_expense = query_expense.where(Expense.created_at <= end_date)
        query_expense_fixed = query_expense_fixed.where(ExpenseFixed.created_at <= end_date)
    
    expenses = session.exec(query_expense).all()
    expenses_fixed = session.exec(query_expense_fixed).all()
    
    all_expenses = expenses + expenses_fixed

    return all_expenses


@router.get("/{entry_id}", response_model=ExpenseRead)
def get_expense(entry_id: UUID, session: Session = Depends(get_session)):
    entry = session.get(Expense, entry_id)
    if entry:
        return entry
    return get_entry_or_404(session, ExpenseFixed, entry_id, "Expense not found")


@router.get("/fixed/{entry_id}", response_model=ExpenseRead)
def get_expense_fixed(entry_id: UUID, session: Session = Depends(get_session)):
    return get_entry_or_404(session, ExpenseFixed, entry_id, "Expense not found")


@router.put("/{entry_id}", response_model=ExpenseRead)
def update_expense(entry_id: UUID, entry: ExpenseCreate, session: Session = Depends(get_session)):
    return update_entry(session, Expense, entry_id, entry, "Expense not found")


@router.put("/fixed/{entry_id}", response_model=ExpenseRead)
def update_expense_fixed(entry_id: UUID, entry: ExpenseCreate, session: Session = Depends(get_session)):
    return update_entry(session, ExpenseFixed, entry_id, entry, "Fixed Expense not found")


@router.delete("/{entry_id}")
def delete_expense(entry_id: UUID, session: Session = Depends(get_session)):
    return delete_entry(session, Expense, entry_id, "Expense not found")


@router.delete("/fixed/{entry_id}")
def delete_expense_fixed(entry_id: UUID, session: Session = Depends(get_session)):
    return delete_entry(session, ExpenseFixed, entry_id, "Expense not found")