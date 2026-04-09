from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlmodel import and_, Session, select
from typing import List
from uuid import UUID
from app.models.Expense import ExpenseFixed, Expense
from app.helpers import get_entry_or_404, update_entry, delete_entry, handle_installments_split
from app.utils.pydantic_expense import ExpenseCreate, ExpenseRead
from app.connection_db import get_session

router = APIRouter()


@router.post("/", response_model=ExpenseRead, status_code=201)
def create_expense(
    entry: ExpenseCreate,
    is_fixed: bool = Query(False),
    installments: int | None = Query(None),
    session: Session = Depends(get_session)):
    model_class = ExpenseFixed if is_fixed else Expense
    db_entry = model_class.model_validate(entry)

    db_entries = handle_installments_split(db_entry, installments) if installments else [db_entry]

    session.add_all(db_entries)
    session.commit()
    session.refresh(db_entries[0])

    return db_entries[0]


@router.get("/", response_model=List[ExpenseRead])
def get_expenses_by_period(
    is_fixed: bool = Query(False),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None), 
    session: Session = Depends(get_session)
):
    model_class = ExpenseFixed if is_fixed else Expense
    query = select(model_class)
    
    if start_date and end_date:
        query = query.where(and_(model_class.created_at >= start_date, model_class.created_at <= end_date))
    elif start_date:
        query = query.where(model_class.created_at >= start_date)
    elif end_date:
        query = query.where(model_class.created_at <= end_date)
    
    expenses = session.exec(query).all()

    return expenses


@router.get("/{entry_id}", response_model=ExpenseRead)
def get_expense(entry_id: UUID, is_fixed: bool = Query(False), session: Session = Depends(get_session)):
    model_class = ExpenseFixed if is_fixed else Expense
    return get_entry_or_404(session, model_class, entry_id, "Expense not found")


@router.put("/{entry_id}", response_model=ExpenseRead)
def update_expense(entry_id: UUID, entry: ExpenseCreate, is_fixed: bool = Query(False), session: Session = Depends(get_session)):
    model_class = ExpenseFixed if is_fixed else Expense
    return update_entry(session, model_class, entry_id, entry, "Expense not found")


@router.delete("/{entry_id}")
def delete_expense(entry_id: UUID, is_fixed: bool = Query(False), session: Session = Depends(get_session)):
    model_class = ExpenseFixed if is_fixed else Expense
    return delete_entry(session, model_class, entry_id, "Expense not found")